"""Real partner-stack client implementations.

`praetor.partners` defines the narrow product boundary (the ``PaymentClient``
and ``ACPClient`` protocols). This package supplies concrete clients that speak
to the real Base chain and the real Virtuals Agent Commerce Protocol.

- :class:`BaseUSDCClient` performs genuine Base RPC work. Without a signing key
  it validates and gas-estimates a real USDC transfer against the live chain
  (``live=False``); with a key it signs and broadcasts (``live=True``).
- :class:`VirtualsACPClient` submits a real ACP job via the ``virtuals-acp`` SDK.

Neither client fabricates a transaction. When a partner is not configured the
constructor raises, so a decorative integration cannot be claimed.
"""

from __future__ import annotations

from .config import BaseConfig, IntegrationConfig, VirtualsConfig, load_config

__all__ = [
    "BaseConfig",
    "VirtualsConfig",
    "IntegrationConfig",
    "load_config",
    "BaseUSDCClient",
    "VirtualsACPClient",
    "VirtualsCLIClient",
    "VirtualsCLIConfig",
]


def __getattr__(name: str):  # lazy imports keep heavy deps optional
    if name == "BaseUSDCClient":
        from .base_payment import BaseUSDCClient

        return BaseUSDCClient
    if name == "VirtualsACPClient":
        from .virtuals_acp import VirtualsACPClient

        return VirtualsACPClient
    if name == "VirtualsCLIClient":
        from .virtuals_cli import VirtualsCLIClient

        return VirtualsCLIClient
    if name == "VirtualsCLIConfig":
        from .virtuals_cli import VirtualsCLIConfig

        return VirtualsCLIConfig
    raise AttributeError(name)
