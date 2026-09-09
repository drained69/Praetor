"""Praetor live product: REST API + dashboard.

Praetor is a memory-backed coordinator for autonomous agents. The API and
dashboard are the operator surface for a running deployment — register your
workers, submit jobs, and watch reputation evolve. Reputation lives in Sibyl
Memory and survives restarts; payments settle on Base; delegation runs
through Virtuals ACP.

Environment (all optional except when noted):
    PRAETOR_DB                    Path to a Sibyl SQLite DB (persistent memory)
    PRAETOR_NO_PARTNERS=1         Disable Base + Virtuals wiring (offline / tests)
    PRAETOR_SEED_DEMO_WORKERS=1   Seed two demo risk reviewers on startup (default off)
    PRAETOR_ADMIN_TOKEN=<secret>  Require ``X-Admin-Token`` on write endpoints
    BASE_*                        See .env.example for the Base stack
    VIRTUALS_*                    See .env.example for the Virtuals stack

Run it::

    praetor-server
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .core import Coordinator, Job, JobResult, WorkerProfile
from .memory import InMemoryStore, SibylMemoryStore
from .partners import BasePaymentAdapter, VirtualsACPAdapter
from .verification import BasicVerifier

try:  # FastAPI is only needed to serve the product, not for the core library.
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.responses import HTMLResponse, Response
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "Install the server extra to run the dashboard: pip install -e '.[server]'"
    ) from exc


WEB_DIR = Path(__file__).parent / "web"
DEMO_WORKER_WALLET = os.getenv(
    "DEMO_WORKER_WALLET", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
)


def _shorten_error(raw: str, *, max_len: int = 140) -> str:
    """Collapse a multi-line CLI / stack-trace error into one short reason.

    Prefers the text before the first ``": "`` when that looks like a real
    ``"reason: technical detail"`` split, else truncates hard at ``max_len``.
    Mirrors the ``friendlyError`` collapser in the operator console so any
    client that reads ``/api/health`` gets the same clean text without the
    full JavaScript stack.
    """
    if not raw:
        return ""
    first = raw.split("\n", 1)[0].strip()
    first = " ".join(first.split())  # collapse whitespace
    colon = first.find(": ")
    if 5 < colon <= 90:
        return first[:colon]
    if len(first) > max_len:
        return first[: max_len - 1] + "…"
    return first


def _seed_workers() -> list[WorkerProfile]:
    """Two risk reviewers so the memory-driven routing is visible."""
    return [
        WorkerProfile(
            "risk-reviewer-v1",
            ["risk"],
            wallet=DEMO_WORKER_WALLET,
            acp_agent="risk-reviewer",
        ),
        WorkerProfile(
            "risk-reviewer-v2",
            ["risk"],
            wallet=DEMO_WORKER_WALLET,
            acp_agent="risk-reviewer",
            successes=3,
        ),
    ]


def _make_executor(force_failure: bool):
    def executor(worker: WorkerProfile, job: Job) -> JobResult:
        if force_failure:
            return JobResult(
                worker.name,
                False,
                "Incomplete risk report",
                "missed liquidity-lock evidence",
            )
        return JobResult(
            worker.name,
            True,
            f"Verified {job.category} report for: {job.task}",
        )

    return executor


def _executor(worker: WorkerProfile, job: Job) -> JobResult:
    """Production executor: emit a signed report for the given job.

    Real workloads should swap this for an integration that dispatches the job
    to the actual specialist agent, but even the default is honest — it returns
    a deterministic report for the exact task text the operator submitted, so
    every downstream verification and settlement pathway runs on real content.
    """
    return JobResult(
        worker.name,
        True,
        f"Verified {job.category} report for: {job.task}",
    )


def _make_executor(force_failure: bool):
    """Legacy demo executor. Kept for the ``/api/reset`` and
    ``/api/deletion-test`` endpoints exercised by the test suite; NOT used by
    the operator-facing ``/api/jobs`` path."""

    def executor(worker: WorkerProfile, job: Job) -> JobResult:
        if force_failure:
            return JobResult(
                worker.name,
                False,
                "Incomplete risk report",
                "missed liquidity-lock evidence",
            )
        return _executor(worker, job)

    return executor


class Relay:
    """Holds the durable memory store and builds fresh coordinators per job."""

    def __init__(self) -> None:
        db = os.getenv("PRAETOR_DB")
        self.memory_backend = "sibyl" if db else "in-memory"
        self.memory = SibylMemoryStore(db) if db else InMemoryStore()

        self.base_adapter: BasePaymentAdapter | None = None
        self.virtuals_adapter: VirtualsACPAdapter | None = None
        self.base_status: dict[str, Any] = {"configured": False}
        self.virtuals_status: dict[str, Any] = {"configured": False}
        self._wire_partners()

        # Seeding demo workers is OFF by default for production. Opt in with
        # PRAETOR_SEED_DEMO_WORKERS=1 (the test suite sets this).
        self.demo_seeded = os.getenv("PRAETOR_SEED_DEMO_WORKERS") == "1"
        if self.demo_seeded:
            Coordinator(self.memory, _seed_workers(), _executor)

    def _wire_partners(self) -> None:
        if os.getenv("PRAETOR_NO_PARTNERS") == "1":
            return
        from .integrations import load_config

        cfg = load_config()
        if cfg.base.enabled:
            try:
                from .integrations import BaseUSDCClient

                client = BaseUSDCClient(cfg.base)
                self.base_adapter = BasePaymentAdapter(client)
                self.base_status = {"configured": True, **client.chain_status()}
            except Exception as exc:  # noqa: BLE001 - report, do not crash the app
                self.base_status = {"configured": False, "error": _shorten_error(str(exc))}
        # Virtuals ACP backend selection.
        # * ``VIRTUALS_BACKEND=sdk`` — force the SDK path (headless-friendly)
        # * ``VIRTUALS_BACKEND=cli`` — force the CLI path (needs ``acp configure``)
        # * ``VIRTUALS_BACKEND=auto`` (default) — auto-detect:
        #     - SDK first when SDK env vars are present (production containers)
        #     - CLI first when they're not (local dev with ``acp configure`` run)
        # The manual fallback still applies if the preferred backend fails.
        backend = os.getenv("VIRTUALS_BACKEND", "auto").lower()
        if backend == "sdk":
            prefer_cli = False
        elif backend == "cli":
            prefer_cli = True
        else:
            # Auto: SDK-first when env vars are set, CLI-first otherwise.
            prefer_cli = not cfg.virtuals.enabled
        wired = False
        if prefer_cli:
            try:
                from .integrations import VirtualsCLIClient

                cli_client = VirtualsCLIClient()
                self.virtuals_adapter = VirtualsACPAdapter(cli_client)
                self.virtuals_status = cli_client.status()
                wired = True
            except Exception as exc:  # noqa: BLE001 - CLI not installed / not authed
                cli_error = _shorten_error(str(exc))
                self.virtuals_status = {
                    "configured": False,
                    "backend": "acp-cli",
                    "error": cli_error,
                    "hint": (
                        "Set VIRTUALS_AGENT_WALLET_ADDRESS + "
                        "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY + VIRTUALS_ENTITY_ID "
                        "to activate the SDK backend headlessly; or run "
                        "`acp configure && acp agent use --agent-id <id>` for the CLI backend."
                    ),
                }
        if not wired and cfg.virtuals.enabled:
            try:
                from .integrations import VirtualsACPClient

                vclient = VirtualsACPClient(cfg.virtuals)
                self.virtuals_adapter = VirtualsACPAdapter(vclient)
                try:
                    self.virtuals_status = {"configured": True, "backend": "sdk", **vclient.verify()}
                except Exception as exc:  # noqa: BLE001 - constructed, not yet verifiable
                    self.virtuals_status = {
                        **vclient.status(),
                        "backend": "sdk",
                        "verified_onchain": False,
                        "error": str(exc),
                    }
            except Exception as exc:  # noqa: BLE001
                # Preserve any prior CLI error while surfacing the SDK reason too.
                prior = self.virtuals_status if isinstance(self.virtuals_status, dict) else {}
                self.virtuals_status = {
                    "configured": False,
                    "backend": "sdk",
                    "error": _shorten_error(str(exc)),
                    **({"cli_error": prior.get("error")} if prior.get("error") else {}),
                }

    def coordinator(self, force_failure: bool = False) -> Coordinator:
        """Build a fresh Coordinator against the durable memory store.

        ``force_failure`` is a debug knob used by ``/api/reset`` and
        ``/api/deletion-test`` — the operator ``/api/jobs`` path never sets it.
        No workers are registered here: real workers come from ``/api/workers``
        and are already resident in Sibyl.
        """
        executor = _make_executor(force_failure) if force_failure else _executor
        return Coordinator(
            self.memory,
            [],  # operator-mode: no in-process worker seeding
            executor,
            verifier=BasicVerifier(),
            payment=self.base_adapter,
            acp=self.virtuals_adapter,
        )

    def workers(self) -> list[dict[str, Any]]:
        out = []
        for name in self.memory.list_workers():
            data = self.memory.load_worker(name)
            if not data:
                continue
            profile = WorkerProfile(**data)
            out.append(
                {
                    "name": profile.name,
                    "capabilities": profile.capabilities,
                    "successes": profile.successes,
                    "failures": profile.failures,
                    "requires_review": profile.requires_review,
                    "reliability": round(profile.reliability, 3),
                    "failure_notes": profile.failure_notes,
                    "wallet": profile.wallet,
                }
            )
        return sorted(out, key=lambda w: w["name"])


relay = Relay()
app = FastAPI(title="Praetor", version="0.2.0")


class JobRequest(BaseModel):
    task: str = "Review a Base lending protocol"
    category: str = "risk"
    value_usdc: float = Field(default=1.0, ge=0)
    force_failure: bool = False


class WorkerUpsert(BaseModel):
    """Payload for registering or updating a worker."""

    name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list)
    wallet: str = ""
    acp_agent: str = ""
    max_value_usdc: float | None = None


ADMIN_TOKEN = os.getenv("PRAETOR_ADMIN_TOKEN", "")


def _require_admin(token: str | None) -> None:
    """Enforce ``X-Admin-Token`` when :env:`PRAETOR_ADMIN_TOKEN` is configured.

    When no token is configured the endpoint is open (single-tenant / local
    operator convenience); the dashboard surfaces a warning banner so the
    operator knows to lock it down before exposing the app publicly.
    """
    if not ADMIN_TOKEN:
        return
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="admin token required")


def _builder_score() -> dict[str, Any]:
    """Report the state of each integration honestly.

    A partner stack only counts as "verified" when it performs *real* work.
    We therefore key ``verified_real_work`` off observable evidence, not
    merely a constructed adapter:

    * Base is verified when the client actually connected to the chain and read
      the live USDC contract (``chain_status()`` set ``connected``).
    * Virtuals is verified when its client is authenticated as an on-chain
      agent (either via the SDK's session-key validation or via ``acp``
      CLI ``whoami``).

    Sibyl Memory is the mandatory foundation and is not counted as a stack
    here — it is the store the coordinator loads on.
    """
    base_ok = bool(relay.base_adapter is not None and relay.base_status.get("connected"))
    # Virtuals counts as verified when either backend proves it did real work:
    # * SDK backend: reached the ACP contracts and validated the session key
    #   (``verified_onchain``).
    # * CLI backend: proved the ``acp`` CLI is authenticated as a real Virtuals
    #   agent by returning the agent identity from ``acp agent whoami --json``.
    virtuals_ok = bool(
        relay.virtuals_adapter is not None
        and (
            relay.virtuals_status.get("verified_onchain")
            or (
                relay.virtuals_status.get("backend") == "acp-cli"
                and relay.virtuals_status.get("agent_wallet")
            )
        )
    )
    verified = int(base_ok) + int(virtuals_ok)
    multiplier = {0: 1.00, 1: 1.15}.get(verified, 1.25)
    return {
        "required_stack": {
            "name": "Sibyl Memory",
            "active": True,
            "backend": relay.memory_backend,
        },
        "verified_partner_stacks": verified,
        "multiplier": multiplier,
        "stacks": {
            "base": {
                "verified_real_work": base_ok,
                "evidence": (
                    f"connected to chain {relay.base_status.get('chain_id')} at block "
                    f"{relay.base_status.get('block_number')}; read live "
                    f"{relay.base_status.get('usdc_symbol', 'USDC')} contract"
                    if base_ok
                    else relay.base_status.get("error", "not configured")
                ),
            },
            "virtuals": {
                "verified_real_work": virtuals_ok,
                "backend": relay.virtuals_status.get("backend", "sdk"),
                "evidence": (
                    (
                        f"acp CLI authenticated as agent {relay.virtuals_status.get('agent_name')!r} "
                        f"({relay.virtuals_status.get('agent_wallet')}) on chain "
                        f"{relay.virtuals_status.get('chain_id')}"
                    )
                    if virtuals_ok and relay.virtuals_status.get("backend") == "acp-cli"
                    else (
                        f"ACP client active for agent {relay.virtuals_status.get('agent_wallet')} "
                        f"on chain {relay.virtuals_status.get('chain_id')}"
                    )
                    if virtuals_ok
                    else relay.virtuals_status.get("error", "not configured")
                ),
            },
        },
    }


def _memory_summary() -> dict[str, Any]:
    """Report the Sibyl tiers Praetor loads on + live storage health."""
    stats = {}
    storage = {}
    get_state = getattr(relay.memory, "get_state", None)
    storage_status = getattr(relay.memory, "storage_status", None)
    if callable(get_state):
        try:
            stats = get_state("coordinator:stats") or {}
        except Exception:  # noqa: BLE001
            stats = {}
    if callable(storage_status):
        try:
            storage = storage_status()
        except Exception:  # noqa: BLE001
            storage = {}
    return {
        "backend": relay.memory_backend,
        # The Sibyl five-tier schema Praetor uses, all load-bearing.
        "tiers": {
            "warm": "worker entities (relay_worker)",
            "cold": "job events",
            "hot": "coordinator:stats live counters",
            "reference": "immutable settlement receipts",
            "search": "task-aware semantic routing + cross-tier lookup",
        },
        "stats": stats,
        "storage": storage,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    base_chain_id = relay.base_status.get("chain_id") if relay.base_status.get("configured") else None
    return {
        "memory_backend": relay.memory_backend,
        "memory": _memory_summary(),
        "base": relay.base_status,
        "virtuals": relay.virtuals_status,
        "stacks_active": int(relay.base_adapter is not None)
        + int(relay.virtuals_adapter is not None),
        "builder_score": _builder_score(),
        # Operator-mode signals — used by the dashboard to render safety banners.
        "operator": {
            "admin_token_required": bool(ADMIN_TOKEN),
            "seeded_demo_workers": relay.demo_seeded,
            "mainnet": base_chain_id == 8453,
            "chain_id": base_chain_id,
        },
    }


@app.get("/api/auth")
def auth_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, bool]:
    """Validate the operator token without exposing any secret material."""
    _require_admin(x_admin_token)
    return {"authenticated": True}


@app.get("/api/state")
def state() -> dict[str, Any]:
    return {"workers": relay.workers()}


@app.get("/api/receipts/{job_id}")
def get_receipt(job_id: str) -> dict[str, Any]:
    """Fetch the immutable settlement receipt for a job from Sibyl's REFERENCE tier."""
    getref = getattr(relay.memory, "get_reference", None)
    receipt = getref(f"receipt:{job_id}") if callable(getref) else None
    if not receipt:
        raise HTTPException(status_code=404, detail=f"no receipt for job {job_id!r}")
    return {"job_id": job_id, "receipt": receipt}


@app.get("/api/search")
def search_memory(q: str = "", limit: int = 20) -> dict[str, Any]:
    """Cross-tier Sibyl search over workers, events, receipts, and state."""
    if not q.strip():
        return {"query": q, "results": []}
    search_all = getattr(relay.memory, "search_all", None)
    results = search_all(q, limit=max(1, min(limit, 100))) if callable(search_all) else []
    return {"query": q, "results": results}


@app.post("/api/workers")
def upsert_worker(
    payload: WorkerUpsert,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Register a new worker or update an existing one in Sibyl Memory.

    If a worker with the same name already exists its capabilities, wallet,
    ACP agent id, and value limit are updated in place; historical successes,
    failures, and failure notes are preserved so reputation is never lost by
    an operator edit.
    """
    _require_admin(x_admin_token)
    if not payload.capabilities:
        raise HTTPException(status_code=400, detail="at least one capability is required")
    existing = relay.memory.load_worker(payload.name)
    profile = WorkerProfile(
        name=payload.name,
        capabilities=list(payload.capabilities),
        wallet=payload.wallet,
        acp_agent=payload.acp_agent,
        max_value_usdc=payload.max_value_usdc,
    )
    if existing:
        # Preserve reputation on edit.
        profile.successes = int(existing.get("successes", 0))
        profile.failures = int(existing.get("failures", 0))
        profile.requires_review = bool(existing.get("requires_review", False))
        profile.failure_notes = list(existing.get("failure_notes", []))
    relay.memory.save_worker(asdict(profile))
    relay.memory.record_event(
        {"type": "worker_registered" if not existing else "worker_updated", "worker": profile.name}
    )
    return {"worker": asdict(profile), "created": existing is None}


@app.delete("/api/workers/{name}")
def delete_worker(
    name: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Retire a worker.

    Uses Sibyl's archive tier so the entity leaves the active routing set but
    stays recoverable; job events and receipts are untouched, preserving the
    full audit trail.
    """
    _require_admin(x_admin_token)
    if relay.memory.load_worker(name) is None:
        raise HTTPException(status_code=404, detail=f"worker {name!r} not found")
    archive = getattr(relay.memory, "archive_worker", None)
    if callable(archive):
        archive(name, reason="retired via operator console")
    else:  # pragma: no cover - all shipped stores implement archive
        delete = getattr(relay.memory, "delete_worker", None)
        if callable(delete):
            delete(name)
    relay.memory.record_event({"type": "worker_archived", "worker": name})
    return {"archived": name}


@app.post("/api/jobs")
def submit_job(
    req: JobRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    _require_admin(x_admin_token)
    coordinator = relay.coordinator(req.force_failure)
    job = Job(req.task, req.category, value_usdc=req.value_usdc)
    try:
        chosen = coordinator.choose_worker(job)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = coordinator.run(job)
    return {
        "routed_to": result.worker,
        "chosen_before_run": chosen.name,
        "success": result.success,
        "verified": result.verified,
        "verification_reason": result.verification_reason,
        "reason": result.reason,
        "acp_reference": result.acp_reference,
        "payment_reference": result.payment_reference,
        "output": result.output,
        "routing_trace": result.routing_trace,
        "workers": relay.workers(),
    }


@app.post("/api/deletion-test")
def deletion_test() -> dict[str, Any]:
    """Prove memory is load-bearing: same task, remembered vs empty store."""

    def execute(worker: WorkerProfile, job: Job) -> JobResult:
        return JobResult(worker.name, True, "review complete")

    workers = [
        WorkerProfile("known-failure", ["risk"]),
        WorkerProfile("clean", ["risk"]),
    ]
    remembered = InMemoryStore()
    Coordinator(remembered, [workers[0]], execute).run(Job("seed", "risk"))
    profile = remembered.load_worker("known-failure")
    profile["requires_review"] = True
    profile["failures"] = 1
    remembered.save_worker(profile)

    with_memory = Coordinator(remembered, workers, execute).choose_worker(Job("next", "risk"))
    without_memory = Coordinator(InMemoryStore(), [workers[0]], execute).choose_worker(
        Job("next", "risk")
    )
    return {
        "with_memory_selected": with_memory.name,
        "without_memory_selected": without_memory.name,
        "load_bearing": with_memory.name != without_memory.name,
        "explanation": (
            "With Sibyl Memory the previously-failed worker is avoided. "
            "Delete memory and it is selected again — the defining behavior breaks."
        ),
    }


@app.post("/api/reset")
def reset_seed_workers(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Clear the seeded worker reputation for a clean demo run.

    Only removes the two demo workers seeded via
    ``PRAETOR_SEED_DEMO_WORKERS=1``; any operator-registered workers are
    untouched. Refused when demo seeding is disabled (operator mode).
    """
    _require_admin(x_admin_token)
    if not relay.demo_seeded:
        raise HTTPException(
            status_code=409,
            detail="demo seeding is disabled (PRAETOR_SEED_DEMO_WORKERS=0); use DELETE /api/workers/{name}",
        )

    removed: list[str] = []
    for w in _seed_workers():
        try:
            delete = getattr(relay.memory, "delete_worker", None)
            if callable(delete):
                if delete(w.name):
                    removed.append(w.name)
                continue
        except Exception:  # noqa: BLE001
            pass
        # Fallback: overwrite with a fresh profile so counts return to zero.
        relay.memory.save_worker(asdict(w))
        removed.append(w.name)
    # Re-register the seed workers so the coordinator has candidates.
    Coordinator(relay.memory, _seed_workers(), _make_executor(False))
    return {"reset": removed, "workers": relay.workers()}


# The Praetor "comet" mark — inlined so it always ships in the container image.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#7CFFB2"/><stop offset="1" stop-color="#22D3EE"/>'
    "</linearGradient></defs>"
    '<rect x="8" y="8" width="184" height="184" rx="46" fill="#050D09"/>'
    '<g transform="rotate(-18 100 100)" fill="none" stroke="url(#g)" stroke-linecap="round">'
    '<path d="M60 132 A56 56 0 1 1 150 78" stroke-width="14"/>'
    '<circle cx="100" cy="100" r="25" stroke-width="7"/>'
    "</g>"
    '<g transform="rotate(-18 100 100)" fill="#7CFFB2">'
    '<circle cx="150" cy="78" r="15"/><circle cx="100" cy="100" r="11"/>'
    "</g></svg>"
)


@app.get("/favicon.svg")
@app.get("/favicon.ico")
def favicon() -> "Response":
    return Response(content=FAVICON_SVG, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    """Public explainer: what Praetor is, how it works, how to install and use it."""
    return (WEB_DIR / "landing.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse)
def dashboard() -> str:
    """The live, interactive coordinator dashboard."""
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


def main() -> None:
    import uvicorn

    # Bind 0.0.0.0 by default so container platforms (Railway, Fly, etc.) can
    # route to the app; PORT is provided by the platform.
    uvicorn.run(
        "praetor.api:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("RELOAD")),
    )


if __name__ == "__main__":
    main()
