"""Real Virtuals Agent Commerce Protocol (ACP) client.

Implements the :class:`praetor.partners.ACPClient` protocol against the real
Virtuals ACP network using the official ``virtuals-acp`` SDK.

``submit_job(agent, task)`` resolves a provider agent (by wallet address or by
browsing the ACP registry for a keyword), then calls ``initiate_job`` on-chain
and returns a durable ``acp:<chain>:<onchain_job_id>`` reference that Relay
persists in its Sibyl Memory completion event.

The ``virtuals-acp`` SDK targets Python 3.10-3.12. Import is deferred so the rest
of Praetor runs on any supported interpreter; the client only requires the
SDK when it is actually used.
"""

from __future__ import annotations

import os
from typing import Any

from .config import USDC_ADDRESS_BY_CHAIN, VirtualsConfig


class VirtualsACPError(RuntimeError):
    pass


class VirtualsACPClient:
    """A concrete ``ACPClient`` backed by the Virtuals ACP network."""

    def __init__(self, config: VirtualsConfig | None = None, *, default_budget_usdc: float = 1.0):
        self.config = config or VirtualsConfig.from_env()
        if not self.config.enabled:
            raise VirtualsACPError(
                "Virtuals is not configured: set VIRTUALS_AGENT_WALLET_ADDRESS and "
                "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY. Refusing to simulate a job."
            )
        self.default_budget_usdc = default_budget_usdc
        self._acp = None
        self._config_obj = None

    # -- lazy SDK wiring ---------------------------------------------------
    def _build(self):
        if self._acp is not None:
            return
        private_key = self.config.private_key.removeprefix("0x")
        if len(private_key) != 64:
            raise VirtualsACPError(
                "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY must be a 32-byte EVM "
                "private key in hex format (64 hex characters, optionally prefixed 0x)."
            )
        try:
            int(private_key, 16)
        except ValueError as exc:
            raise VirtualsACPError(
                "VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY contains non-hex characters; "
                "provide the whitelisted EVM signer key, not a PEM key."
            ) from exc
        sdk_config_names = {
            8453: "BASE_MAINNET_CONFIG_V2",
            84532: "BASE_SEPOLIA_CONFIG_V2",
        }
        config_name = sdk_config_names.get(self.config.chain_id)
        if config_name is None:
            raise VirtualsACPError(
                f"Virtuals ACP does not support chain {self.config.chain_id}; "
                "use Base mainnet (8453) or Base Sepolia (84532)."
            )
        try:
            from virtuals_acp.client import VirtualsACP
            from virtuals_acp.configs import configs as sdk_configs
            from virtuals_acp.contract_clients.contract_client_v2 import ACPContractClientV2
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise VirtualsACPError(
                "virtuals-acp is not installed. Install it on Python 3.10-3.12: "
                "pip install virtuals-acp"
            ) from exc

        # The SDK also reads the signing key from the environment.
        os.environ.setdefault("WHITELISTED_WALLET_PRIVATE_KEY", self.config.private_key)

        self._config_obj = getattr(sdk_configs, config_name)
        try:
            contract_client = ACPContractClientV2(
                agent_wallet_address=self.config.agent_wallet_address,
                wallet_private_key=self.config.private_key,
                entity_id=self.config.entity_id,
                config=self._config_obj,
            )
        except Exception as exc:  # noqa: BLE001 - surface the SDK's reason
            raise VirtualsACPError(
                f"Virtuals agent account is not usable: {exc}. Register the agent on the "
                "Virtuals platform to deploy its on-chain smart account, then set "
                "VIRTUALS_AGENT_WALLET_ADDRESS (deployed account) and VIRTUALS_ENTITY_ID."
            ) from exc
        self._acp = VirtualsACP(
            acp_contract_clients=contract_client,
            custom_rpc_url=self.config.rpc_url or None,
            skip_socket_connection=True,
        )

    # -- read helper (dashboard) ------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "agent_wallet": self.config.agent_wallet_address,
            "chain_id": self.config.chain_id,
        }

    def verify(self) -> dict[str, Any]:
        """Prove the stack does real work by constructing the on-chain client.

        Building the ACP contract client runs the SDK's
        ``validate_session_key_on_chain`` check: it reads the on-chain
        single-signer validation module and confirms the whitelisted signer is
        registered for ``VIRTUALS_ENTITY_ID`` under the agent's smart account.
        This raises if the signer has not been added on the Virtuals platform,
        so a "verified" status can never be claimed decoratively.
        """
        self._build()
        return {**self.status(), "verified_onchain": True}

    def browse(self, keyword: str, top_k: int = 5) -> list[dict[str, Any]]:
        self._build()
        agents = self._acp.browse_agents(keyword=keyword, top_k=top_k) or []
        out: list[dict[str, Any]] = []
        for a in agents:
            out.append(
                {
                    "name": getattr(a, "name", ""),
                    "wallet": getattr(a, "wallet_address", "") or getattr(a, "walletAddress", ""),
                }
            )
        return out

    # -- ACPClient protocol ------------------------------------------------
    def submit_job(self, agent: str, task: str) -> str:
        self._build()
        provider = self._resolve_provider(agent)
        fare = self._fare(self.default_budget_usdc)
        evaluator = self.config.evaluator_address or None
        onchain_job_id = self._acp.initiate_job(
            provider_address=provider,
            service_requirement=task,
            fare_amount=fare,
            evaluator_address=evaluator,
        )
        return f"acp:{self.config.chain_id}:{onchain_job_id}"

    # -- internals ---------------------------------------------------------
    def _resolve_provider(self, agent: str) -> str:
        if agent.startswith("0x") and len(agent) == 42:
            return agent
        agents = self._acp.browse_agents(keyword=agent, top_k=1) or []
        if not agents:
            raise VirtualsACPError(f"No ACP provider agent found for {agent!r}")
        wallet = getattr(agents[0], "wallet_address", "") or getattr(agents[0], "walletAddress", "")
        if not wallet:
            raise VirtualsACPError(f"Resolved agent {agent!r} has no wallet address")
        return wallet

    def _fare(self, amount_usdc: float):
        from virtuals_acp.fare import FareAmount

        usdc = USDC_ADDRESS_BY_CHAIN.get(self.config.chain_id)
        if not usdc:
            raise VirtualsACPError(f"No USDC address known for chain {self.config.chain_id}")
        return FareAmount.from_contract_address(amount_usdc, usdc, self._config_obj)
