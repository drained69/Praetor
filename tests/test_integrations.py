import os

import pytest

from sibyl_relay.integrations import load_config
from sibyl_relay.integrations.config import BaseConfig, VirtualsConfig
from sibyl_relay.integrations.base_payment import BasePaymentError, BaseUSDCClient
from sibyl_relay.integrations.virtuals_acp import VirtualsACPClient, VirtualsACPError
from sibyl_relay.integrations.virtuals_cli import (
    VirtualsCLIClient,
    VirtualsCLIConfig,
    VirtualsCLIError,
)
from sibyl_relay.partners import VirtualsACPAdapter, _is_live_reference


def test_base_config_defaults_to_sepolia_usdc(monkeypatch):
    for var in ("BASE_CHAIN_ID", "BASE_RPC_URL", "BASE_USDC_ADDRESS", "BASE_PRIVATE_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = BaseConfig.from_env()
    assert cfg.chain_id == 84532
    assert cfg.rpc_url == "https://sepolia.base.org"
    assert cfg.usdc_address.lower() == "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
    assert cfg.enabled is True
    assert cfg.can_broadcast is False


def test_base_config_mainnet_usdc(monkeypatch):
    monkeypatch.setenv("BASE_CHAIN_ID", "8453")
    monkeypatch.delenv("BASE_RPC_URL", raising=False)
    monkeypatch.delenv("BASE_USDC_ADDRESS", raising=False)
    cfg = BaseConfig.from_env()
    assert cfg.usdc_address == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    assert cfg.explorer == "https://basescan.org"


def test_base_client_refuses_when_unconfigured():
    with pytest.raises(BasePaymentError):
        BaseUSDCClient(BaseConfig(chain_id=84532, rpc_url="", usdc_address=""))


def test_virtuals_client_refuses_when_unconfigured():
    with pytest.raises(VirtualsACPError):
        VirtualsACPClient(VirtualsConfig())


def test_dryrun_reference_is_not_live():
    assert _is_live_reference("dryrun:base:84532:blk1:gas1:0xabc:1000000") is False
    assert _is_live_reference("0x" + "ab" * 32) is True
    assert _is_live_reference("acp:84532:42") is True


def test_load_config_returns_both_stacks(monkeypatch):
    monkeypatch.delenv("VIRTUALS_AGENT_WALLET_ADDRESS", raising=False)
    cfg = load_config()
    assert isinstance(cfg.base, BaseConfig)
    assert isinstance(cfg.virtuals, VirtualsConfig)


@pytest.mark.skipif(os.getenv("RUN_LIVE_BASE") != "1", reason="set RUN_LIVE_BASE=1 for live chain test")
def test_base_dry_run_against_live_chain():
    """Genuine Base Sepolia work: validate a real USDC transfer without broadcasting."""
    client = BaseUSDCClient(BaseConfig.from_env())
    status = client.chain_status()
    assert status["chain_id"] == 84532
    assert status["usdc_symbol"] == "USDC"
    ref = client.pay("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", 1.0, "test")
    assert ref.startswith("dryrun:base:84532:")
    assert not _is_live_reference(ref)


@pytest.mark.skipif(os.getenv("RUN_LIVE_BASE") != "1", reason="set RUN_LIVE_BASE=1 for live chain test")
def test_dry_run_succeeds_for_zero_balance_recipient():
    """Regression: a worker being paid normally holds no USDC yet.

    The dry-run must validate the real transfer via a state override rather than
    reverting with 'transfer amount exceeds balance'.
    """
    from eth_account import Account

    client = BaseUSDCClient(BaseConfig.from_env())
    fresh = Account.create().address
    assert client.balance_of(fresh) == 0.0
    ref = client.pay(fresh, 1.0, "job-fresh")
    assert ref.startswith("dryrun:base:84532:")
    assert fresh.lower() in ref.lower()


# ---------------------------------------------------------------------------
# VirtualsCLIClient — exercised against a fake ``acp`` binary the test writes
# to a temp directory and puts on PATH. Nothing calls the real network.
# ---------------------------------------------------------------------------

_FAKE_ACP = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]

def out(o):
    sys.stdout.write(json.dumps(o))
    sys.exit(0)

if args[:2] == ["agent", "whoami"]:
    out({"id": "agent-1", "name": "Sibyl Relay", "walletAddress": "0xagent"})

if args[:1] == ["browse"]:
    # emulate: acp browse <keyword> --chain-ids .. --top-k .. --json
    kw = args[1] if len(args) > 1 else ""
    if kw == "missing":
        out({"data": []})
    out({"data": [{"id": "p-1", "name": kw, "walletAddress": "0xprovider"}]})

if args[:2] == ["client", "create-custom-job"]:
    out({"jobId": "999", "chainId": 8453})

sys.stderr.write("unexpected fake-acp invocation: " + " ".join(args))
sys.exit(2)
"""


@pytest.fixture()
def fake_acp(tmp_path, monkeypatch):
    binary = tmp_path / "acp"
    binary.write_text(_FAKE_ACP)
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    return binary


def test_cli_client_refuses_when_binary_missing(monkeypatch, tmp_path):
    # An empty PATH-like shim ensures shutil.which("acp") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(VirtualsCLIError):
        VirtualsCLIClient(VirtualsCLIConfig())


def test_cli_client_status_reports_whoami(fake_acp):
    client = VirtualsCLIClient(VirtualsCLIConfig(chain_id=8453))
    status = client.status()
    assert status["configured"] is True
    assert status["backend"] == "acp-cli"
    assert status["agent_wallet"] == "0xagent"
    assert status["agent_name"] == "Sibyl Relay"
    assert status["chain_id"] == 8453


def test_cli_client_resolves_provider_by_keyword_and_submits_job(fake_acp):
    client = VirtualsCLIClient(VirtualsCLIConfig(chain_id=8453))
    matches = client.browse("risk", top_k=3)
    assert matches and matches[0]["wallet"] == "0xprovider"
    ref = client.submit_job("risk", "review a Base lending protocol")
    assert ref == "acp:8453:999"


def test_cli_client_resolves_provider_by_address_verbatim(fake_acp):
    client = VirtualsCLIClient(VirtualsCLIConfig(chain_id=8453))
    # 0x-prefixed 42-char strings bypass browse and are used directly
    provider = "0x" + "ab" * 20
    ref = client.submit_job(provider, "custom task")
    assert ref == "acp:8453:999"


def test_cli_client_raises_when_no_provider_found(fake_acp):
    client = VirtualsCLIClient(VirtualsCLIConfig(chain_id=8453))
    with pytest.raises(VirtualsCLIError):
        client.submit_job("missing", "no such provider")


def test_cli_client_plugs_into_virtuals_adapter(fake_acp):
    """The CLI client satisfies the same ACPClient protocol as the SDK client."""
    client = VirtualsCLIClient(VirtualsCLIConfig(chain_id=8453))
    receipt = VirtualsACPAdapter(client).delegate("risk", "review")
    assert receipt.provider == "virtuals"
    assert receipt.reference == "acp:8453:999"
    assert receipt.live is True
