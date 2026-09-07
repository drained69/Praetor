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
        candidates: list[WorkerProfile] = []
        for name in self._worker_names():
            data = self.memory.load_worker(name)
            if not data or job.category not in data["capabilities"]:
                continue
            candidates.append(WorkerProfile(**data))
        if not candidates:
            raise LookupError(f"No worker supports category {job.category!r}")

        # Historical failures are intentionally stronger than a cold-start tie.
        return max(candidates, key=lambda w: (not w.requires_review, w.reliability, -w.failures))

    def run(self, job: Job) -> JobResult:
        worker = self.choose_worker(job)
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
        return result

    def _worker_names(self) -> list[str]:
        return self.memory.list_workers()
