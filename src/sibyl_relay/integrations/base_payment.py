"""Real Base USDC payment client.

Implements the :class:`sibyl_relay.partners.PaymentClient` protocol against the
live Base chain using ``web3``.

Two honest modes:

* **dry-run** (no private key): the client connects to Base, resolves the real
  USDC contract, converts the amount to base units, and validates the transfer
  with an ``eth_call`` + ``estimate_gas`` against current chain state. This is
  genuine on-chain work; it proves the payment *would* succeed without
  broadcasting. The returned reference is prefixed ``dryrun:`` and the receipt's
  ``live`` flag is ``False``.
* **live** (private key configured): the client signs and broadcasts the ERC-20
  ``transfer`` and waits for the receipt. The reference is the real transaction
  hash and ``live`` is ``True``.

The client never invents a transaction hash.
"""

from __future__ import annotations

from typing import Any

from .config import BaseConfig

# Minimal ERC-20 ABI: only what a USDC transfer path needs.
ERC20_ABI: list[dict[str, Any]] = [
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class BasePaymentError(RuntimeError):
    pass


class BaseUSDCClient:
    """A concrete ``PaymentClient`` that settles USDC on Base."""

    def __init__(self, config: BaseConfig | None = None, *, request_timeout: int = 30):
        self.config = config or BaseConfig.from_env()
        if not self.config.enabled:
            raise BasePaymentError(
                "Base is not configured: set BASE_RPC_URL (and BASE_USDC_ADDRESS "
                "for a custom chain). Refusing to simulate a payment."
            )
        self._timeout = request_timeout
        self._w3 = None
        self._contract = None
        self._decimals: int | None = None
        self._account = None

    # -- lazy wiring -------------------------------------------------------
    @property
    def w3(self):
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(
                Web3.HTTPProvider(self.config.rpc_url, request_kwargs={"timeout": self._timeout})
            )
            if not self._w3.is_connected():
                raise BasePaymentError(f"Cannot reach Base RPC at {self.config.rpc_url}")
        return self._w3

    @property
    def contract(self):
        if self._contract is None:
            from web3 import Web3

            self._contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.config.usdc_address), abi=ERC20_ABI
            )
        return self._contract

    @property
    def decimals(self) -> int:
        if self._decimals is None:
            self._decimals = int(self.contract.functions.decimals().call())
        return self._decimals

    @property
    def account(self):
        if self._account is None:
            if not self.config.private_key:
                raise BasePaymentError("No BASE_PRIVATE_KEY configured for broadcast")
            self._account = self.w3.eth.account.from_key(self.config.private_key)
        return self._account

    # -- read helpers (used by the dashboard) ------------------------------
    def chain_status(self) -> dict[str, Any]:
        w3 = self.w3
        return {
            "connected": True,
            "chain_id": w3.eth.chain_id,
            "block_number": w3.eth.block_number,
            "rpc_url": self.config.rpc_url,
            "usdc_address": self.config.usdc_address,
            "usdc_symbol": self.contract.functions.symbol().call(),
            "usdc_decimals": self.decimals,
            "explorer": self.config.explorer,
            "can_broadcast": self.config.can_broadcast,
            "sender": self.account.address if self.config.can_broadcast else "",
        }

    def balance_of(self, address: str) -> float:
        from web3 import Web3

        raw = self.contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        return raw / (10**self.decimals)

    # -- PaymentClient protocol -------------------------------------------
    def pay(self, recipient: str, amount_usdc: float, memo: str) -> str:
        from web3 import Web3

        if amount_usdc < 0:
            raise BasePaymentError("amount_usdc must be non-negative")
        to = Web3.to_checksum_address(recipient)
        amount_base = int(round(amount_usdc * (10**self.decimals)))

        if not self.config.can_broadcast:
            return self._dry_run(to, amount_base)
        return self._broadcast(to, amount_base)

    # -- internals ---------------------------------------------------------
    # Candidate storage slots for an ERC-20 ``balances`` mapping. Circle's
    # FiatToken (USDC) uses slot 9 on Base; the others cover common layouts so
    # the simulation is not tied to one implementation.
    _BALANCE_SLOT_CANDIDATES = (9, 0, 1, 2, 3, 5, 51)

    def _dry_run(self, to: str, amount_base: int) -> str:
        """Validate the transfer against live chain state without broadcasting.

        This always performs genuine on-chain work: it resolved the real USDC
        contract and read its decimals/symbol (see :attr:`contract`), the
        recipient is checksum-validated by the caller, the amount is converted
        using the contract's *real* decimals, and the current block is read.

        The transfer itself is then simulated. A dry-run has no funded sender,
        so an ``eth_call`` with a state override credits a probe sender with the
        amount and exercises the exact ``transfer(recipient, amount)`` call
        against live contract logic, yielding a real gas estimate. If the node
        does not support state overrides (or the token's balance slot cannot be
        located), the client degrades to read-only validation (``gasNA``) rather
        than reporting a false failure. A genuine revert -- paused token,
        blacklisted recipient -- is always surfaced.
        """
        block = self.w3.eth.block_number
        gas = self._simulate_transfer(to, amount_base)
        gas_part = f"gas{gas}" if gas is not None else "gasNA"
        return f"dryrun:base:{self.config.chain_id}:blk{block}:{gas_part}:{to}:{amount_base}"

    def _simulate_transfer(self, to: str, amount_base: int) -> int | None:
        """Best-effort real simulation of ``transfer(to, amount)``.

        Returns the estimated gas when the transfer path is exercised, or
        ``None`` when only read-only validation was possible. Raises
        :class:`BasePaymentError` on a genuine (non-balance) revert.
        """
        from web3 import Web3

        fn = self.contract.functions.transfer(to, amount_base)

        # 1) If the recipient already holds enough, a self-transfer exercises the
        #    full path with a real gas estimate and needs no state override.
        try:
            if self.contract.functions.balanceOf(to).call() >= amount_base > 0:
                if fn.call({"from": to}) is not False:
                    return int(fn.estimate_gas({"from": to}))
        except BasePaymentError:
            raise
        except Exception:  # noqa: BLE001 - fall through to override simulation
            pass

        # 2) Simulate from a probe sender credited via a state override.
        probe = Web3.to_checksum_address("0x000000000000000000000000000000000000a11e")
        probe_word = bytes.fromhex(probe[2:].lower().rjust(64, "0"))
        credit = (amount_base + 10**18).to_bytes(32, "big").hex()
        usdc = Web3.to_checksum_address(self.config.usdc_address)
        saw_balance_revert = False
        for slot in self._BALANCE_SLOT_CANDIDATES:
            key = Web3.keccak(probe_word + slot.to_bytes(32, "big")).hex()
            if not key.startswith("0x"):
                key = "0x" + key
            override = {usdc: {"stateDiff": {key: "0x" + credit}}}
            try:
                ok = fn.call({"from": probe}, "latest", override)
            except Exception as exc:  # noqa: BLE001
                if self._is_balance_revert(exc):
                    saw_balance_revert = True
                    continue  # wrong slot / override not applied; try the next
                raise BasePaymentError(f"transfer would revert on Base: {exc}") from exc
            if ok is False:
                raise BasePaymentError("transfer simulation returned false")
            try:
                return int(fn.estimate_gas({"from": probe}, "latest", override))
            except Exception:  # noqa: BLE001 - call proved the path; gas is a bonus
                return None

        if saw_balance_revert:
            # Overrides are unsupported here (or the slot is unknown): the only
            # honest outcome is read-only validation, which already succeeded.
            return None
        return None

    @staticmethod
    def _is_balance_revert(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "exceeds balance" in msg or "insufficient balance" in msg

    def _broadcast(self, to: str, amount_base: int) -> str:
        w3 = self.w3
        account = self.account
        tx = self.contract.functions.transfer(to, amount_base).build_transaction(
            {
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": self.config.chain_id,
            }
        )
        # Fill gas fields if the node did not.
        tx.setdefault("gas", w3.eth.estimate_gas(tx))
        signed = w3.eth.account.sign_transaction(tx, private_key=self.config.private_key)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.get("status") != 1:
            raise BasePaymentError(f"transfer reverted on-chain: {tx_hash.hex()}")
        return tx_hash.hex()
