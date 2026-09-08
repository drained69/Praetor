"""Optional partner integrations.

These adapters deliberately do not invent Base or Virtuals APIs. They provide
the product boundary and require an application-specific client implementation.
The local demo can therefore be verified without claiming a fake transaction.

An application can configure either adapter independently, or use both in the
same workflow: Virtuals can coordinate or delegate the agent job, while Base
can settle the worker payment. Neither partner is required for Praetor's
memory-backed routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class PaymentClient(Protocol):
    def pay(self, recipient: str, amount_usdc: float, memo: str) -> str: ...


class ACPClient(Protocol):
    def submit_job(self, agent: str, task: str) -> str: ...


@dataclass
class PartnerReceipt:
    provider: str
    reference: str
    live: bool


def _is_live_reference(reference: str) -> bool:
    """A ``dryrun:`` reference is real chain validation but not a broadcast."""
    return not reference.startswith("dryrun:")


class BasePaymentAdapter:
    def __init__(self, client: PaymentClient):
        self.client = client

    def pay_worker(self, recipient: str, amount_usdc: float, job_id: str) -> PartnerReceipt:
        reference = self.client.pay(recipient, amount_usdc, f"Praetor job {job_id}")
        return PartnerReceipt("base", reference, _is_live_reference(reference))


class VirtualsACPAdapter:
    def __init__(self, client: ACPClient):
        self.client = client

    def delegate(self, agent: str, task: str) -> PartnerReceipt:
        reference = self.client.submit_job(agent, task)
        return PartnerReceipt("virtuals", reference, _is_live_reference(reference))


class UnconfiguredIntegration:
    """Makes accidental decorative integrations impossible."""

    def __init__(self, provider: str):
        self.provider = provider

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"{self.provider} integration is not configured; refusing to simulate {name}()")
