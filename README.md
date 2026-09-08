# Praetor

**Memory-backed coordination protocol for autonomous agents.**

[![Version](https://img.shields.io/badge/version-0.1.0-informational.svg)](pyproject.toml)
[![Status](https://img.shields.io/badge/status-experimental-yellow.svg)](#status)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Identity tells an agent economy *who* can work. Payment tells it *how* to settle. Praetor specifies the missing layer: **durable evidence of what each worker actually did**, and a deterministic rule for using that evidence on the next assignment.

This repository is the **reference implementation**. Memory is the source of truth; process-local caches are not.

| | |
|---|---|
| **Live console** | **[praetorv1.up.railway.app](https://praetorv1.up.railway.app)** |
| **Specification** | [§ Protocol](#protocol) |
| **Reference server** | [§ HTTP API](#http-api) |
| **Memory substrate** | [Sibyl Memory](https://docs.sibyllabs.org/) — **all five tiers, load-bearing** |
| **Settlement** | Base USDC — **live on-chain** ([proof](#live-proof)) |
| **Delegation** | Virtuals ACP — **live on-chain** ([proof](#live-proof)) |
| **Source** | [github.com/drained69/Praetor](https://github.com/drained69/Praetor) |

---

## Live proof

Praetor is deployed and doing real work. Every claim below is independently verifiable — no screenshots, no trust required.

**Deep Sibyl integration — five tiers, each load-bearing:**

> **WARM** worker entities · **COLD** job events · **HOT** live counters · **REFERENCE** immutable receipts · **SEARCH** task-aware routing

Most coordinators use memory as a key-value cache. Praetor binds every tier of Sibyl's [five-tier schema](#memory-model) to a distinct, specified behavior. Remove any tier and a named guarantee breaks — see [Conformance](#conformance).

**On-chain settlement (Base Sepolia) and delegation (Virtuals ACP), from real job runs:**

| Artifact | Reference | Verify |
|---|---|---|
| Settlement by the **deployed** instance | `0x78a0…5d20` | [BaseScan ↗](https://sepolia.basescan.org/tx/0x78a004ca5231253f7a72c29f6ba8612c88a2987ff3899d3a308c871e2ed55d20) |
| Settlement by a reference run | `0xf83d…84f0` | [BaseScan ↗](https://sepolia.basescan.org/tx/0xf83df8a619aeb29e6d487ef78ea6392c25754fb13d6bf1156bece2373e7284f0) |
| Virtuals ACP job created by the coordinator | `acp:8453:77419` | [Virtuals ↗](https://app.virtuals.io/acp/jobs/77419) |
| Live health & memory tiers | `GET /api/health` | [health ↗](https://praetorv1.up.railway.app/api/health) |

Each USDC settlement is gated on verification: a job that fails or cannot be verified never reaches the payment adapter ([Invariant 2](#invariants)).

---

## Status

| Field | Value |
|---|---|
| Version | `0.1.0` |
| Stability | **Experimental.** Interfaces may change before `1.0.0`. |
| Language | Python 3.10+ |
| License | MIT |

Normative sections: [Protocol](#protocol), [Invariants](#invariants), [Security considerations](#security-considerations).  
Informative sections: install, operator console, examples, roadmap.

---

## Table of contents

1. [Live proof](#live-proof)
2. [Motivation](#motivation)
3. [Protocol](#protocol)
   - [Coordination loop](#coordination-loop)
   - [Objects](#objects)
   - [Routing](#routing)
   - [Memory model](#memory-model)
   - [Verification and settlement](#verification-and-settlement)
   - [Partner interfaces](#partner-interfaces)
4. [Invariants](#invariants)
5. [Reference implementation](#reference-implementation)
   - [Install](#install)
   - [Quick start](#quick-start)
   - [Operator console](#operator-console)
   - [HTTP API](#http-api)
   - [Configuration](#configuration)
   - [Python API](#python-api)
6. [Conformance](#conformance)
7. [Security considerations](#security-considerations)
8. [Repository layout](#repository-layout)
9. [Development](#development)
10. [Roadmap](#roadmap)
11. [License](#license)

---

## Motivation

Static agent registries know what a worker *claims* it can do. They do not know what happened yesterday, and they forget on restart.

Praetor treats operational history as protocol state:

- A failure is recorded, not discarded.
- A subsequent coordinator instance reconstructs that record before it routes.
- Payment is gated on verification. An unverifiable result never reaches the settlement adapter.
- Removing memory is not a cache flush. It removes the protocol’s defining behavior. See [Conformance](#conformance).

---

## Protocol

```
  Client                    Praetor                     Memory                Worker / chain
    |                          |                           |                         |
    |  Job(task, category, $)  |                           |                         |
    |------------------------->|  load profiles + events   |                         |
    |                          |-------------------------->|                         |
    |                          |  rank eligible workers    |                         |
    |                          |  assign                   |                         |
    |                          |---------------------------------------------------->|
    |                          |  verify result            |                         |
    |                          |  settle iff verified      |                         |
    |                          |  write event + receipt    |                         |
    |                          |-------------------------->|                         |
    |  JobResult + receipt     |                           |                         |
    |<-------------------------|                           |                         |
```

Optional partners attach at two boundaries only:

| Boundary | Partner | Role |
|---|---|---|
| Delegation | Virtuals ACP | Submit the job to an on-chain agent |
| Settlement | Base USDC | Pay the worker after verification |

Neither partner is required for routing. The core protocol depends on a `MemoryStore` and a ranking function.

### Coordination loop

Every job is a six-step sequence. Each step is observable.

| Step | Name | Action |
|---|---|---|
| 1 | **Request** | Accept `task`, `category`, and `value_usdc`. |
| 2 | **Recall** | Reconstruct worker profiles, events, and failure notes from memory. |
| 3 | **Route** | Rank eligible workers and assign one. Emit `job_assigned`. |
| 4 | **Verify** | Run the result through a `ResultVerifier`. Unverified successes are rewritten as failures. |
| 5 | **Publish** | Persist the outcome, update reputation, write `receipt:<job_id>`. Emit `job_completed`. |
| 6 | **Settle** | If and only if the result is successful *and* verified, call the payment adapter. |

### Objects

```text
Job            { id, task, category, value_usdc }
WorkerProfile  { name, capabilities[], wallet, acp_agent,
                 max_value_usdc, successes, failures,
                 requires_review, failure_notes[] }
JobResult      { worker, success, output, reason,
                 verified, verification_reason,
                 payment_reference, acp_reference, routing_trace }
Receipt        keyed receipt:<job_id> — immutable settlement record
```

Reliability of a worker with `n = successes + failures` jobs:

```text
reliability(w) = successes / n     if n > 0
               = 0.5               otherwise   (cold start)
```

### Routing

Eligible workers are those whose `capabilities` contain the job `category` and that have not been archived.

Candidates are ranked by a descending tuple. The first component that differs decides.

| Priority | Key | Winner |
|---|---|---|
| 1 | `not requires_review` | Workers not flagged for review |
| 2 | `not semantic_hit` | Workers whose recorded `failure_notes` do **not** overlap the current task |
| 3 | `reliability` | Higher historical success rate |
| 4 | `-failures` | Fewer historical failures |

`semantic_hit` is true when memory search (Sibyl FTS5, or a deterministic token-overlap fallback) associates the worker’s failure notes with the current task text **and** `failures > 0`.

The ranking, the candidate set, and the semantic matches are returned in `JobResult.routing_trace`. Routing is a pure function of memory state plus the job. A fresh `Coordinator` against the same store produces the same choice.

### Memory model

Praetor binds to Sibyl Memory’s five-tier schema. Every tier is load-bearing. Removing any one degrades a specified behavior.

| Tier | Role in Praetor | Operations |
|---|---|---|
| **WARM** (entities) | Worker profiles: capability, reliability, limits, review flag, failure notes | `set_entity` / `get_entity` / `list_entities` / `archive_entity` |
| **COLD** (events) | Job history: `worker_registered`, `worker_updated`, `job_assigned`, `job_completed`, `worker_archived` | `write_event` / `read_events` |
| **HOT** (state) | Live scoreboard `coordinator:stats` — jobs total / succeeded / failed / settlements | `set_state` / `get_state` |
| **REFERENCE** (receipts) | Immutable per-job receipt `receipt:<job_id>` (worker, verification, Base tx, ACP id) | `set_reference` / `get_reference` |
| **Search** (FTS5) | Task-aware downweight of workers whose prior failures resemble this task; operator `GET /api/search` | `search_entities` / `search` |

Without a configured database the reference implementation uses an in-memory store that implements the same `MemoryStore` contract. State is then lost on process exit. That mode is for tests and local demonstration, not production.

Worker retirement calls `archive_entity`. The entity leaves the active routing set; events and receipts are not deleted.

### Verification and settlement

```text
execute(job) → result
verify(job, result) → (ok, reason)
if not ok: result.success := false
if result.success and payment configured:
    assert worker.wallet
    assert job.value_usdc ≤ worker.max_value_usdc   (when a limit is set)
    pay(worker.wallet, job.value_usdc, job.id)
else:
    do not call the payment adapter
```

The reference verifier (`BasicVerifier`) rejects empty output and worker-reported failure. Applications may substitute a stricter `ResultVerifier`. The gate is the protocol requirement; the particular checks are an implementation choice.

Praetor does not fabricate payments or ACP jobs. Unconfigured partners raise rather than simulate success. A Base client without `BASE_PRIVATE_KEY` validates against the live chain and returns a `dryrun:` reference; it does not broadcast.

### Partner interfaces

The core depends on two narrow protocols, not on Base or Virtuals specifically:

```python
class PaymentClient:
    def pay(self, recipient: str, amount_usdc: float, memo: str) -> str: ...

class ACPClient:
    def submit_job(self, agent: str, task: str) -> str: ...
```

A `PartnerReceipt` carries `provider`, `reference`, and `live`. A reference prefixed `dryrun:` is chain-validated but not broadcast; `live` is false.

---

## Invariants

1. **Memory is authoritative.** A coordinator reconstructs worker state from the store on every job. An in-process cache is not the source of truth.
2. **Verification precedes settlement.** An unsuccessful or unverifiable result never reaches `PaymentClient.pay`.
3. **No simulated success.** Missing partner configuration is an error, not a fake receipt.
4. **Reputation is monotonic in evidence.** A failed job increments `failures`, sets `requires_review`, and appends `failure_notes`. Editing a worker’s wallet or capabilities MUST NOT reset those fields.
5. **Archive, do not erase.** Retirement removes a worker from routing and leaves the audit trail intact.
6. **Deletion changes routing.** The same job against remembered failure state and against an empty store MUST select different workers. This is the [conformance test](#conformance).

---

## Reference implementation

Package `praetor` (`0.1.0`). Commands: `praetor`, `praetor-server`. Import namespace: `praetor`.

### Install

```bash
git clone https://github.com/drained69/Praetor.git
cd Praetor
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,server]'
```

| Extra | Contents |
|---|---|
| `server` | FastAPI dashboard, Uvicorn, Web3 |
| `sibyl` | `sibyl-memory-client` (durable memory) |
| `base` | Web3 + dotenv (USDC settlement) |
| `virtuals` | Virtuals ACP SDK |
| `dev` | pytest and test-time server stack |

### Quick start

No credentials or network access required:

```bash
.venv/bin/python -m praetor
```

```text
Fresh session routed to: risk-reviewer-v2
Verification: passed
Outcome: success
```

What ran:

1. `risk-reviewer-v1` fails to provide required evidence.
2. That failure is written to memory.
3. A new `Coordinator` is constructed against the same store.
4. A similar job is routed to `risk-reviewer-v2`.

Prove the load-bearing property:

```bash
.venv/bin/praetor --deletion-test
```

### Operator console

```bash
.venv/bin/praetor-server
```

| URL | Surface |
|---|---|
| <http://127.0.0.1:8000> | Public landing |
| <http://127.0.0.1:8000/app> | Operator console |

The console submits jobs, registers workers, inspects reputation, and reports live Base / Virtuals status when those stacks are configured.

A production image is in `Dockerfile` (`python:3.12-slim`, `praetor-server` on `$PORT`). Railway deploys from `railway.json` and health-checks `GET /api/health`.

### HTTP API

Write endpoints (`POST /api/workers`, `DELETE /api/workers/{name}`, `POST /api/jobs`, `POST /api/reset`) require header `X-Admin-Token` when `PRAETOR_ADMIN_TOKEN` is set. If it is unset the surface is open; the console warns. Set the token before exposing the server.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | no | Memory backend, partner status, operator flags |
| `GET` | `/api/state` | no | Worker profiles reconstructed from memory |
| `GET` | `/api/receipts/{job_id}` | no | Immutable settlement receipt |
| `GET` | `/api/search?q=` | no | Cross-tier search over workers, events, receipts, state |
| `POST` | `/api/workers` | admin | Register or update a worker (reputation preserved on edit) |
| `DELETE` | `/api/workers/{name}` | admin | Archive a worker (audit trail kept) |
| `POST` | `/api/jobs` | admin | Route, execute, verify, settle |
| `POST` | `/api/deletion-test` | no | Conformance: remembered vs empty store |
| `POST` | `/api/reset` | admin | Reset seeded demo workers only; 409 in operator mode |

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H 'content-type: application/json' \
  -H "X-Admin-Token: $PRAETOR_ADMIN_TOKEN" \
  -d '{"task":"Review a Base lending protocol","category":"risk","value_usdc":1.0}'
```

Register a worker:

```bash
curl -X POST http://127.0.0.1:8000/api/workers \
  -H 'content-type: application/json' \
  -H "X-Admin-Token: $PRAETOR_ADMIN_TOKEN" \
  -d '{"name":"risk-reviewer-v2","capabilities":["risk"],"wallet":"0x…"}'
```

### Configuration

Copy `.env.example` to `.env`. The file is gitignored and loaded automatically from the working directory upward. Already-exported environment variables take precedence. Secrets are never logged.

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `PRAETOR_DB` | unset (in-memory) | Path to the Sibyl SQLite database |
| `PRAETOR_ADMIN_TOKEN` | unset (open writes) | Shared secret for write endpoints |
| `PRAETOR_NO_PARTNERS` | `0` | Disable Base and Virtuals wiring |
| `PRAETOR_SEED_DEMO_WORKERS` | `0` | Seed two demo reviewers (tests / demos only) |
| `BASE_CHAIN_ID` | `84532` | `8453` mainnet, `84532` Base Sepolia |
| `BASE_RPC_URL` | chain default | JSON-RPC endpoint |
| `BASE_PRIVATE_KEY` | unset (dry-run) | Signer; required to broadcast |
| `BASE_USDC_ADDRESS` | Circle canonical | Override only for custom deployments |
| `VIRTUALS_AGENT_WALLET_ADDRESS` | — | ACP agent account |
| `VIRTUALS_ENTITY_ID` | — | ACP entity id |
| `VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY` | — | Whitelisted signer |
| `VIRTUALS_CHAIN_ID` | `84532` | ACP chain |
| `VIRTUALS_BACKEND` | `auto` | `acp` (CLI, preferred) or `sdk` |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Server bind |

Durable memory:

```bash
export PRAETOR_DB="$HOME/.sibyl-memory/memory.db"
.venv/bin/praetor-server
```

CLI against the same store:

```bash
.venv/bin/python -m praetor --db "$PRAETOR_DB"
```

| Stack | Capability | Activation |
|---|---|---|
| **Sibyl Memory** | Durable profiles, events, receipts, search | `PRAETOR_DB` |
| **Base** | USDC settlement; dry-run validation without a key | `BASE_RPC_URL`; `BASE_PRIVATE_KEY` to broadcast |
| **Virtuals ACP** | Agent-to-agent delegation | agent wallet + whitelisted signer |

Never commit credentials. On mainnet the signer must hold ETH (gas) and USDC (payouts).

### Python API

```python
from praetor import Coordinator, Job, WorkerProfile, SibylMemoryStore
from praetor.integrations import BaseUSDCClient
from praetor.partners import BasePaymentAdapter, VirtualsACPAdapter
from praetor.integrations import VirtualsACPClient

memory = SibylMemoryStore("/path/to/memory.db")
payment = BasePaymentAdapter(BaseUSDCClient())
acp = VirtualsACPAdapter(VirtualsACPClient())

coordinator = Coordinator(
    memory,
    workers=[WorkerProfile("risk-reviewer", ["risk"], wallet="0x…")],
    executor=your_executor,
    payment=payment,
    acp=acp,
)
result = coordinator.run(Job("Review a Base lending protocol", "risk", value_usdc=1.0))
print(result.worker, result.verified, result.payment_reference)
```

Adapters may be used independently:

```python
receipt = payment.pay_worker("0xWorkerWallet", 1.0, "job-id")
print(receipt.reference, receipt.live)
```

---

## Conformance

The shortest proof that memory is load-bearing:

```bash
.venv/bin/praetor --deletion-test
```

The same category is routed twice: once with a remembered failure, once against an empty store.

| Store | Selected worker |
|---|---|
| Remembered failure on `known-failure` | `clean` |
| Empty store | `known-failure` |

If both selections match, the implementation is not conformant. Removing Sibyl Memory does not clear a cache; it removes risk-aware routing.

The HTTP equivalent is `POST /api/deletion-test`, which returns `load_bearing: true` on success.

---

## Security considerations

- **Admin token.** Unset `PRAETOR_ADMIN_TOKEN` leaves write endpoints unauthenticated. Required for any network-exposed deployment.
- **Signing keys.** `BASE_PRIVATE_KEY` and `VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY` authorize on-chain transfers. Scope them, keep them out of git, and prefer testnet until the operator flow is verified.
- **Dry-run vs live.** A `dryrun:` payment reference is a real chain read, not a broadcast. Do not treat it as a settlement proof.
- **Mainnet.** `BASE_CHAIN_ID=8453` moves value. Confirm `GET /api/health` → `operator.mainnet` before submitting paid jobs.
- **Demo seeding.** `PRAETOR_SEED_DEMO_WORKERS=1` injects synthetic reviewers. Leave it off in production.
- **Verifier strength.** `BasicVerifier` is a structural gate (non-empty output, reported success). Domain-specific safety belongs in a substituted `ResultVerifier`.
- **Archive vs delete.** Operators should archive workers. Hard-delete paths exist only to reset seeded demo state.
- **Receipt writes are best-effort.** A failure to persist `receipt:<job_id>` does not roll back the job. Operators should alert on missing receipts rather than assume atomicity with settlement.

---

## Repository layout

```text
src/praetor/
├── core.py                 Job, WorkerProfile, Coordinator (normative loop)
├── memory.py               MemoryStore, Sibyl and in-memory backends
├── verification.py         ResultVerifier (BasicVerifier)
├── partners.py             PaymentClient, ACPClient, adapters
├── api.py                  FastAPI app and HTTP surface
├── demo.py                 Two-session demo and deletion test
├── env.py                  .env loading (no override of exported vars)
├── web/landing.html        Public explainer
├── web/index.html          Operator console
└── integrations/
    ├── config.py           Environment-driven partner configuration
    ├── base_payment.py     Base USDC client
    ├── virtuals_acp.py     Virtuals ACP SDK client
    └── virtuals_cli.py     Virtuals ACP CLI client

tests/                      Unit, integration, and API tests
Dockerfile                  Production image (Python 3.12)
railway.json                Deploy contract
```

---

## Development

```bash
.venv/bin/pytest -q
```

Coverage includes routing persistence, worker discovery, unsupported categories, verification gates, payment and ACP receipts, partner configuration, provider failures, and the dashboard flow.

Live Base tests are skipped unless enabled:

```bash
RUN_LIVE_BASE=1 .venv/bin/pytest -k 'live_chain or zero_balance'
```

For a real Sibyl round trip:

```bash
.venv/bin/pip install -e '.[dev,sibyl]'
.venv/bin/sibyl init
.venv/bin/sibyl health
```

See the [Sibyl Memory documentation](https://docs.sibyllabs.org/).

---

## Roadmap

**Now** — durable routing, verification gates, Base / Virtuals references in one workflow.

**Next**

- End-to-end Virtuals ACP provider registration
- Broadcast Base testnet USDC settlement with a funded test key
- Worker health checks, approval thresholds, retries, escalation
- Signed job receipts, audit export, authentication, tenant authorization

**Then** — consent-based cross-organization reputation, with evidence-backed capability claims and dispute workflows.

---

## License

MIT. See [LICENSE](LICENSE).
