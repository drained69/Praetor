# Praetor

### Memory-backed coordination for autonomous agents

**Praetor remembers which agents earned trust, then uses that memory to decide who gets the
next job.**

Praetor is a coordinator for agent workflows. It matches tasks to specialist workers, records
assignments and outcomes in [Sibyl Memory](https://docs.sibyllabs.org/), and changes future
routing when a worker has failed before. The decision survives a process restart because the
worker's operational history is durable, not held in a transient in-process cache.

> Identity and payment tell an agent economy *who* can work and *how* to settle. Praetor adds
> the missing layer: evidence of what each worker actually did.

**[Live dashboard](http://127.0.0.1:8000)** · [Install](#install) · [Quick start](#quick-start) ·
[How it works](#how-it-works) · [Integrations](#integrations) · [Deletion test](#deletion-test) ·
[Development](#development)

## Install

Python 3.10 or newer is supported. The server extra includes the dashboard dependencies.

```bash
git clone <your-repository-url> praetor
cd praetor
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,server]'
```

The package is named `praetor`, and its commands are `praetor` and `praetor-server`. The
underlying Python import namespace remains `praetor` for compatibility with the current
source layout and existing consumers.

## Quick Start

Run the deterministic memory demonstration. It needs no credentials or network access:

```bash
.venv/bin/python -m praetor
```

Expected output:

```text
Fresh session routed to: risk-reviewer-v2
Verification: passed
Outcome: success
```

The demo performs two sessions:

1. `risk-reviewer-v1` fails to provide critical evidence.
2. Praetor persists that failure in memory.
3. A fresh coordinator is created.
4. A similar task is routed to `risk-reviewer-v2`.

Run the explicit comparison between remembered and empty state:

```bash
.venv/bin/praetor --deletion-test
```

## Live Product

Start the FastAPI dashboard locally:

```bash
.venv/bin/praetor-server
```

Open <http://127.0.0.1:8000>. The dashboard lets you submit a risk job, inject a worker
failure, inspect the resulting reputation, and run the deletion test. It also reports live
Base status and partner references when those integrations are configured.

REST endpoints:

| method | endpoint | purpose |
|---|---|---|
| `GET` | `/api/health` | Memory, partner, and builder-score status |
| `GET` | `/api/state` | Worker profiles reconstructed from memory |
| `POST` | `/api/jobs` | Route and execute a job |
| `POST` | `/api/deletion-test` | Prove routing changes when memory is removed |

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H 'content-type: application/json' \
  -d '{"task":"Review a Base lending protocol","category":"risk","value_usdc":1.0}'
```

## Configuration

Configuration is environment-driven. Copy `.env.example` to `.env`; `.env` is gitignored and
is loaded automatically. Already-exported environment variables take precedence.

```bash
cp .env.example .env
```

### Memory

Without a database path, the server uses a deterministic in-memory store. To make reputation
durable across restarts, point Praetor at the SQLite database used by Sibyl Memory:

```bash
export SIBYL_RELAY_DB="$HOME/.sibyl-memory/memory.db"
.venv/bin/praetor-server
```

You can also run the CLI against that database:

```bash
.venv/bin/python -m praetor --db "$SIBYL_RELAY_DB"
```

Set `SIBYL_RELAY_NO_PARTNERS=1` for a local run without Base or Virtuals wiring. The variable
names retain the `SIBYL_RELAY_` prefix because they are part of the existing deployment
interface.

### Optional partner stacks

The core coordinator works with Sibyl Memory alone. Optional stacks add real external actions:

| stack | capability | activation |
|---|---|---|
| **Sibyl Memory** | Durable worker profiles, routing history, and audit events | `SIBYL_RELAY_DB` |
| **Base** | USDC settlement on Base; dry-run validation without a signing key | `BASE_RPC_URL`, optional `BASE_PRIVATE_KEY` |
| **Virtuals ACP** | Agent-to-agent job delegation | `VIRTUALS_AGENT_WALLET_ADDRESS`, `VIRTUALS_WHITELISTED_WALLET_PRIVATE_KEY` |

Praetor does not fabricate successful payments or ACP jobs. Base connects to the configured
chain and validates a transfer in dry-run mode by default. A funded `BASE_PRIVATE_KEY` is
required before it broadcasts. Virtuals requires a configured buyer agent and supported ACP
backend. Never commit credentials to the repository.

## How It Works

```text
                 job
                  |
                  v
        +--------------------+
        |      Praetor       |
        | match, execute,    |
        | verify, settle     |
        +----------+---------+
                   |
          load profile + history
                   v
        +--------------------+
        |   Sibyl Memory     |
        | profiles + events  |
        +----------+---------+
                   |
                   v
        +--------------------+
        |  Specialist worker |
        +--------------------+
```

Worker selection currently ranks eligible workers by:

1. Workers that do not require review.
2. Historical reliability.
3. Lower failure count.

Every assignment and completion is recorded. A failed result increments the worker's failure
count, marks it for review, and stores the reason. The next `Coordinator` instance reads that
state back from Sibyl Memory before choosing a worker.

### Memory model — all five Sibyl tiers, load-bearing

Praetor is built directly on Sibyl Memory's five-tier hierarchical schema. Every tier does
real work in the routing loop; remove any one and the product degrades.

| Sibyl tier | Praetor use | API |
|---|---|---|
| **WARM** (entities) | Worker profiles — capability, reliability, limits, review status, failure notes | `set_entity` / `get_entity` / `list_entities` / `archive_entity` |
| **COLD** (events) | Job history — `worker_registered`, `job_assigned`, `job_completed`, `worker_archived` | `write_event` / `read_events` |
| **HOT** (state) | Live coordinator scoreboard — `coordinator:stats` counters (jobs total / succeeded / failed / settlements) | `set_state` / `get_state` |
| **REFERENCE** (receipts) | Immutable per-job settlement receipt keyed `receipt:<job_id>` with Base tx + ACP references and verification result | `set_reference` / `get_reference` |
| **Search** (FTS5) | Task-aware routing (semantic failure downweight) **and** the operator's cross-tier `/api/search` | `search_entities` / `search` |

The coordinator never treats an in-process cache as its source of truth. The memory layer
is the source of truth — kill the process and every profile, counter, and receipt is
reconstructed from Sibyl on the next boot.

### How each tier earns its place

1. **Recall (WARM + COLD).** A fresh `Coordinator` against the same Sibyl DB reads each
   worker's `successes`, `failures`, `requires_review`, and `failure_notes` before its first
   routing decision. This is the defining behavior — see the [deletion test](#deletion-test).
2. **Task-aware routing (Search).** Before ranking candidates, the coordinator runs Sibyl's
   FTS5 search against the current task text. Any worker whose recorded `failure_notes`
   semantically overlap with the task is *downweighted* — turning flat reputation
   (*"worker failed once"*) into task-aware reputation (*"worker failed on **this kind** of
   work"*). The reasoning is returned in `JobResult.routing_trace` and rendered on the
   dashboard: *"Semantic downweight: atlas previously failed on similar work — routed to
   nova instead."*
3. **Live telemetry (HOT).** Every job atomically advances a `coordinator:stats` document in
   the HOT tier. The dashboard reads it back; it survives restarts.
4. **Durable receipts (REFERENCE).** Every completed job writes an immutable receipt to the
   REFERENCE tier (`receipt:<job_id>`) carrying the worker, verification result, Base tx
   hash, and ACP job id. `GET /api/receipts/{job_id}` looks it up without replaying the
   event log.
5. **Audit-preserving retirement (Archive).** Removing a worker calls `archive_entity`, not
   a hard delete — the entity leaves the active routing set but stays recoverable, and its
   events and receipts are untouched.
6. **Storage hygiene.** The dashboard surfaces `free_tier_status` (DB size, % of cap) so an
   operator can see the memory layer's real footprint.

Reflection (`learn`) and consolidation are available in `sibyl-memory-client` and are the
natural next layer; Praetor's routing is a deterministic function over the tiers above, so
it does not depend on them today.

### Verification before settlement

When configured, Praetor can delegate through Virtuals ACP, execute the job, verify the report,
and settle payment through Base. An unsuccessful or unverifiable result never reaches the
payment adapter. Partner references are persisted with the completion event and returned in
the API response.

## Integrations

The core depends on narrow protocols rather than provider-specific logic:

```python
class PaymentClient:
    def pay(self, recipient: str, amount_usdc: float, memo: str) -> str: ...


class ACPClient:
    def submit_job(self, agent: str, task: str) -> str: ...
```

Use the adapters independently or together:

```python
from praetor.integrations import BaseUSDCClient
from praetor.partners import BasePaymentAdapter

payment = BasePaymentAdapter(BaseUSDCClient())
receipt = payment.pay_worker("0xWorkerWallet", 1.0, "job-id")
print(receipt.reference, receipt.live)
```

```python
from praetor.integrations import VirtualsACPClient
from praetor.partners import VirtualsACPAdapter

acp = VirtualsACPAdapter(VirtualsACPClient())
receipt = acp.delegate("risk-reviewer", "perform risk review")
print(receipt.reference)
```

## Deletion Test

Memory is load-bearing by design. The shortest proof is:

```bash
.venv/bin/praetor --deletion-test
```

The comparison runs the same category with remembered failure state and with an empty store.
With memory, the flagged worker is avoided. Without memory, that evidence does not exist and
the worker can be selected again. Removing Sibyl Memory therefore removes Praetor's defining
risk-aware routing behavior; it is not merely clearing a performance cache.

## Repository Layout

```text
src/praetor/
├── core.py                Jobs, worker profiles, and coordinator
├── demo.py                Two-session demo and deletion test
├── memory.py              Sibyl and in-memory stores
├── partners.py            Payment and ACP protocols plus adapters
├── verification.py        Verification-before-settlement gate
├── api.py                 FastAPI dashboard and REST API
├── web/index.html         Interactive dashboard
└── integrations/
    ├── config.py          Environment-driven partner configuration
    ├── base_payment.py    Base USDC client
    ├── virtuals_acp.py    Virtuals ACP SDK client
    └── virtuals_cli.py   Virtuals ACP CLI client

tests/                     Unit, integration, and API tests
video/                     Praetor product demo video source
```

## Development

Run the automated suite:

```bash
.venv/bin/pytest -q
```

The tests cover routing persistence, worker discovery, unsupported categories, verification
gates, payment and ACP receipt handling, partner configuration, provider failures, and the
end-to-end dashboard flow. Live Base tests are skipped unless explicitly enabled:

```bash
RUN_LIVE_BASE=1 .venv/bin/pytest -k 'live_chain or zero_balance'
```

For a real Sibyl Memory round trip, install the optional client and initialize Sibyl as
described in the [Sibyl Memory documentation](https://docs.sibyllabs.org/):

```bash
.venv/bin/pip install -e '.[dev,sibyl]'
.venv/bin/sibyl init
.venv/bin/sibyl health
```

## Roadmap

- Register and connect a real Virtuals ACP provider end to end.
- Broadcast a Base testnet USDC settlement with a funded test key.
- Add worker registration and health checks.
- Add human approval thresholds, retries, and escalation policies.
- Add signed job receipts, audit export, authentication, and tenant authorization.
- Build cross-organization reputation with explicit consent and evidence-backed capability claims.

## License

MIT. See [LICENSE](LICENSE).
