"""Environment-driven configuration for the Base and Virtuals stacks.

All values are read from environment variables so that no secret is ever
committed. A deployment sets the relevant variables to move an adapter from
dry-run (real chain reads, no broadcast) to live (real broadcast).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Circle's canonical USDC deployments, keyed by chain id.
USDC_ADDRESS_BY_CHAIN: dict[int, str] = {
    8453: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base mainnet
    84532: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
}

DEFAULT_RPC_BY_CHAIN: dict[int, str] = {
    8453: "https://mainnet.base.org",
    84532: "https://sepolia.base.org",
}

EXPLORER_BY_CHAIN: dict[int, str] = {
    8453: "https://basescan.org",
    84532: "https://sepolia.basescan.org",
}


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class BaseConfig:
    """Configuration for the Base USDC payment client."""

    chain_id: int = 84532
    rpc_url: str = ""
    private_key: str = ""
    usdc_address: str = ""

    @classmethod
    def from_env(cls) -> "BaseConfig":
        chain_id = int(_env("BASE_CHAIN_ID", default="84532"))
        rpc_url = _env("BASE_RPC_URL", default=DEFAULT_RPC_BY_CHAIN.get(chain_id, ""))
        private_key = _env("BASE_PRIVATE_KEY", "BASE_WALLET_PRIVATE_KEY", default="") or ""
        usdc = _env("BASE_USDC_ADDRESS", default=USDC_ADDRESS_BY_CHAIN.get(chain_id, "")) or ""
        return cls(chain_id=chain_id, rpc_url=rpc_url or "", private_key=private_key, usdc_address=usdc)

    @property
    def explorer(self) -> str:
        return EXPLORER_BY_CHAIN.get(self.chain_id, "")

    @property
    def can_broadcast(self) -> bool:
        return bool(self.private_key)

    @property
    def enabled(self) -> bool:
        # A configured RPC + USDC address is enough for real dry-run work.
        return bool(self.rpc_url and self.usdc_address)


@dataclass(frozen=True)
class VirtualsConfig:
    """Configuration for the Virtuals ACP client."""

    agent_wallet_address: str = ""
    private_key: str = ""
    entity_id: int = 0
    chain_id: int = 84532
    rpc_url: str = ""
    evaluator_address: str = ""

    @classmethod
    def from_env(cls) -> "VirtualsConfig":
        entity_raw = _env("VIRTUALS_ENTITY_ID", "BUYER_ENTITY_ID", default="0") or "0"
        return cls(
            agent_wallet_address=_env(
                "VIRTUALS_AGENT_WALLET_ADDRESS", "BUYER_AGENT_WALLET_ADDRESS", default=""
            )
            or "",
            private_key=_env(
                "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY",
                "WHITELISTED_WALLET_PRIVATE_KEY",
                default="",
            )
            or "",
            entity_id=int(entity_raw),
            chain_id=int(_env("VIRTUALS_CHAIN_ID", default="84532")),
            rpc_url=_env("VIRTUALS_RPC_URL", "BASE_RPC_URL", default="") or "",
            evaluator_address=_env("VIRTUALS_EVALUATOR_ADDRESS", default="") or "",
        )

    @property
    def enabled(self) -> bool:
        return bool(self.agent_wallet_address and self.private_key)


@dataclass(frozen=True)
class IntegrationConfig:
    base: BaseConfig
    virtuals: VirtualsConfig


def load_config() -> IntegrationConfig:
    return IntegrationConfig(base=BaseConfig.from_env(), virtuals=VirtualsConfig.from_env())
