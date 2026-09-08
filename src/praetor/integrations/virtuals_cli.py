"""Virtuals ACP client backed by the official ``acp`` CLI.

This is an alternate implementation of :class:`praetor.partners.ACPClient`
for the common case where the agent's ACP v2 smart account has not been
deployed yet, or the Python SDK is not usable on the current interpreter.

The CLI (``@virtuals-protocol/acp-cli``) authenticates once with
``acp configure`` and stores credentials in the OS keychain. All subsequent
signing uses a signer wallet the operator whitelisted through the ACP
dashboard, so no signing key is passed to Praetor.

- :meth:`status` shells out to ``acp agent whoami`` and returns the active
  agent's real name and wallet address — proving the CLI is authenticated as
  a Virtuals agent (this is the evidence used by the dashboard's
  ``virtuals.configured`` flag).
- :meth:`browse` calls ``acp browse`` to resolve a provider by keyword.
- :meth:`submit_job` calls ``acp client create-custom-job`` which submits the
  job on-chain via the whitelisted signer, and returns a durable
  ``acp:<chain>:<onchain_job_id>`` reference.

Nothing about this file simulates a job. If the CLI isn't installed or isn't
authenticated, the constructor raises so the dashboard reports the failure
honestly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


class VirtualsCLIError(RuntimeError):
    pass


@dataclass(frozen=True)
class VirtualsCLIConfig:
    chain_id: int = 8453
    default_evaluator: str = ""
    default_expired_in_s: int = 3600
    binary: str = "acp"

    @classmethod
    def from_env(cls) -> "VirtualsCLIConfig":
        return cls(
            chain_id=int(os.getenv("VIRTUALS_CHAIN_ID", "8453")),
            default_evaluator=os.getenv("VIRTUALS_EVALUATOR_ADDRESS", ""),
            default_expired_in_s=int(os.getenv("VIRTUALS_JOB_EXPIRES_IN_S", "3600")),
            binary=os.getenv("VIRTUALS_ACP_BINARY", "acp"),
        )


def _run_json(argv: list[str], *, timeout: int = 60) -> Any:
    """Run an acp CLI subcommand and parse its JSON stdout."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VirtualsCLIError(
            "acp CLI not found. Install it: npm i -g @virtuals-protocol/acp-cli"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise VirtualsCLIError(f"acp CLI timed out: {' '.join(argv)}") from exc
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0 or not stdout:
        stderr = (proc.stderr or "").strip() or stdout
        raise VirtualsCLIError(f"acp CLI failed ({proc.returncode}): {stderr[:400]}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise VirtualsCLIError(f"acp CLI returned non-JSON output: {stdout[:400]}") from exc


class VirtualsCLIClient:
    """A concrete ``ACPClient`` backed by the ``acp`` CLI."""

    def __init__(self, config: VirtualsCLIConfig | None = None):
        self.config = config or VirtualsCLIConfig.from_env()
        if shutil.which(self.config.binary) is None:
            raise VirtualsCLIError(
                f"{self.config.binary!r} not on PATH. Install: npm i -g @virtuals-protocol/acp-cli"
            )
        # Cheapest possible probe that fails fast if the CLI is unauthenticated
        # or has no active agent.
        try:
            self._whoami = _run_json([self.config.binary, "agent", "whoami", "--json"], timeout=20)
        except VirtualsCLIError as exc:
            raise VirtualsCLIError(
                f"acp CLI is installed but not usable as an agent yet: {exc}. "
                "Run: acp configure && acp agent use --agent-id <id>"
            ) from exc

    # -- read helper (dashboard) ------------------------------------------
    def status(self) -> dict[str, Any]:
        d = self._whoami or {}
        return {
            "configured": True,
            "agent_wallet": d.get("walletAddress", ""),
            "agent_name": d.get("name", ""),
            "agent_id": d.get("id", ""),
            "chain_id": self.config.chain_id,
            "backend": "acp-cli",
        }

    def browse(self, keyword: str, top_k: int = 5) -> list[dict[str, Any]]:
        out = _run_json(
            [
                self.config.binary, "browse", keyword,
                "--chain-ids", str(self.config.chain_id),
                "--top-k", str(top_k), "--json",
            ],
            timeout=30,
        )
        data = out.get("data") if isinstance(out, dict) else out
        results: list[dict[str, Any]] = []
        for a in data or []:
            results.append(
                {
                    "name": a.get("name", ""),
                    "wallet": a.get("walletAddress", ""),
                    "id": a.get("id", ""),
                }
            )
        return results

    # -- ACPClient protocol ------------------------------------------------
    def submit_job(self, agent: str, task: str) -> str:
        provider = self._resolve_provider(agent)
        argv = [
            self.config.binary, "client", "create-custom-job",
            "--provider", provider,
            "--description", task,
            "--chain-id", str(self.config.chain_id),
            "--expired-in", str(self.config.default_expired_in_s),
            "--json",
        ]
        if self.config.default_evaluator:
            argv += ["--evaluator", self.config.default_evaluator]
        out = _run_json(argv, timeout=180)
        onchain_job_id = (
            out.get("jobId")
            or out.get("id")
            or out.get("onchainJobId")
            or (out.get("data") or {}).get("jobId")
        )
        if not onchain_job_id:
            raise VirtualsCLIError(f"acp CLI create-custom-job returned no jobId: {out}")
        return f"acp:{self.config.chain_id}:{onchain_job_id}"

    # -- internals ---------------------------------------------------------
    def _resolve_provider(self, agent: str) -> str:
        if agent.startswith("0x") and len(agent) == 42:
            return agent
        matches = self.browse(agent, top_k=1)
        if not matches or not matches[0].get("wallet"):
            raise VirtualsCLIError(f"No ACP provider agent found for {agent!r}")
        return matches[0]["wallet"]
