"""End-to-end tests for the live product API (in-memory, no partner credentials)."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # Force the in-memory backend and no partner credentials for a hermetic test.
    for var in (
        "SIBYL_RELAY_DB",
        "BASE_RPC_URL",
        "BASE_USDC_ADDRESS",
        "BASE_PRIVATE_KEY",
        "VIRTUALS_AGENT_WALLET_ADDRESS",
        "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Keep the test hermetic: never touch the network for partner wiring.
    monkeypatch.setenv("SIBYL_RELAY_NO_PARTNERS", "1")
    import sibyl_relay.api as api

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


def test_unknown_category_is_rejected(client):
    r = client.post("/api/jobs", json={"category": "unknown"})
    assert r.status_code == 400


def test_negative_payment_value_is_rejected(client):
    r = client.post("/api/jobs", json={"value_usdc": -1})
    assert r.status_code == 422
