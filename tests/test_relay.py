from sibyl_relay.core import Coordinator, Job, JobResult, WorkerProfile
from sibyl_relay.memory import InMemoryStore


def test_fresh_session_avoids_worker_with_persisted_failure():
    memory = InMemoryStore()

    def execute(worker, job):
        return JobResult(worker.name, worker.name != "bad", "ok", "missed critical evidence" if worker.name == "bad" else "")

    Coordinator(memory, [WorkerProfile("bad", ["risk"])], execute).run(Job("first", "risk"))

    result = Coordinator(memory, [WorkerProfile("bad", ["risk"]), WorkerProfile("good", ["risk"], successes=4)], execute).run(Job("second", "risk"))
    assert result.worker == "good"
    assert memory.load_worker("bad")["requires_review"] is True


def test_memory_is_load_bearing_for_routing():
    memory = InMemoryStore()

    def execute(worker, job):
        return JobResult(worker.name, True, "ok")

    Coordinator(memory, [WorkerProfile("only", ["risk"])], execute)
    assert Coordinator(memory, [], execute).choose_worker(Job("task", "risk")).name == "only"


def test_unsupported_category_is_rejected():
    coordinator = Coordinator(InMemoryStore(), [WorkerProfile("researcher", ["research"])], lambda w, j: JobResult(w.name, True, "ok"))
    try:
        coordinator.choose_worker(Job("task", "risk"))
    except LookupError as exc:
        assert "risk" in str(exc)
    else:
        raise AssertionError("expected LookupError")


def test_deletion_test_has_different_routing_outcome():
    memory = InMemoryStore()
    memory.save_worker({"name": "failed", "capabilities": ["risk"], "successes": 0, "failures": 1, "requires_review": True, "failure_notes": []})
    memory.save_worker({"name": "clean", "capabilities": ["risk"], "successes": 0, "failures": 0, "requires_review": False, "failure_notes": []})
    coordinator = Coordinator(memory, [], lambda w, j: JobResult(w.name, True, "ok"))
    assert coordinator.choose_worker(Job("risk", "risk")).name == "clean"
    empty = Coordinator(InMemoryStore(), [WorkerProfile("failed", ["risk"])], lambda w, j: JobResult(w.name, True, "ok"))
    assert empty.choose_worker(Job("risk", "risk")).name == "failed"
