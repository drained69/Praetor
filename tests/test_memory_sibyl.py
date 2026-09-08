"""Round-trip tests against the real ``sibyl-memory-client`` SDK.

These exercise the documented Sibyl Memory API (docs.sibyllabs.org):
``MemoryClient.local``, ``set_entity``/``get_entity``, ``list_entities`` for
enumeration, and ``write_event``/``read_events``. They are skipped when the SDK
is not installed so the core suite stays dependency-light.
"""

import tempfile

import pytest

pytest.importorskip("sibyl_memory_client")

from praetor.core import Coordinator, Job, JobResult, WorkerProfile
from praetor.memory import SibylMemoryStore


def _store():
    directory = tempfile.mkdtemp()
    return SibylMemoryStore(directory + "/memory.db")


def test_sibyl_round_trip_worker_and_events():
    store = _store()
    store.save_worker(
        {
            "name": "risk-reviewer-v1",
            "capabilities": ["risk"],
            "wallet": "",
            "acp_agent": "",
            "max_value_usdc": None,
            "successes": 0,
            "failures": 0,
            "requires_review": False,
            "failure_notes": [],
        }
    )
    loaded = store.load_worker("risk-reviewer-v1")
    assert loaded["name"] == "risk-reviewer-v1"
    assert loaded["capabilities"] == ["risk"]
    assert store.load_worker("does-not-exist") is None

    store.record_event({"type": "job_assigned", "worker": "risk-reviewer-v1"})
    found = store.find_events("job_assigned")
    assert any(e.get("worker") == "risk-reviewer-v1" for e in found)


def test_list_workers_enumerates_beyond_fts_limit():
    """`list_workers` must return every worker, not the FTS default page of 20."""
    store = _store()
    names = [f"worker-{i:03d}" for i in range(35)]
    for name in names:
        store.save_worker(
            {
                "name": name,
                "capabilities": ["risk"],
                "wallet": "",
                "acp_agent": "",
                "max_value_usdc": None,
                "successes": 0,
                "failures": 0,
                "requires_review": False,
                "failure_notes": [],
            }
        )
    listed = store.list_workers()
    assert len(listed) == 35, f"expected all 35 workers, got {len(listed)}"
    assert set(listed) == set(names)


def test_memory_backed_routing_survives_a_fresh_coordinator():
    """The load-bearing behavior, end to end against real Sibyl Memory."""
    store = _store()

    def execute(worker, job):
        failed = worker.name == "risk-reviewer-v1"
        return JobResult(
            worker.name,
            not failed,
            "ok" if not failed else "incomplete",
            "missed liquidity-lock evidence" if failed else "",
        )

    # Session one: the v1 reviewer fails and the failure is persisted.
    Coordinator(store, [WorkerProfile("risk-reviewer-v1", ["risk"])], execute).run(
        Job("first review", "risk")
    )
    assert store.load_worker("risk-reviewer-v1")["requires_review"] is True

    # Session two: a brand-new coordinator reads history and avoids the flagged worker.
    result = Coordinator(
        store,
        [
            WorkerProfile("risk-reviewer-v1", ["risk"]),
            WorkerProfile("risk-reviewer-v2", ["risk"], successes=3),
        ],
        execute,
    ).run(Job("second review", "risk"))
    assert result.worker == "risk-reviewer-v2"
    assert result.success is True


def test_semantic_search_over_failure_notes_via_real_sibyl(tmp_path):
    """The fourth primitive: FTS5-backed semantic search that only surfaces
    workers whose STORED failure notes overlap with the query — clean workers
    matching on other fields are not falsely flagged."""
    store = SibylMemoryStore(str(tmp_path / "sem.db"))
    store.save_worker({
        "name": "atlas", "capabilities": ["risk"], "wallet": "", "acp_agent": "",
        "max_value_usdc": None,
        "successes": 5, "failures": 1, "requires_review": False,
        "failure_notes": ["missed liquidity-lock evidence on Base lending review"],
    })
    store.save_worker({
        "name": "clean", "capabilities": ["risk"], "wallet": "", "acp_agent": "",
        "max_value_usdc": None,
        "successes": 4, "failures": 0, "requires_review": False,
        "failure_notes": [],
    })

    hits_related = store.search_similar_failure_workers("audit a liquidity-lock in a stablecoin")
    assert "atlas" in hits_related, "atlas's failure notes should match"
    assert "clean" not in hits_related, "no failure notes -> never a hit"

    hits_unrelated = store.search_similar_failure_workers("check oracle staleness")
    assert "atlas" not in hits_unrelated, "unrelated task should NOT surface atlas"
