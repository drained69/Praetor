from __future__ import annotations

import argparse
import os

from .core import Coordinator, Job, JobResult, WorkerProfile
from .memory import InMemoryStore, SibylMemoryStore
from .verification import BasicVerifier


def executor(worker: WorkerProfile, job: Job) -> JobResult:
    if worker.name == "risk-reviewer-v1" and job.id.startswith("fail"):
        return JobResult(worker.name, False, "Incomplete risk report", "missed liquidity-lock evidence")
    return JobResult(worker.name, True, f"Verified {job.category} report for: {job.task}")


def run(db: str | None = None) -> None:
    memory = SibylMemoryStore(db) if db else InMemoryStore()
    first = Coordinator(memory, [WorkerProfile("risk-reviewer-v1", ["risk"])], executor)
    first.run(Job("Review a Base lending protocol", "risk", id="fail-001"))
    second = Coordinator(memory, [
        WorkerProfile("risk-reviewer-v1", ["risk"]),
        WorkerProfile("risk-reviewer-v2", ["risk"], successes=3),
    ], executor, verifier=BasicVerifier())
    result = second.run(Job("Review a second Base lending protocol", "risk", id="fresh-002"))
    print(f"Fresh session routed to: {result.worker}")
    print(f"Verification: {'passed' if result.verified else 'failed'}")
    print(f"Outcome: {'success' if result.success else 'failure'}")


def deletion_test() -> None:
    """Show how persisted history changes routing."""
    def execute(worker: WorkerProfile, job: Job) -> JobResult:
        return JobResult(worker.name, True, "review complete")

    workers = [WorkerProfile("known-failure", ["risk"]), WorkerProfile("clean", ["risk"])]
    remembered_store = InMemoryStore()
    Coordinator(remembered_store, [workers[0]], execute).run(Job("seed", "risk"))
    profile = remembered_store.load_worker("known-failure")
    profile["requires_review"] = True
    profile["failures"] = 1
    remembered_store.save_worker(profile)
    remembered = Coordinator(remembered_store, workers, execute).choose_worker(Job("next", "risk"))
    empty = Coordinator(InMemoryStore(), [workers[0]], execute).choose_worker(Job("next", "risk"))
    print("With Sibyl:   known-failure is flagged; selected", remembered.name)
    print("Without it:   no history exists; selected", empty.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.getenv("PRAETOR_DB"))
    parser.add_argument("--deletion-test", action="store_true", help="compare routing with and without persisted memory")
    args = parser.parse_args()
    deletion_test() if args.deletion_test else run(args.db)


if __name__ == "__main__":
    main()
