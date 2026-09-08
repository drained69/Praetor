from praetor.partners import BasePaymentAdapter, VirtualsACPAdapter
from praetor.core import Coordinator, Job, JobResult, WorkerProfile
from praetor.memory import InMemoryStore
from praetor.verification import BasicVerifier


def test_base_adapter_returns_live_receipt():
    class Client:
        def pay(self, recipient, amount_usdc, memo):
            assert recipient == "worker-wallet"
            assert amount_usdc == 1.5
            assert "job-1" in memo
            return "0xtx"

    receipt = BasePaymentAdapter(Client()).pay_worker("worker-wallet", 1.5, "job-1")
    assert receipt.provider == "base"
    assert receipt.reference == "0xtx"
    assert receipt.live is True


def test_virtuals_adapter_returns_acp_receipt():
    class Client:
        def submit_job(self, agent, task):
            assert agent == "risk-agent"
            return "acp-job-1"

    receipt = VirtualsACPAdapter(Client()).delegate("risk-agent", "review Base")
    assert receipt.provider == "virtuals"
    assert receipt.reference == "acp-job-1"


def test_coordinator_delegates_then_verifies_then_pays():
    calls = []

    class ACP:
        def submit_job(self, agent, task):
            calls.append("acp")
            return "acp-1"

    class Payment:
        def pay(self, recipient, amount_usdc, memo):
            calls.append("payment")
            return "0xbase-1"

    def execute(worker, job):
        calls.append("execute")
        return JobResult(worker.name, True, "complete")

    memory = InMemoryStore()
    result = Coordinator(
        memory,
        [WorkerProfile("worker", ["risk"], wallet="worker-wallet")],
        execute,
        verifier=BasicVerifier(),
        payment=BasePaymentAdapter(Payment()),
        acp=VirtualsACPAdapter(ACP()),
    ).run(Job("review", "risk", value_usdc=1.0))
    assert calls == ["acp", "execute", "payment"]
    assert result.verified is True
    assert result.acp_reference == "acp-1"
    assert result.payment_reference == "0xbase-1"
    event = memory.find_events("job_completed")[0]
    assert event["payment_reference"] == "0xbase-1"


def test_failed_verification_blocks_payment():
    class Payment:
        def pay(self, recipient, amount_usdc, memo):
            raise AssertionError("payment must not happen")

    result = Coordinator(
        InMemoryStore(),
        [WorkerProfile("worker", ["risk"])],
        lambda w, j: JobResult(w.name, True, ""),
        verifier=BasicVerifier(),
        payment=BasePaymentAdapter(Payment()),
    ).run(Job("review", "risk", value_usdc=1.0))
    assert result.success is False
    assert result.verified is False


def test_provider_failure_is_persisted_and_payment_is_not_attempted():
    class ACP:
        def submit_job(self, agent, task):
            raise RuntimeError("ACP unavailable")

    class Payment:
        def pay(self, recipient, amount_usdc, memo):
            raise AssertionError("payment must not happen after ACP failure")

    memory = InMemoryStore()
    result = Coordinator(
        memory,
        [WorkerProfile("worker", ["risk"], wallet="wallet", max_value_usdc=2)],
        lambda w, j: JobResult(w.name, True, "complete"),
        verifier=BasicVerifier(),
        payment=BasePaymentAdapter(Payment()),
        acp=VirtualsACPAdapter(ACP()),
    ).run(Job("review", "risk", value_usdc=1.0))
    assert result.success is False
    assert "ACP unavailable" in result.reason
    assert memory.load_worker("worker")["failures"] == 1


def test_base_and_virtuals_can_be_used_in_one_workflow():
    calls = []

    class Client:
        def pay(self, recipient, amount_usdc, memo):
            calls.append(("base", recipient, amount_usdc, memo))
            return "0xtx"

        def submit_job(self, agent, task):
            calls.append(("virtuals", agent, task))
            return "acp-job-1"

    client = Client()
    delegated = VirtualsACPAdapter(client).delegate("risk-agent", "review Base")
    paid = BasePaymentAdapter(client).pay_worker("worker-wallet", 1.5, "job-1")

    assert delegated.provider == "virtuals"
    assert paid.provider == "base"
    assert [call[0] for call in calls] == ["virtuals", "base"]
