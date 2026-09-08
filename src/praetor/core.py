from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol
from uuid import uuid4

from .memory import MemoryStore


@dataclass(frozen=True)
class Job:
    task: str
    category: str
    value_usdc: float = 0.0
    id: str = field(default_factory=lambda: uuid4().hex[:10])


@dataclass
class JobResult:
    worker: str
    success: bool
    output: str
    reason: str = ""
    verified: bool = False
    verification_reason: str = ""
    payment_reference: str = ""
    acp_reference: str = ""
    routing_trace: dict = field(default_factory=dict)


class ResultVerifier(Protocol):
    def verify(self, job: Job, result: JobResult) -> tuple[bool, str]: ...


@dataclass
class WorkerProfile:
    name: str
    capabilities: list[str]
    wallet: str = ""
    acp_agent: str = ""
    max_value_usdc: float | None = None
    successes: int = 0
    failures: int = 0
    requires_review: bool = False
    failure_notes: list[str] = field(default_factory=list)

    @property
    def reliability(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total else 0.5


class Coordinator:
    def __init__(
        self,
        memory: MemoryStore,
        workers: list[WorkerProfile],
        executor: Callable[[WorkerProfile, Job], JobResult],
        verifier: ResultVerifier | None = None,
        payment=None,
        acp=None,
    ):
        self.memory = memory
        self.executor = executor
        self.verifier = verifier
        self.payment = payment
        self.acp = acp
        for worker in workers:
            existing = self.memory.load_worker(worker.name)
            if existing:
                worker = WorkerProfile(**existing)
            self.memory.save_worker(asdict(worker))
            self.memory.record_event({"type": "worker_registered", "worker": worker.name})

    def choose_worker(self, job: Job) -> WorkerProfile:
        return self._choose_worker_with_trace(job)[0]

    def _choose_worker_with_trace(self, job: Job) -> tuple[WorkerProfile, dict]:
        """Rank candidates and return the winner alongside a routing trace.

        Ranking factors, in priority order:
          1. Not currently marked ``requires_review``.
          2. No *task-aware* semantic penalty — a worker whose recorded
             failure notes semantically match the current task text is
             pushed BELOW workers whose past failures don't resemble this
             work.  Uses Sibyl's semantic search over the ``relay_worker``
             category. Sibyl-less stores mirror the same contract with a
             deterministic token-overlap check.
          3. Higher reliability (successes / total).
          4. Fewer historical failures (tiebreaker).
        """
        candidates: list[WorkerProfile] = []
        for name in self._worker_names():
            data = self.memory.load_worker(name)
            if not data or job.category not in data["capabilities"]:
                continue
            candidates.append(WorkerProfile(**data))
        if not candidates:
            raise LookupError(f"No worker supports category {job.category!r}")

        try:
            semantic_hits = self.memory.search_similar_failure_workers(job.task)
        except Exception:  # noqa: BLE001 - never let search failure block routing
            semantic_hits = set()

        def rank(w: WorkerProfile) -> tuple:
            related = w.name in semantic_hits and w.failures > 0
            # sort descending — higher tuple wins
            return (not w.requires_review, not related, w.reliability, -w.failures)

        ranked = sorted(candidates, key=rank, reverse=True)
        chosen = ranked[0]
        trace = {
            "chosen": chosen.name,
            "task": job.task,
            "semantic_matches": sorted(semantic_hits),
            "candidates": [
                {
                    "name": w.name,
                    "reliability": round(w.reliability, 3),
                    "successes": w.successes,
                    "failures": w.failures,
                    "requires_review": w.requires_review,
                    "semantic_hit": w.name in semantic_hits and w.failures > 0,
                    "chosen": w.name == chosen.name,
                }
                for w in ranked
            ],
        }
        return chosen, trace

    def run(self, job: Job) -> JobResult:
        worker, routing_trace = self._choose_worker_with_trace(job)
        self.memory.record_event({"type": "job_assigned", "job_id": job.id, "category": job.category, "worker": worker.name})
        acp_reference = ""
        try:
            if self.acp:
                acp_reference = self.acp.delegate(worker.acp_agent or worker.name, job.task).reference
            result = self.executor(worker, job)
        except Exception as exc:
            result = JobResult(worker.name, False, "", f"execution failed: {exc}")
        if self.verifier:
            result.verified, result.verification_reason = self.verifier.verify(job, result)
            if not result.verified and result.success:
                result.success = False
                result.reason = result.verification_reason or result.reason
        result.acp_reference = acp_reference
        if result.success and self.payment:
            if worker.max_value_usdc is not None and job.value_usdc > worker.max_value_usdc:
                result.success = False
                result.verified = False
                result.reason = f"job value exceeds worker limit of {worker.max_value_usdc} USDC"
            elif not worker.wallet:
                result.success = False
                result.verified = False
                result.reason = "worker has no payment wallet configured"
            else:
                try:
                    result.payment_reference = self.payment.pay_worker(worker.wallet, job.value_usdc, job.id).reference
                except Exception as exc:
                    result.success = False
                    result.reason = f"payment failed: {exc}"
        profile_data = self.memory.load_worker(worker.name) or asdict(worker)
        profile = WorkerProfile(**profile_data)
        if result.success:
            profile.successes += 1
        else:
            profile.failures += 1
            profile.requires_review = True
            if result.reason:
                profile.failure_notes.append(result.reason)
        self.memory.save_worker(asdict(profile))
        self.memory.record_event({
            "type": "job_completed", "job_id": job.id, "category": job.category,
            "worker": worker.name, "success": result.success, "verified": result.verified,
            "reason": result.reason, "verification_reason": result.verification_reason,
            "acp_reference": result.acp_reference, "payment_reference": result.payment_reference,
        })
        self._write_receipt(job, worker, result)
        self._bump_stats(result)
        result.routing_trace = routing_trace
        return result

    def _write_receipt(self, job: Job, worker: WorkerProfile, result: JobResult) -> None:
        """Persist an immutable settlement receipt in Sibyl's REFERENCE tier.

        A receipt is the durable, addressable record of a completed job —
        keyed by ``receipt:<job_id>`` so any later process can look up exactly
        what happened, what was verified, and which on-chain references settled
        it, without replaying the event log.
        """
        put_reference = getattr(self.memory, "put_reference", None)
        if not callable(put_reference):
            return
        receipt = {
            "job_id": job.id,
            "task": job.task,
            "category": job.category,
            "value_usdc": job.value_usdc,
            "worker": worker.name,
            "success": result.success,
            "verified": result.verified,
            "reason": result.reason,
            "acp_reference": result.acp_reference,
            "payment_reference": result.payment_reference,
        }
        try:
            put_reference(
                f"receipt:{job.id}",
                receipt,
                metadata={
                    "worker": worker.name,
                    "success": result.success,
                    "settled": bool(result.payment_reference),
                },
            )
        except Exception:  # noqa: BLE001 - a receipt failure must never fail the job
            pass

    def _bump_stats(self, result: JobResult) -> None:
        """Maintain a live coordinator scoreboard in Sibyl's HOT state tier."""
        get_state = getattr(self.memory, "get_state", None)
        set_state = getattr(self.memory, "set_state", None)
        if not (callable(get_state) and callable(set_state)):
            return
        try:
            stats = get_state("coordinator:stats") or {
                "jobs_total": 0, "jobs_succeeded": 0, "jobs_failed": 0, "settlements": 0
            }
            stats["jobs_total"] = stats.get("jobs_total", 0) + 1
            if result.success:
                stats["jobs_succeeded"] = stats.get("jobs_succeeded", 0) + 1
            else:
                stats["jobs_failed"] = stats.get("jobs_failed", 0) + 1
            if result.payment_reference:
                stats["settlements"] = stats.get("settlements", 0) + 1
            set_state("coordinator:stats", stats)
        except Exception:  # noqa: BLE001 - stats are best-effort telemetry
            pass

    def _worker_names(self) -> list[str]:
        return self.memory.list_workers()
