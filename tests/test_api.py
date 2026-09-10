"""End-to-end tests for the live product API (in-memory, no partner credentials)."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # Force the in-memory backend and no partner credentials for a hermetic test.
    for var in (
        "PRAETOR_DB",
        "PRAETOR_ADMIN_TOKEN",
        "BASE_RPC_URL",
        "BASE_USDC_ADDRESS",
        "BASE_PRIVATE_KEY",
        "VIRTUALS_AGENT_WALLET_ADDRESS",
        "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Keep the test hermetic: never touch the network for partner wiring.
    monkeypatch.setenv("PRAETOR_NO_PARTNERS", "1")
    # These tests exercise the demo flow; production defaults keep seeding off.
    monkeypatch.setenv("PRAETOR_SEED_DEMO_WORKERS", "1")
    import praetor.api as api

    importlib.reload(api)
    return TestClient(api.app)


@pytest.fixture()
def operator_client(monkeypatch):
    """Operator-mode server: no demo seeding, admin token required for writes."""
    for var in (
        "PRAETOR_DB",
        "BASE_RPC_URL",
        "BASE_USDC_ADDRESS",
        "BASE_PRIVATE_KEY",
        "VIRTUALS_AGENT_WALLET_ADDRESS",
        "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PRAETOR_NO_PARTNERS", "1")
    monkeypatch.delenv("PRAETOR_SEED_DEMO_WORKERS", raising=False)
    monkeypatch.setenv("PRAETOR_ADMIN_TOKEN", "test-admin-token")
    import praetor.api as api

    importlib.reload(api)
    return TestClient(api.app)


def test_health_reports_memory_backend(client):
    body = client.get("/api/health").json()
    assert body["memory_backend"] == "in-memory"
    assert "base" in body and "virtuals" in body
    assert body["stacks_active"] == 0


def test_health_reports_builder_score(client):
    bs = client.get("/api/health").json()["builder_score"]
    # Sibyl Memory is the mandatory foundation, always active.
    assert bs["required_stack"]["name"] == "Sibyl Memory"
    assert bs["required_stack"]["active"] is True
    # With no partner credentials no multiplier stack is verified.
    assert bs["verified_partner_stacks"] == 0
    assert bs["multiplier"] == 1.00
    assert bs["stacks"]["base"]["verified_real_work"] is False
    assert bs["stacks"]["virtuals"]["verified_real_work"] is False


def test_state_lists_seed_workers(client):
    workers = client.get("/api/state").json()["workers"]
    names = {w["name"] for w in workers}
    assert {"risk-reviewer-v1", "risk-reviewer-v2"} <= names


def test_memory_changes_routing_across_requests(client):
    # First: force the chosen worker to fail, seeding a failure in memory.
    first = client.post("/api/jobs", json={"force_failure": True}).json()
    assert first["success"] is False
    failed_worker = first["routed_to"]

    # A fresh request (fresh coordinator, same memory) must avoid the flagged worker.
    second = client.post("/api/jobs", json={"force_failure": False}).json()
    assert second["success"] is True
    assert second["routed_to"] != failed_worker

    flagged = [w for w in second["workers"] if w["name"] == failed_worker][0]
    assert flagged["requires_review"] is True
    assert flagged["failures"] >= 1


def test_deletion_test_is_load_bearing(client):
    body = client.post("/api/deletion-test").json()
    assert body["load_bearing"] is True
    assert body["with_memory_selected"] != body["without_memory_selected"]


def test_deletion_test_also_reachable_via_get(client):
    """Judges hit the URL in a browser — GET must return the same JSON."""
    body = client.get("/api/deletion-test").json()
    assert body["load_bearing"] is True
    assert body["with_memory_selected"] != body["without_memory_selected"]


def test_unknown_category_is_rejected(client):
    r = client.post("/api/jobs", json={"category": "unknown"})
    assert r.status_code == 400


def test_negative_payment_value_is_rejected(client):
    r = client.post("/api/jobs", json={"value_usdc": -1})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Operator mode — real deployment surface (no demo seeding, admin token
# required, worker CRUD is the source of truth for candidate lists).
# ---------------------------------------------------------------------------

def _hdr(token="test-admin-token"):
    return {"X-Admin-Token": token}


def test_operator_mode_starts_with_no_workers(operator_client):
    """A production deployment must not ship with demo workers pre-registered."""
    body = operator_client.get("/api/state").json()
    assert body["workers"] == []


def test_health_reveals_operator_signals(operator_client):
    body = operator_client.get("/api/health").json()
    op = body["operator"]
    assert op["seeded_demo_workers"] is False
    assert op["admin_token_required"] is True


def test_auth_status_validates_operator_token(operator_client):
    assert operator_client.get("/api/auth").status_code == 401
    assert operator_client.get("/api/auth", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert operator_client.get("/api/auth", headers=_hdr()).json() == {"authenticated": True}


def test_admin_token_required_on_write_endpoints(operator_client):
    # Missing token → 401
    r = operator_client.post("/api/workers", json={"name": "n", "capabilities": ["risk"]})
    assert r.status_code == 401
    # Wrong token → 401
    r = operator_client.post(
        "/api/workers", json={"name": "n", "capabilities": ["risk"]},
        headers={"X-Admin-Token": "wrong"},
    )
    assert r.status_code == 401


def test_register_worker_and_route_job_end_to_end(operator_client):
    # Register a real worker
    r = operator_client.post(
        "/api/workers",
        json={"name": "risk-analyst-mainnet", "capabilities": ["risk"],
              "wallet": "0x000000000000000000000000000000000000dEaD"},
        headers=_hdr(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["worker"]["name"] == "risk-analyst-mainnet"

    # It shows up in state
    workers = operator_client.get("/api/state").json()["workers"]
    assert {w["name"] for w in workers} == {"risk-analyst-mainnet"}

    # Now submit a job — coordinator uses the registered worker
    r = operator_client.post(
        "/api/jobs", json={"task": "audit protocol", "category": "risk", "value_usdc": 0.0},
        headers=_hdr(),
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["routed_to"] == "risk-analyst-mainnet"


def test_registering_worker_preserves_reputation_history(operator_client):
    """Editing a worker's capabilities/wallet must not reset successes/failures."""
    operator_client.post(
        "/api/workers",
        json={"name": "atlas", "capabilities": ["risk"], "wallet": "0xaa"},
        headers=_hdr(),
    )
    # Manually simulate a job by directly manipulating the memory store —
    # equivalent to a completed run leaving history in place.
    import praetor.api as api

    profile = api.relay.memory.load_worker("atlas")
    profile["successes"] = 5
    profile["failures"] = 1
    profile["failure_notes"] = ["missed evidence"]
    api.relay.memory.save_worker(profile)

    # Now the operator edits the worker (adds a new capability)
    r = operator_client.post(
        "/api/workers",
        json={"name": "atlas", "capabilities": ["risk", "audit"], "wallet": "0xaa"},
        headers=_hdr(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is False
    assert body["worker"]["successes"] == 5
    assert body["worker"]["failures"] == 1
    assert body["worker"]["failure_notes"] == ["missed evidence"]


def test_delete_worker_archives(operator_client):
    operator_client.post(
        "/api/workers", json={"name": "temp", "capabilities": ["risk"]},
        headers=_hdr(),
    )
    r = operator_client.delete("/api/workers/temp", headers=_hdr())
    assert r.status_code == 200
    assert r.json() == {"archived": "temp"}
    # Worker is out of the active set
    workers = operator_client.get("/api/state").json()["workers"]
    assert "temp" not in {w["name"] for w in workers}
    # Second removal → 404
    r = operator_client.delete("/api/workers/temp", headers=_hdr())
    assert r.status_code == 404


def test_reset_refused_in_operator_mode(operator_client):
    r = operator_client.post("/api/reset", headers=_hdr())
    assert r.status_code == 409
    assert "demo seeding is disabled" in r.json()["detail"]


def test_worker_with_no_capabilities_rejected(operator_client):
    r = operator_client.post(
        "/api/workers", json={"name": "empty", "capabilities": []},
        headers=_hdr(),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Deep Sibyl integration — HOT state, REFERENCE receipts, cross-tier search.
# ---------------------------------------------------------------------------

def test_job_writes_reference_receipt_and_bumps_hot_stats(operator_client):
    operator_client.post(
        "/api/workers", json={"name": "w", "capabilities": ["risk"]}, headers=_hdr()
    )
    out = operator_client.post(
        "/api/jobs", json={"task": "audit vault", "category": "risk", "value_usdc": 0},
        headers=_hdr(),
    ).json()
    assert out["success"] is True

    # REFERENCE tier: an immutable receipt exists for this job.
    import praetor.api as api
    # find the job id from the completion event
    ev = [e for e in api.relay.memory.find_events("job_completed")]
    assert ev, "expected a job_completed event"
    job_id = ev[-1]["job_id"]
    r = operator_client.get(f"/api/receipts/{job_id}")
    assert r.status_code == 200, r.text
    receipt = r.json()["receipt"]
    assert receipt["worker"] == "w"
    assert receipt["success"] is True

    # HOT tier: coordinator stats counter advanced.
    health = operator_client.get("/api/health").json()
    stats = health["memory"]["stats"]
    assert stats.get("jobs_total", 0) >= 1
    assert stats.get("jobs_succeeded", 0) >= 1


def test_missing_receipt_is_404(operator_client):
    r = operator_client.get("/api/receipts/does-not-exist")
    assert r.status_code == 404


def test_cross_tier_search_finds_worker_and_receipt(operator_client):
    operator_client.post(
        "/api/workers",
        json={"name": "liquidity-specialist", "capabilities": ["risk"]},
        headers=_hdr(),
    )
    operator_client.post(
        "/api/jobs", json={"task": "audit liquidity lock", "category": "risk", "value_usdc": 0},
        headers=_hdr(),
    )
    body = operator_client.get("/api/search", params={"q": "liquidity"}).json()
    tiers = {r["tier"] for r in body["results"]}
    # Worker (warm) and/or receipt (reference) should surface for the query.
    assert body["results"], "cross-tier search returned nothing"
    assert tiers & {"warm", "reference"}


def test_health_exposes_five_tier_map(operator_client):
    mem = operator_client.get("/api/health").json()["memory"]
    assert set(mem["tiers"]) == {"warm", "cold", "hot", "reference", "search"}
    assert "storage" in mem
