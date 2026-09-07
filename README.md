# Sibyl Relay

## Memory-backed coordination for autonomous agents

Sibyl Relay is an agent coordinator that learns from execution history. It
routes work to specialist agents, records what happened, and changes future
delegation decisions when an agent has previously failed.

> **Core idea:** Agent economies need more than identity and payment. They need
> persistent memory of what each agent actually did.

## Why Relay exists

Most agent orchestration systems select workers from static descriptions:

```text
"This agent says it can perform risk analysis, so assign it the task."
```

Relay adds operational memory:

```text
"This agent previously missed liquidity-lock evidence on a similar review.
Assign discovery to it only, and route final verification to another agent."
```

That decision survives a process restart because it is stored in Sibyl Memory,
not in the coordinator's transient state.

## Current status

### Complete

- Memory-backed worker profiles and capability matching
- Persistent success, failure, and failure-note tracking
- Fresh-session routing based on previously persisted outcomes
- Durable job assignment and completion events
- Real local SQLite integration through `sibyl-memory-client` 0.8.x
- Deterministic in-memory test implementation
- **Real Base USDC client** (`web3`) — connects to the live Base chain, resolves
  Circle's USDC contract, and validates/gas-estimates a real transfer. Dry-run
  by default (no key needed); broadcasts when a signing key is supplied.
- **Real Virtuals ACP client** (`virtuals-acp` SDK) — resolves a provider agent
  and calls `initiate_job` on-chain, returning a durable ACP job reference.
- **Live product: dashboard + REST API** (`FastAPI`) showing routing evidence,
  worker reputation reconstructed from memory, live Base chain status, and
  partner references, with a one-click deletion test.
- Verification-before-settlement safety gate
- Durable ACP and payment references in job events
- Provider failure handling with persisted audit outcomes
- Executable `--deletion-test` routing comparison
- Automated unit tests (including end-to-end API tests) and a live Base test
- MIT project license declaration

### What still needs the deployer's own credentials

The clients are real; moving them from *validated* to *broadcast* requires
secrets that must never live in the repo:

- A funded Base key (`BASE_PRIVATE_KEY`) to broadcast USDC settlement. Without
  it, Base runs in **dry-run**: it connects to the live chain, resolves the real
  USDC contract, reads its decimals, and simulates the exact
  `transfer(recipient, amount)` against live state using an `eth_call` state
  override (so it validates correctly even when the recipient — a worker being
  paid — holds no USDC yet). If the node lacks state-override support the client
  degrades to read-only validation rather than reporting a false failure, and a
  genuine revert (paused token, blacklisted recipient) is always surfaced. This
  is real work, and the code never pretends a broadcast happened — the reference
  is prefixed `dryrun:` and the receipt's `live` flag is `False`.
- A Virtuals ACP buyer-agent wallet + whitelisted key (and Python 3.10–3.12,
  which the `virtuals-acp` SDK requires) to submit a live ACP job.
- Production hardening: authentication, rate limiting, and deployment config.

The repository does **not** pretend that a payment or ACP job occurred when no
live client is configured. This is important for the hackathon's requirement
that partner integrations perform real work rather than being decorative.

## Live product (dashboard + API)

Run the coordinator as a live web product:

```bash
.venv/bin/pip install -e '.[server]'
.venv/bin/sibyl-relay-server           # http://127.0.0.1:8000
```

The dashboard lets you submit a job and watch the routing decision, inject a
worker failure to seed memory, then run again clean and see the coordinator
avoid the flagged worker. With `BASE_RPC_URL` set (Base Sepolia by default) it
shows the live chain block height and produces a real USDC settlement reference
per job. Point `SIBYL_RELAY_DB` at a Sibyl database to make reputation durable
across restarts.

REST endpoints: `GET /api/health`, `GET /api/state`, `POST /api/jobs`,
`POST /api/deletion-test`.

`GET /api/health` also returns a `builder_score` block that mirrors the
hackathon rubric: the mandatory Sibyl Memory foundation, the number of
**verified** partner stacks, and the resulting multiplier (`x1.00` / `x1.15` /
`x1.25`). A stack is counted only when it is observed doing real work — Base
when the client actually connected and read the live USDC contract, Virtuals
when its ACP client is active — so the score reflects genuine integration, not
constructed adapters.

Configuration is environment-driven and a `.env` file is loaded automatically
(found by walking up from the working directory), so you never have to `export`
anything. Copy `.env.example` to `.env` and fill in the stacks you want to
activate:

```bash
cp .env.example .env      # then paste your keys into .env
```

`.env` is gitignored. Real environment variables that are already set take
precedence over the file, and `SIBYL_RELAY_NO_PARTNERS=1` disables partner
wiring entirely (used by the tests). Adding `BASE_PRIVATE_KEY` flips Base from
dry-run to live broadcast; adding the `VIRTUALS_*` keys activates ACP.

## Demonstration

The included demo shows the central product behavior:

1. Session one runs a risk-review task with `risk-reviewer-v1`.
2. The worker fails and Relay persists the failure in Sibyl Memory.
3. The coordinator process is recreated.
4. Session two receives a similar task.
5. Relay recalls the prior failure and routes the task to `risk-reviewer-v2`.

Run the deterministic demo without credentials:

```bash
PYTHONPATH=src python3 -m sibyl_relay
```

Expected output:

```text
Fresh session routed to: risk-reviewer-v2
Outcome: success
```

Run the explicit deletion-test comparison:

```bash
.venv/bin/python -m sibyl_relay --deletion-test
```

This compares a store containing a remembered failure with a fresh empty
store. It is the shortest local demonstration that memory changes routing.

## Real Sibyl Memory

Relay uses the public Sibyl Memory API documented at
<https://docs.sibyllabs.org/>:

- `MemoryClient.local(...)`
- `set_entity(...)`
- `get_entity(...)`
- `list_entities(...)` — used to enumerate all workers in the `relay_worker`
  category (the documented enumeration primitive; `search_entities` is FTS-paged
  and would truncate)
- `search_entities(...)`
- `write_event(...)`
- `read_events(...)`

Install the client:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pip install sibyl-memory-client
```

If account activation is required by the local Sibyl installation, run the
documented commands separately:

```bash
sibyl init
sibyl health
```

Run Relay against the same local memory database used by Sibyl:

```bash
export SIBYL_RELAY_DB="$HOME/.sibyl-memory/memory.db"
.venv/bin/python -m sibyl_relay --db "$SIBYL_RELAY_DB"
```

For a clean smoke test against a temporary real Sibyl database:

```bash
.venv/bin/python - <<'PY'
from tempfile import TemporaryDirectory

from sibyl_relay.core import Coordinator, Job, JobResult, WorkerProfile
from sibyl_relay.memory import SibylMemoryStore

with TemporaryDirectory() as directory:
    memory = SibylMemoryStore(directory + "/memory.db")

    def execute(worker, job):
        failed = worker.name == "bad"
        return JobResult(
            worker.name,
            not failed,
            "ok" if not failed else "incomplete",
            "missed critical evidence" if failed else "",
        )

    Coordinator(memory, [WorkerProfile("bad", ["risk"])], execute).run(
        Job("first review", "risk")
    )
    result = Coordinator(
        memory,
        [
            WorkerProfile("bad", ["risk"]),
            WorkerProfile("good", ["risk"], successes=4),
        ],
        execute,
    ).run(Job("second review", "risk"))
    print(result.worker, result.success)
PY
```

Expected result:

```text
good True
```

## Architecture

```text
              task
               |
               v
       +----------------+
       |  Coordinator   |
       | choose + run   |
       +--------+-------+
                |
                | load profile and history
                v
       +----------------+
       | Sibyl Memory   |
       | WARM entities  |
       | COLD events    |
       +--------+-------+
                |
                v
       +----------------+
       | Specialist     |
       | worker agent   |
       +----------------+
                |
                | result, failure, evidence
                +-----------------------> Sibyl Memory
```

### Memory model

| Relay data | Sibyl tier | Purpose |
|---|---|---|
| Worker profile | WARM entity | Capabilities, successes, failures, review status |
| Job assignment | COLD event | Records who was selected and for which task |
| Job completion | COLD event | Records success, failure, and reason |
| Future routing | FTS/entity lookup | Reconstructs durable worker state after restart |

Worker profiles are stored under the `relay_worker` category. An omitted
`max_value_usdc` means no local limit and is serialized as JSON `null`; the
coordinator does not use an in-process reputation cache as its source of truth.

### Routing behavior

Relay currently ranks eligible workers by:

1. Workers not marked `requires_review`
2. Historical reliability
3. Lower failure count

A failed result increments the worker's failure count, marks the worker for
review, and stores the failure reason. The next coordinator instance reads that
profile from Sibyl before selecting a worker.

If configured, Relay delegates to ACP before execution, verifies the returned
report, and only then settles payment. A failed or unverifiable report never
reaches the payment adapter.

## Partner integration boundaries

The core defines two narrow protocols, and `sibyl_relay.integrations` ships real
clients that satisfy them:

```python
class PaymentClient:
    def pay(self, recipient: str, amount_usdc: float, memo: str) -> str: ...


class ACPClient:
    def submit_job(self, agent: str, task: str) -> str: ...
```

Real Base settlement (dry-run without a key, live broadcast with one):

```python
from sibyl_relay.integrations import BaseUSDCClient
from sibyl_relay.partners import BasePaymentAdapter

payment = BasePaymentAdapter(BaseUSDCClient())        # reads BASE_* env
receipt = payment.pay_worker("0xWorkerWallet", 1.0, "job-id")
# receipt.reference -> "dryrun:base:84532:..."   (or a real tx hash when live)
# receipt.live      -> False for dry-run, True after a broadcast
```

Real Virtuals ACP delegation:

```python
from sibyl_relay.integrations import VirtualsACPClient
from sibyl_relay.partners import VirtualsACPAdapter

acp = VirtualsACPAdapter(VirtualsACPClient())         # reads VIRTUALS_* env
receipt = acp.delegate("risk-reviewer", "perform risk review")
# receipt.reference -> "acp:84532:<onchain_job_id>"
```

Both clients **refuse to construct** unless their stack is configured, so a
decorative integration is impossible. No secret is embedded in the code; the
clients read Base and Virtuals configuration from the environment and use the
official provider APIs (`web3` for Base, the `virtuals-acp` SDK for Virtuals).
When configured, Relay persists their returned references in the COLD completion
event and exposes them on `JobResult`.

### One stack or both

The partner stacks are optional and composable:

- **Sibyl only** provides persistent memory-backed routing.
- **Sibyl + Base** adds Base-based worker payments and agentic transactions.
- **Sibyl + Virtuals** adds Virtuals agent coordination and delegation.
- **Sibyl + Base + Virtuals** lets Virtuals coordinate the job and Base settle
  the resulting worker payment.

Base and Virtuals are therefore not an either/or choice. An application may
configure either adapter independently or call both in the same workflow. Sibyl
Memory remains the required foundation for the relay's persistent routing.

## Deletion test

Sibyl Memory is load-bearing by design.

To verify it:

1. Run the first session and allow a worker to fail.
2. Stop the coordinator.
3. Start a fresh coordinator with the same database.
4. Submit a similar task.
5. Observe that the failed worker is avoided.
6. Repeat with an empty store and observe that the previously failed worker is selected again.

Without Sibyl, Relay loses the worker's failure history and cannot perform
memory-backed risk-aware routing. The product's defining behavior therefore
breaks when the memory layer is removed.

## Repository layout

```text
src/sibyl_relay/
├── __init__.py            Public package exports
├── __main__.py            `python -m sibyl_relay` entry point
├── cli.py                 Console entry point
├── core.py                Jobs, worker profiles, and coordinator
├── demo.py                Two-session demonstration
├── memory.py              Sibyl and in-memory store implementations
├── partners.py            PaymentClient/ACPClient protocols + adapters
├── verification.py        Verification-before-settlement safety gate
├── api.py                 FastAPI dashboard + REST API (the live product)
├── web/index.html         Dashboard UI
└── integrations/
    ├── config.py          Env-driven Base + Virtuals configuration
    ├── base_payment.py    Real Base USDC client (web3)
    └── virtuals_acp.py    Real Virtuals ACP client (virtuals-acp SDK)

tests/
├── test_partners.py       Partner adapter tests
├── test_relay.py          Routing and persistence behavior tests
├── test_integrations.py   Base/Virtuals config + client guards + live Base test
└── test_api.py            End-to-end dashboard/API tests
```

## Testing

Run the automated suite:

```bash
.venv/bin/pytest -q
```

Current test coverage includes:

- Fresh-session avoidance of a worker with a persisted failure
- Memory being required for worker discovery and routing
- Unsupported task categories being rejected
- Base adapter receipt handling and dry-run vs live reference detection
- Virtuals ACP adapter receipt handling
- Provider failures blocking settlement and updating worker reputation
- Base/Virtuals env configuration and unconfigured-client refusal
- End-to-end dashboard/API flow (health, state, job routing, deletion test)

The local verification result is:

```text
25 passed, 2 skipped
```

The two skipped tests are live Base Sepolia dry-runs (they exercise the real
chain without broadcasting); run them explicitly with
`RUN_LIVE_BASE=1 .venv/bin/pytest -k "live_chain or zero_balance"`. The Sibyl
round-trip tests (`tests/test_memory_sibyl.py`) run against a real temporary
SQLite store created by `sibyl-memory-client` and prove that `list_workers`
enumerates every worker via the documented `list_entities` API (not the
FTS-paged `search_entities`), so routing memory does not silently truncate.

## Product roadmap

### Remaining integration work

- ~~Add a web view showing routing evidence and live references~~ — **done**
  (FastAPI dashboard)
- ~~Real Base settlement path~~ — **done** as a dry-run client; supply
  `BASE_PRIVATE_KEY` (funded testnet key) to broadcast
- ~~Real Virtuals ACP client~~ — **done**; supply a Virtuals buyer-agent wallet
  and key (Python 3.10–3.12) to submit a live job
- Register and connect one real Virtuals ACP provider agent end to end
- Broadcast one real Base testnet USDC settlement with a funded key
- Record a clean, unedited fresh-session demo video (2–5 min)

### Production foundation

- Worker registration and health checks
- Per-worker wallet and ACP identity configuration
- Human approval thresholds for high-value work
- Retry and escalation policies
- Signed job receipts and audit export
- Authentication and tenant authorization

### Phase 3: agent reputation network

- Cross-organization reputation with explicit consent
- Evidence-backed capability claims
- Reputation decay and dispute workflows
- Pricing and escrow based on historical performance

## Hackathon positioning

Sibyl Relay is designed for the Sibyl Labs Hackathon's memory gate:

> **Sibyl Relay remembers which agents earned trust, then uses that memory to
> decide who gets the next job.**

The intended final demo will combine:

- Sibyl Memory for durable worker reputation and job history
- Virtuals for real agent-to-agent delegation
- Base for real settlement or x402 payment

Only integrations that are exercised end to end should be claimed in the final
submission.

## License

MIT. See `pyproject.toml`.
