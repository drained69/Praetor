from praetor.core import Coordinator, Job, JobResult, WorkerProfile
from praetor.memory import InMemoryStore


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


# ---------------------------------------------------------------------------
# Task-aware routing — the "fourth Sibyl primitive" (semantic search).
#
# The router downweights any worker whose recorded failure notes semantically
# match the current task. That turns flat reputation ("worker failed once")
# into task-aware reputation ("worker failed on THIS kind of work").
# ---------------------------------------------------------------------------


def _mk_store_with_history():
    """Two candidates:
      - atlas: HIGH reliability except previously failed on liquidity-lock work
      - clean: cold-start, no history
    """
    m = InMemoryStore()
    m.save_worker({
        "name": "atlas", "capabilities": ["risk"], "wallet": "", "acp_agent": "",
        "max_value_usdc": None,
        "successes": 5, "failures": 1, "requires_review": False,
        "failure_notes": ["missed liquidity-lock evidence on Base lending review"],
    })
    m.save_worker({
        "name": "clean", "capabilities": ["risk"], "wallet": "", "acp_agent": "",
        "max_value_usdc": None,
        "successes": 0, "failures": 0, "requires_review": False,
        "failure_notes": [],
    })
    return m


def test_semantic_downweight_avoids_worker_who_failed_on_similar_task():
    """A task text that resembles a worker's past failure downweights them."""
    store = _mk_store_with_history()
    coordinator = Coordinator(store, [], lambda w, j: JobResult(w.name, True, "ok"))
    chosen = coordinator.choose_worker(Job("audit a liquidity-lock in stablecoin", "risk"))
    # atlas has FAR higher reliability but the semantic hit demotes them.
    assert chosen.name == "clean", "semantic downweight should route around atlas"


def test_unrelated_task_leaves_reputation_ranking_intact():
    """When the current task is UNRELATED to any past failure, the strongest
    reputation wins — even if the strongest reputation has failures on record."""
    store = _mk_store_with_history()
    coordinator = Coordinator(store, [], lambda w, j: JobResult(w.name, True, "ok"))
    chosen = coordinator.choose_worker(Job("check oracle staleness on Chainlink", "risk"))
    assert chosen.name == "atlas", "no semantic overlap -> ranking picks the stronger worker"


def test_semantic_hit_ignored_for_workers_with_zero_failures():
    """A clean worker (no failure_notes) matching the task text on other fields
    must NOT be penalized — the penalty is only for past-failure similarity."""
    m = InMemoryStore()
    m.save_worker({
        "name": "liquidity-specialist", "capabilities": ["risk"], "wallet": "",
        "acp_agent": "", "max_value_usdc": None,
        "successes": 4, "failures": 0, "requires_review": False,
        "failure_notes": [],
    })
    m.save_worker({
        "name": "generic", "capabilities": ["risk"], "wallet": "",
        "acp_agent": "", "max_value_usdc": None,
        "successes": 4, "failures": 0, "requires_review": False,
        "failure_notes": [],
    })
    coordinator = Coordinator(m, [], lambda w, j: JobResult(w.name, True, "ok"))
    chosen = coordinator.choose_worker(Job("audit a liquidity lock", "risk"))
    # Both have equal reputation; tiebreak lands on max() ordering. The point
    # is neither triggered a semantic penalty, so `liquidity-specialist` isn't
    # demoted just because its NAME matches the task text.
    assert chosen.name in {"liquidity-specialist", "generic"}
    # And crucially: the specialist is NOT in the semantic-hit set.
    hits = m.search_similar_failure_workers("audit a liquidity lock")
    assert "liquidity-specialist" not in hits


def test_routing_trace_records_semantic_hits_and_candidate_ranking():
    """run() populates JobResult.routing_trace with the full decision record."""
    store = _mk_store_with_history()
    coordinator = Coordinator(store, [], lambda w, j: JobResult(w.name, True, "ok"))
    result = coordinator.run(Job("liquidity-lock audit on Aave", "risk"))
    trace = result.routing_trace
    assert trace["chosen"] == "clean"
    assert "atlas" in trace["semantic_matches"]
    names = [c["name"] for c in trace["candidates"]]
    assert {"atlas", "clean"} == set(names)
    atlas_row = next(c for c in trace["candidates"] if c["name"] == "atlas")
    clean_row = next(c for c in trace["candidates"] if c["name"] == "clean")
    assert atlas_row["semantic_hit"] is True
    assert clean_row["semantic_hit"] is False
    assert clean_row["chosen"] is True
