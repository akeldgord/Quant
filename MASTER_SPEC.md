PROJECT ARGUS

MASTER BUILD SPECIFICATION v2.0

Canonical Implementation Contract

Solana Wallet Intelligence, Copyability Research, Alpha-Ancestry Graph, Synthetic Trader, and Isolated Execution Engine

⸻

0. AUTHORITY

This file is the single authoritative implementation contract for Project ARGUS.

Do not use earlier versions, addenda, chat summaries, or prior architectural notes as implementation instructions.

If a requirement is not contained in this file or in a later explicit instruction from the ARGUS ORCHESTRATOR, do not infer it from earlier conversations.

After implementation begins, approved changes must be recorded in:

docs/DECISION_LOG.md

Latest explicit orchestrator instruction supersedes this file only where the instruction explicitly says so.

⸻

1. YOUR ROLE

You are the ARGUS IMPLEMENTATION AGENT.

You implement.

You do not redesign the system.

The roles are:

HUMAN OPERATOR
    controls credentials
    controls capital
    controls live arming
    transports checkpoints
ARGUS ORCHESTRATOR
    architecture
    research reasoning
    phase approval
    changes to this specification
IMPLEMENTATION AGENT
    code
    tests
    migrations
    CLI
    documentation
    checkpoint reports
ARGUS
    deterministic runtime system

The implementation agent MUST:

* follow this specification,
* work one phase at a time,
* test before claiming success,
* preserve point-in-time truth,
* report failures honestly,
* stop at every phase gate,
* produce the required orchestrator checkpoint,
* avoid consequential architectural improvisation.

The implementation agent MUST NOT:

* make live capital-allocation decisions,
* weaken safety thresholds because trades are rare,
* change providers/architecture without approval,
* substitute mocks for required production functionality and call the phase complete,
* use an LLM in the runtime trading decision loop,
* access or request a private trading key,
* initiate a mainnet strategy trade.

⸻

2. ALLOWED IMPLEMENTATION DISCRETION

The agent MAY independently choose minor implementation details that do not affect:

* research validity,
* financial behavior,
* persistent schemas,
* provider cost,
* security boundaries,
* phase semantics,
* execution safety,
* reproducibility.

Examples of acceptable discretion:

function names
internal helper classes
test fixture organization
minor SQL index choices
logging helper structure
ordinary error-message wording
module-local refactors

Examples requiring ORCHESTRATOR REVIEW:

database replacement
new paid provider
different accounting method
different scoring formula
different live eligibility rule
different private-key architecture
different transaction execution flow
schema redesign that removes required history
microservices
new message broker
new runtime AI
automatic scaling rules
changing score thresholds
changing risk semantics

Do not ask the human routine coding questions when the answer can be derived from this file.

⸻

3. MISSION

ARGUS is not primarily a copy-trading bot.

ARGUS is an on-chain research and trading laboratory designed to answer:

When ARGUS observes a wallet act, does exploitable information remain after discovery bias, incomplete history, detection latency, liquidity, transaction costs, execution constraints, follower behavior, and realistic exits?

Its intended evolution is:

historical token winners
        ↓
early-wallet discovery
        ↓
unbiased wallet qualification
        ↓
prospective observation
        ↓
shadow copying
        ↓
copyability measurement
        ↓
micro live execution
        ↓
wallet leadership graph
        ↓
Alpha Ancestry
        ↓
Convergence Surprise
        ↓
entry/exit specialists
        ↓
Synthetic Super-Wallet
        ↓
prediction of future informed order flow

ARGUS should eventually discover where information originates, not merely which wallets previously made money.

⸻

4. FIRST-FIVE-DAY OBJECTIVE

ARGUS should be technically capable of a first strategy-driven MICRO live trade within five calendar days of initial startup if:

* all software readiness gates pass,
* a human-authorized mainnet canary has passed,
* the operator has explicitly armed live execution,
* an authentic signal satisfies all eligibility rules.

ARGUS MUST NOT manufacture a trade to meet this deadline.

There is:

NO DAY-5 DESPERATION TRADE

Five days is an engineering-readiness target.

Five days is NOT considered statistical validation of wallet alpha.

⸻

5. NON-NEGOTIABLE SYSTEM PRINCIPLES

CORE-001 — Point-in-time truth

Historical beliefs may never be rewritten using future information.

If a wallet score was 61 when a signal occurred and later became 95:

signal.wallet_score_at_signal = 61

forever.

CORE-002 — Raw observations are immutable

Raw chain/provider observations are append-only.

Derived data may be recomputed.

Raw evidence may not be silently altered or deleted.

CORE-003 — Observation time differs from chain time

Always distinguish:

block_time
first_seen_at
confirmed_at
finalized_at

first_seen_at means the time ARGUS first became aware of the event.

CORE-004 — Every decision is reproducible

Every meaningful decision records:

algorithm version
config version/hash
git commit
input references
timestamp
reason codes
result

CORE-005 — Skill is not copyability

Maintain separately:

skill
copyability
forward information value
confidence

CORE-006 — Addresses are not automatically independent actors

Wallet clustering and independence estimation are mandatory.

CORE-007 — Bots are classified, not automatically discarded

A systematic wallet can contain useful information.

CORE-008 — Runtime trading is deterministic

No LLM is required for:

wallet scoring
signal creation
risk decisions
trade sizing
execution
sell decisions

CORE-009 — Research and custody are separated

Research processes never access the signing key.

CORE-010 — Failure to trade is valid

No threshold is weakened merely because the system has been inactive.

CORE-011 — Truth outranks impressive P&L

A modest clean result outranks a spectacular contaminated backtest.

⸻

6. FIXED TECHNOLOGY STACK

These choices are fixed unless the orchestrator explicitly changes them.

TECH-001 — Language

Python 3.12.

TECH-002 — Environment/package manager

Use uv.

Repository contains:

pyproject.toml
uv.lock

TECH-003 — Application architecture

Use a modular monolith.

Logical workers may run as separate Docker processes from the same codebase.

DO NOT introduce:

Kubernetes
Kafka
RabbitMQ
Celery
microservice sprawl

TECH-004 — Canonical operational database

PostgreSQL 17.

Use:

SQLAlchemy 2.x
asyncpg
Alembic

Postgres stores canonical:

entities
point-in-time state
signals
wallet score history
relationships
trade intents
execution history
positions
audit records

TECH-005 — Analytical storage

Use:

Parquet
PyArrow
Polars
DuckDB

Large analytical datasets belong in Parquet.

DuckDB is used for research queries.

Do not turn Postgres into a full-chain data warehouse.

TECH-006 — API/admin service

FastAPI.

Initial endpoints only as needed:

/health
/ready
/metrics-summary
/webhooks/*

TECH-007 — CLI

Typer.

Primary executable:

argus

Every important pipeline must have a CLI entry point.

TECH-008 — Testing

Use:

pytest
pytest-asyncio
Hypothesis where valuable
pytest-cov

TECH-009 — Static quality

Use:

Ruff
mypy

TECH-010 — Containers

Docker Compose.

Target host:

Linux or WSL2

Host suspend/resume must be treated as a live-safety event.

⸻

7. REPOSITORY CONTRACT

Create approximately:

argus/
├── MASTER_SPEC.md
├── README.md
├── pyproject.toml
├── uv.lock
├── compose.yaml
├── Makefile
├── .gitignore
├── .env.example
│
├── config/
│   ├── argus.default.yaml
│   ├── providers.yaml
│   ├── scoring_v1.yaml
│   ├── signals_v1.yaml
│   ├── risk.default.yaml
│   └── bootstrap_tokens.example.csv
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── BUILD_STATE.md
│   ├── DATA_MODEL.md
│   ├── PROVIDERS.md
│   ├── RESEARCH_METHODS.md
│   ├── EXECUTION_SAFETY.md
│   ├── OPERATIONS.md
│   ├── RUNBOOK.md
│   ├── CHECKPOINTS.md
│   └── DECISION_LOG.md
│
├── migrations/
│
├── src/argus/
│   ├── cli.py
│   ├── config.py
│   ├── clock.py
│   ├── logging.py
│   │
│   ├── db/
│   ├── domain/
│   │
│   ├── providers/
│   │   ├── solana/
│   │   ├── helius/
│   │   ├── dexscreener/
│   │   ├── geckoterminal/
│   │   ├── jupiter/
│   │   ├── bigquery/
│   │   └── archives/
│   │
│   ├── ingestion/
│   ├── parsing/
│   ├── tokens/
│   ├── wallets/
│   ├── clustering/
│   ├── scoring/
│   ├── copyability/
│   ├── graph/
│   ├── signals/
│   ├── shadow/
│   ├── execution/
│   ├── risk/
│   ├── outcomes/
│   ├── research/
│   ├── notifications/
│   └── api/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   ├── replay/
│   └── fixtures/
│
├── scripts/
│   ├── bootstrap.sh
│   ├── checkpoint.sh
│   ├── backup.sh
│   └── smoke_test.sh
│
├── data/
│   ├── raw/
│   ├── parquet/
│   ├── cache/
│   └── exports/
│
└── runtime/
    ├── logs/
    ├── reports/
    └── state/

Runtime data, local datasets, credentials, and secrets MUST be gitignored.

⸻

8. SESSION RECOVERY PROTOCOL

Cheap coding agents may be restarted.

Every new implementation session MUST begin by reading:

MASTER_SPEC.md
docs/BUILD_STATE.md
docs/DECISION_LOG.md
latest checkpoint report
git status
git log -5

Then print no more than five lines containing:

current phase
last approved phase
current git commit
working tree state
next permitted action

Do not assume remembered state from a previous agent session.

docs/BUILD_STATE.md must include:

current_phase
last_completed_phase
last_orchestrator_approved_phase
approved_commit
awaiting_orchestrator_review
known_blockers

The implementation agent may update phase progress.

It may only mark a phase ORCHESTRATOR_APPROVED after receiving explicit approval.

⸻

9. DEPENDENCY AND SUPPLY-CHAIN POLICY

SEC-001

All Python dependencies must be pinned in uv.lock.

SEC-002

Do not use random/unmaintained packages merely to save coding time.

SEC-003

Prefer established libraries for:

Solana transaction structures
HTTP
WebSockets
database
serialization
testing

SEC-004

Do not execute installation patterns such as:

curl <unknown-script> | bash

without explicit necessity and review.

SEC-005

Never commit:

API keys
Telegram tokens
private keys
seed phrases
live-arm files

⸻

10. PROVIDER STRATEGY

Providers are adapters.

Domain code MUST NOT depend directly on provider-specific response objects.

Implement protocols/interfaces.

Conceptually:

class ChainProvider(Protocol):
    async def get_transaction(...)
    async def get_signatures_for_address(...)
    async def get_balance(...)
    async def get_token_accounts(...)
    async def get_slot(...)
class LiveChainStream(Protocol):
    async def subscribe_wallet(...)
    async def unsubscribe_wallet(...)
class MarketDataProvider(Protocol):
    async def token_snapshot(...)
    async def historical_ohlcv(...)
class ExecutionProvider(Protocol):
    async def get_order(...)
    async def execute(...)

⸻

11. FREE-FIRST POLICY

COST-001

ARGUS must begin with free provider tiers wherever practical.

COST-002

No provider upgrade may happen automatically.

COST-003

No paid API may be enabled without explicit human/orchestrator approval.

COST-004

Provider limits are not architectural constants.

Actual current provider capabilities must be probed/documented during Phase 1.

Use conservative local rate limits.

Never intentionally operate at the published maximum.

⸻

12. PROVIDER BASELINE

PROV-001 — Helius / Solana RPC

Use Helius standard RPC and standard WebSocket functionality as the initial live-chain provider.

Do NOT make paid Helius-exclusive historical APIs a requirement for free V1.

A paid accelerated historical adapter MAY exist but remains disabled.

PROV-002 — DexScreener

Use primarily for:

pair/token lookup
current liquidity
current price
volume
pair creation metadata
market cap/FDV where available

PROV-003 — GeckoTerminal

Use primarily for:

historical OHLCV
pool history
market-data fallback

Never make high-frequency live functionality depend on it.

PROV-004 — Jupiter

Use Jupiter for:

executable quotes
order construction
execution
reverse/sellability probes

Research and execution requests share a centrally coordinated priority scheduler.

PROV-005 — Historical sources

Support optional adapters for:

Google BigQuery public Solana data
free archival Parquet sources
standard Solana/Helius RPC

Historical source choice must be based on observed availability and cost.

Never silently use paid archival functionality.

⸻

13. PROVIDER CAPABILITY PROBE

Implement:

argus providers probe
argus providers probe-history
argus providers usage

probe reports:

provider
reachable
supported functions
current configured throttle
response contract status
latency
health

probe-history reports where applicable:

earliest available date
latest available date
available partitions
archive freshness
estimated query/download size
known limitations

Do not trust provider marketing/documentation as proof that a historical partition actually exists.

⸻

14. PROVIDER COST GUARD

Every outbound provider request records:

provider
endpoint
request_class
requested_at
response_at
latency_ms
status
retry_count
estimated_credits
bytes_received
cache_hit

Streaming accounting must additionally record:

connection count
subscription count
reconnect count
bytes received
estimated streaming credits

argus providers usage reports:

today
month-to-date
30-day projected usage
configured allowance
percentage used/projected
warnings

Warn at:

70%
85%
95%

No automatic upgrade.

⸻

15. PROVIDER REQUEST PRIORITIES

Provider traffic must be centrally prioritized.

For Jupiter:

P0  emergency live exit
P1  ordinary live exit
P2  live entry order
P3  live safety/sellability check
P4  prospective copyability quote
P5  shadow exit quote
P6  background research

If capacity is constrained:

delay/drop research
NEVER starve live safety/execution

Missing research data receives an explicit missing reason.

Do not fabricate observations.

⸻

16. BIGQUERY COST CONTROL

Any BigQuery query MUST first perform a dry run.

Record:

estimated_bytes_processed
maximum_bytes_billed

Abort if estimated bytes exceed configured ceiling.

Never use unrestricted:

SELECT *

against large historical tables.

The default system must function without paid BigQuery usage.

⸻

17. CLOCK MODEL

Use both:

UTC wall clock
monotonic clock

Wall clock:

persistent timestamps

Monotonic clock:

latency/duration measurement

Detect:

large wall-clock jumps
host suspend/resume
clock-health anomalies

If a material time anomaly occurs:

disable new live entries
reconnect providers
reconcile chain state
verify clock health

Only then may live entry resume.

⸻

18. CANONICAL EVENT LEDGER

Create immutable chain_events.

Minimum conceptual fields:

event_id UUID
chain
slot
block_time
first_seen_at
confirmed_at nullable
finalized_at nullable
provider
provider_received_at
transaction_signature
event_type
wallet_address nullable
mint nullable
raw_payload_reference or payload
payload_hash
parser_version
created_at

Use deduplication constraints.

Raw provider evidence must remain replayable.

⸻

19. LIVE CHAIN OBSERVATION: FAST PATH + TRUTH PATH

Every tracked wallet uses TWO complementary paths.

DATA-FAST

WebSocket observation for low latency.

DATA-TRUTH

Periodic RPC/history reconciliation for completeness.

WebSocket receipt alone is never treated as proof of complete observation.

Maintain per-wallet watermarks:

last_stream_signature
last_stream_slot
last_reconciled_signature
last_reconciled_slot
last_reconciliation_at
stream_health

On:

disconnect
reconnect
process restart
timeout
clock jump
host resume
subscription failure

run reconciliation.

If unresolved:

wallet_live_state = DEGRADED

A degraded wallet MUST NOT create new live entry intents.

⸻

20. COMMITMENT POLICY

Store where available:

processed first-seen time
confirmed time
finalized time

Initial MICRO live policy:

source wallet transaction MUST be confirmed

before it may trigger live execution.

Processed-only observations may be stored for latency research.

Later research may test whether trading from earlier commitment states is valuable.

Changing live commitment policy requires orchestrator approval.

⸻

21. GENERIC TRANSACTION/SWAP PARSER

Start with deterministic balance-delta reconstruction.

Do NOT initially build a separate parser for every Solana DEX.

For a tracked-wallet transaction:

1. obtain pre/post balances,
2. identify wallet-owned accounts,
3. canonicalize native SOL / wrapped SOL,
4. calculate net asset deltas,
5. account for network fees,
6. identify meaningful asset inflow/outflow,
7. classify transaction,
8. assign confidence.

Canonical classifications:

SWAP_SIMPLE
SWAP_COMPLEX
TRANSFER_IN
TRANSFER_OUT
TOKEN_CREATE
LP_ACTION
UNKNOWN

Canonical swap fields:

swap_id
event_id
wallet
input_mint
input_amount_raw
input_amount_ui
output_mint
output_amount_raw
output_amount_ui
network_fee_raw
slot
block_time
first_seen_at
confidence
parser_version

Ambiguous interpretation:

NO AUTOMATIC COPY TRADE

but preserve it for research.

⸻

22. FINANCIAL ARITHMETIC

Never use binary float for canonical financial accounting.

Use:

integer raw units

for on-chain quantities.

Use:

Decimal

for:

prices
P&L
risk limits
USD conversions
position accounting

Floating-point values may be used inside statistical models after canonical values are safely represented.

⸻

23. GOLDEN TRANSACTION FIXTURES

Maintain sanitized real-chain fixtures covering at least:

SOL → token
token → SOL
token → USDC
multi-hop swap
simple transfer
partial sell
multiple token accounts
ambiguous multi-asset transaction
failed transaction

Any parser change must replay all historical golden fixtures.

Unexpected classification changes fail the test suite until reviewed.

⸻

24. TOKEN LIFECYCLE MODEL

ARGUS must distinguish where observable:

TOKEN_CREATION
BONDING_CURVE
LAUNCHPAD_TRADING
MIGRATION
AMM_POOL
MULTIPLE_POOLS

Store:

venue
venue_program
pool_or_curve_address
lifecycle_stage

A wallet can be highly informative but impossible to copy during a particular lifecycle stage.

Therefore:

information value ≠ copyability

⸻

25. REFERENCE PRICE LEDGER

Create:

reference_asset_prices

At minimum:

SOL/USD
USDC/USD

Store:

asset
price
source
observed_at
confidence

Do not permanently assume USDC equals exactly $1.

Historical USD calculations should use point-in-time reference prices where practical.

⸻

26. HISTORICAL MARKET-STATE RULE

Historical metrics must use information appropriate to the historical timestamp.

Do NOT calculate:

historical market cap =
historical price × today's token supply

when supply could have changed.

Historical fields such as:

market cap
supply
liquidity
FDV
pool state

receive:

market_state_confidence

If contemporaneous data cannot be recovered:

NULL

is preferable to false precision.

⸻

27. CORE DATA ENTITIES

The exact normalized SQL implementation may vary modestly, but the following responsibilities are mandatory.

Token domain

tokens
token_market_snapshots
token_discovery_events
token_outcomes
reference_asset_prices

Wallet domain

wallets
wallet_discovery_events
wallet_activity
wallet_history_quality
wallet_metrics_snapshots
wallet_score_snapshots
wallet_tier_history

Wallet clusters

wallet_clusters
wallet_cluster_memberships
wallet_cluster_evidence
wallet_independence_snapshots

Transactions/positions

chain_events
swaps
wallet_positions
wallet_position_events
wallet_trade_roundtrips

Graph

wallet_lead_follow_events
wallet_relationship_snapshots

Signals

signals
signal_participants
signal_features
signal_decisions

Shadow

shadow_trade_intents
shadow_quotes
shadow_fills
shadow_positions
shadow_exit_quotes
shadow_outcomes

Live execution

trade_intents
orders
execution_attempts
fills
live_positions
execution_events
risk_events

Research

hypotheses
experiments
experiment_runs
counterfactual_sets
predictions
prediction_outcomes

Operations

provider_usage
jobs
job_runs
system_health
configuration_versions

⸻

28. WALLET DISCOVERY CHANNELS

ARGUS continuously expands its universe through four channels.

DISC-001 — Historical winner archaeology

Find wallets positioned early in historical extreme winners.

DISC-002 — Prospective winner archaeology

When ARGUS observes a token later cross major performance milestones, inspect its earlier participants.

DISC-003 — Alpha-Ancestry upstream discovery

If an elite wallet repeatedly buys after an unknown wallet, investigate the upstream wallet.

DISC-004 — Peer/network discovery

If independent skilled wallet clusters repeatedly overlap with an unknown address/cluster, investigate it.

Every discovered wallet receives explicit provenance.

⸻

29. WALLET DISCOVERY PROVENANCE

wallet_discovery_events must record:

wallet
discovered_at
discovery_channel
trigger_token nullable
trigger_wallet nullable
trigger_event nullable
trigger_reason
algorithm_version

Never lose the reason ARGUS began studying a wallet.

⸻

30. CRITICAL ANTI-SURVIVORSHIP RULE

Any token/event that caused ARGUS to discover a wallet is permanently excluded from the score used to qualify that wallet.

Maintain TWO score families.

DESCRIPTIVE SCORE

May use all known historical observations.

Answers:

What does this wallet's complete known record look like?

QUALIFICATION SCORE

Excludes discovery-triggering observations.

Answers:

Does the wallet look skilled using evidence separate from the evidence that caused us to notice it?

Only:

QUALIFICATION SCORE

may affect live eligibility.

Store excluded rows and:

exclusion_reason = DISCOVERY_CONTAMINATION

Never delete them.

⸻

31. NEGATIVE-CONTROL ARCHAEOLOGY

ARGUS must eventually compare historical winner archaeology against similar tokens that did NOT become extreme winners.

Control matching may include:

launch period
venue
early liquidity
early market cap
early transaction activity

Purpose:

Determine whether apparently impressive early wallets are merely:

generic snipers
launchpad regulars
high-frequency meme traders
bots that buy everything

This functionality need not block the first five-day live-readiness target, but schemas must support it.

⸻

32. WINNER DEFINITIONS

Initial research categories:

MAJOR_WINNER >= 10x
MONSTER      >= 20x
EXTREME      >= 50x

These categories are research labels, not trading signals.

The baseline price must be computed from an explicitly versioned methodology based on the earliest reliably tradable market state.

Do not use an untradeable zero-liquidity launch price merely to inflate multiples.

Store:

winner_definition_version
baseline_timestamp
baseline_price
baseline_liquidity
peak_price
peak_timestamp

⸻

33. EARLY-BUYER EXTRACTION

For historical winners, attempt to recover at least:

first 100 distinct meaningful net buyers

Preserve at minimum the earliest 50 useful candidates if recoverable.

Record:

wallet
token
first_buy_slot
first_buy_time
sequence_number
venue
lifecycle_stage
entry_price estimate
entry_market_state confidence
token_age
amount
USD estimate

Tag, do not automatically delete:

possible_deployer
possible_insider
possible_bundler
possible_funder_related
possible_bot

These wallets may contain information even when prohibited from copy trading.

⸻

34. HISTORICAL WALLET COMPLETENESS

Do NOT assume:

getSignaturesForAddress(wallet)

represents complete wallet activity.

Associated token-account activity may require additional reconstruction.

Every historical wallet analysis receives:

history_start
history_end
history_provider_set
history_completeness
history_completeness_reason

Allowed qualitative states:

HIGH
MEDIUM
LOW
UNKNOWN

Low/unknown completeness must reduce score confidence.

It may prevent live eligibility.

⸻

35. WALLET POSITION RECONSTRUCTION

Use deterministic inventory accounting.

V1 accounting:

weighted-average cost

Store raw position events so alternative accounting can later be recomputed.

For every token position derive where possible:

first_entry
last_entry
entry_quantity
entry_value
average_cost
partial_exits
final_exit
realized_P&L
unrealized_P&L
holding_duration
MFE
MAE
peak_value
peak_profit_capture

Transfers of uncertain origin are NOT magically purchases or sales.

Position confidence:

HIGH
MEDIUM
LOW
UNRESOLVED

Only high/medium confidence positions substantially contribute to qualification.

⸻

36. WALLET LIFECYCLE

Allowed wallet states:

DISCOVERED
WATCH
PROBATION
B
A
S
QUARANTINE
DORMANT
RETIRED

DISCOVERED

Insufficient analysis.

WATCH

Interesting enough for continued monitoring.

PROBATION

Historically interesting; prospectively shadow monitored.

B

Promising evidence; paper only by default.

A

Strong evidence; potentially live eligible.

S

Exceptional evidence; potentially live eligible.

QUARANTINE

Possible insider/common control/manipulation/data issue/predation.

No automatic live copying.

DORMANT

No meaningful recent activity.

RETIRED

Persistent degradation or disqualifying evidence.

Every state transition is timestamped and immutable.

⸻

37. WALLET FEATURE FINGERPRINT

Every scored wallet gets independent components:

selection_skill
early_discovery_skill
entry_timing_skill
exit_skill
risk_control_skill
consistency
copyability
forward_information_value
recency
confidence
insider_risk
cluster_risk
predation_risk
automation_probability

Do not reduce everything to one score internally.

⸻

38. WALLET QUALIFICATION SCORE v1

Normalize major components to 0–100.

Initial weights:

selection alpha             25%
consistency                 15%
entry timing                15%
forward information         15%
risk-adjusted return        10%
exit capture                10%
recency                      5%
data confidence              5%

Apply penalties separately:

insider penalty
cluster uncertainty penalty
lottery dominance penalty
data-quality penalty
predation penalty

Store:

score_version
component values
penalties
final score
confidence
excluded discovery observations

Do not optimize these weights during initial implementation.

They are V1 priors to be evaluated prospectively.

⸻

39. QUALIFICATION SAMPLE REQUIREMENTS v1

A wallet may not become A/S merely because of a tiny sample.

Initial historical eligibility target:

>= 20 usable closed positions
>= 10 distinct tokens with usable outcomes
history completeness not LOW/UNKNOWN
discovery-contaminating tokens excluded

These are minimum evidence gates, not proof of persistent alpha.

Small samples must be confidence-shrunk toward the population prior.

⸻

40. LOTTERY-DOMINANCE PROTECTION

Calculate:

median return
trimmed mean return
winsorized return
profit factor
hit rate
largest-trade contribution
top-three-trade contribution
max drawdown
number distinct profitable tokens

Flag:

LOTTERY_DOMINATED

when the largest position contributes more than 70% of estimated lifetime P&L.

This initially creates a penalty/flag, not automatic rejection.

⸻

41. RECENCY AND ALPHA DECAY

Maintain:

lifetime
180-day
90-day
30-day
7-day

metrics where data exists.

Recent observations receive greater influence using a versioned decay rule.

Historical observations are never deleted.

A formerly elite wallet may naturally fall in tier.

⸻

42. WALLET CLUSTERING

Evidence may include:

common funding source
direct transfers
same initial funder
synchronized transactions
repeated identical sizing
repeated identical token sequence
shared deployer relation
shared cash-out destination
strong temporal co-occurrence

ARGUS estimates:

probability of common control

It does NOT identify real-world people.

Cluster membership is temporal and versioned.

⸻

43. CONSERVATIVE INDEPENDENCE

Absence of proof of common control is NOT proof of independence.

Maintain:

independence_probability

For live convergence, uncertain dependence contributes less than confidently independent actors.

Three addresses likely belonging to one actor count approximately as one source of information.

⸻

44. PROSPECTIVE SHADOW MONITORING

Every sufficiently interesting tracked-wallet trade creates a prospective event.

Record:

leader transaction time
ARGUS first-seen time
confirmation time
wallet score snapshot
wallet tier snapshot
token state
wallet position-size context
current cluster state
current graph state

No later reconstruction may replace point-in-time values used in the original signal.

⸻

45. SHADOW COPY EXECUTION

For qualifying observations, obtain actual contemporaneous Jupiter quotes where practical.

Store:

signal time
quote-request time
quote-response time
actual latency
notional
expected output
price impact
route
fees estimate
quote success/failure

Never create an imaginary historical fill from a later price chart.

⸻

46. COPYABILITY DELAY PROBES

For prospectively observed wallet buys, attempt quote probes approximately at:

+1 second
+5 seconds
+15 seconds
+30 seconds
+60 seconds
+5 minutes

Provider capacity may prevent every probe.

Record actual request timestamp.

Never claim a +1s quote if the call occurred +2.7s later.

Use standardized shadow notionals.

V1 may begin with one configurable small notional.

⸻

47. EXECUTABLE RETURNS

Maintain two outcome families.

MARK RETURN

Based on market-price data.

Useful descriptively.

EXECUTABLE RETURN

Based on contemporaneous reverse quotes for the standardized position/notional.

This is the primary outcome for copyability.

Where capacity permits, request reverse quotes approximately at:

5m
30m
1h
6h
24h

Longer-horizon mark outcomes may also be stored:

3d
7d

Store:

target horizon
quote due time
actual quote time
scheduling delay
route available
executable output
price impact

⸻

48. UNSELLABLE IS A REAL OUTCOME

Explicitly record:

NO_ROUTE
INSUFFICIENT_LIQUIDITY
PRICE_IMPACT_EXCESSIVE
QUOTE_FAILED
TOKEN_RESTRICTED

Do not drop these rows.

A token showing:

mark return +500%

with no executable sell route does NOT receive +500% executable performance.

⸻

49. COPYABILITY SCORE v1

Initial components:

prospective delayed follower alpha    35%
liquidity/executability               15%
post-entry stability                  10%
holding-duration suitability          10%
latency tolerance                     10%
slippage sensitivity                  10%
sample confidence                     10%

Copyability confidence is separately stored.

Historical simulation may initialize a prior.

Prospective data progressively dominates.

⸻

50. INFORMATION HALF-LIFE

For each wallet estimate how rapidly exploitable forward information decays after ARGUS can observe its trade.

Research:

1s
5s
15s
30s
60s
5m

Do not assume fastest copying is optimal.

Some wallets may exhibit:

leader buys
followers cause spike
temporary retracement
sustained move

The system must be capable of discovering that a delayed follower entry is superior.

⸻

51. FORWARD INFORMATION VALUE

Primary conceptual question:

After ARGUS first observed the wallet act, how much abnormal return remained?

Measure from:

ARGUS first_seen_at

not the wallet's original execution timestamp.

Where data allows, evaluate:

5s
15s
30s
1m
5m
30m
1h
6h
24h

Prefer executable outcomes when possible.

A wallet with lower personal P&L but high remaining follower alpha may be more useful than a spectacular but uncopyable wallet.

⸻

52. POSITION-SIZE SURPRISE

Raw buy size is not enough.

Estimate for each wallet:

typical absolute size
typical portfolio-relative size where possible
recent median size
robust size dispersion

Calculate a robust relative-size surprise.

Example:

normal buy = 0.7 SOL
current buy = 6 SOL

may be highly informative.

Use robust statistics appropriate for heavy-tailed distributions.

⸻

53. TRADE READINESS SCORE v1

This evaluates the current opportunity, not the wallet.

Initial weighted inputs:

qualification score                     20%
copyability                             20%
remaining information at current delay 15%
liquidity/executable price impact       15%
price movement since leader             10%
relative position-size surprise         10%
independent confirmation                10%

Hard gates are applied BEFORE the score:

token safety
chain freshness
wallet eligibility
history quality
quote validity
risk caps

Initial MICRO-live trade-readiness threshold:

>= 90 / 100

This score is a V1 prior, not a proven statistical model.

Do not silently retune it.

⸻

54. EARLY MICRO-LIVE WALLET REQUIREMENTS v1

For a wallet-led MICRO live entry, require at minimum:

wallet tier = A or S
qualification score >= 85
qualification confidence >= configured acceptable level
history completeness not LOW/UNKNOWN
copyability score >= 75
no quarantine
no unresolved insider/common-control prohibition
trade readiness >= 90

Additionally require at least ONE corroborating condition:

second independent high-quality wallet confirmation
OR
exceptionally large relative position-size surprise
OR
validated high Convergence Surprise once available

Before advanced modules exist, the first two conditions are sufficient mechanisms.

No requirement may be relaxed automatically because no trades occur.

⸻

55. COUNTERFACTUAL ALPHA

Mandatory research question:

Did this wallet select something unusually good, or was the surrounding opportunity set also rising?

For each wallet entry, build a matched token set using only information available at entry:

timestamp
token age
market-cap bucket
liquidity bucket
recent momentum
volume
transaction rate
launch venue
broad market regime

Evaluate:

wallet token forward return
-
matched-universe forward return

Store:

residual_selection_alpha

at multiple horizons.

No future variable may enter matching.

⸻

56. ALPHA ANCESTRY

Construct directional wallet relationships.

For wallets A and B estimate:

P(B buys same/relevant token within T after A)

for:

5m
15m
30m
1h
6h
24h

Compare against B's normal/base probability.

Control for general token popularity.

Store directional edges:

A → B

with:

observations
conditional follow rate
baseline rate
lift
median lag
lag distribution
effect size
p-value
q-value
forward return after A
forward return after B
valid_from
graph_version

The goal is to identify wallets that lead wallets everybody else considers smart.

⸻

57. GRAPH MULTIPLE-COMPARISON CONTROL

Thousands of pairwise wallet tests will produce false discoveries.

Initial procedure:

Benjamini-Hochberg false-discovery-rate control

Do not call an edge meaningful simply because:

p < 0.05

before correction.

Require:

effect size
minimum observation count
q-value

All graph statistics are versioned.

⸻

58. UPSTREAM DISCOVERY

If unknown wallet Q repeatedly acts before elite wallet A with significant lift:

Q → A

Q becomes a discovery candidate even when Q's personal P&L is mediocre.

This is the mechanism for recursively finding information sources upstream.

⸻

59. CONVERGENCE SURPRISE

Raw wallet counts are insufficient.

Estimate:

How unusual is the observed joint behavior after accounting for normal overlap and dependence?

Persist underlying quantities first:

raw wallet count
estimated independent actors
expected overlap
observed overlap
empirical probability
surprisal
sample size
calibration confidence

Conceptually:

surprisal = -log(P(observed convergence | historical behavior))

Do NOT invent a 0–100 score until calibration is defined.

A display score may later be derived from an empirically calibrated percentile.

⸻

60. DOG-THAT-DIDN'T-BARK SIGNAL

Negative network evidence is mandatory research.

If:

R historically precedes A frequently
R buys token X
A does not appear within expected window

create:

EXPECTED_CONFIRMATION_ABSENT

Also support:

EXPECTED_CONFIRMATION_EARLY
EXPECTED_CONFIRMATION_LATE
EXPECTED_CONFIRMATION_STRONG

Test whether missing downstream confirmation predicts poor outcomes.

Do not assume it does.

⸻

61. PREDATION DETECTION

A profitable wallet may profit partly from its followers.

Research:

leader buy
→ follower influx
→ follower-driven price impact
→ leader distribution

Estimate:

follower influx
price impact
leader exit timing
repetition frequency

Create:

predation_score

High predation risk reduces copy eligibility.

It may still increase informational value of the wallet's exits.

⸻

62. ENTRY AND EXIT SPECIALISTS

Score entry and exit ability separately.

A wallet can be:

ENTRY_SKILL = 48
EXIT_SKILL = 96

and remain strategically useful.

Build separate research for:

entry specialists
discovery specialists
validation specialists
exit specialists

⸻

63. EXIT ORACLES

Identify wallets whose reductions frequently precede:

large drawdowns
liquidity collapse
sustained distribution

Build:

EXIT_CONVERGENCE

among independent exit specialists.

Do not require that the wallet originally sourced the position.

⸻

64. SYNTHETIC SUPER-WALLET

ARGUS must eventually support strategies that combine specialized actors.

Example:

R = discovers
A = confirms
K = provides conviction/size information
E = exits well

Conceptual strategy:

R enters
↓
starter position
A confirms
↓
increase exposure if validated
independent convergence strengthens
↓
increase within risk cap
E begins reducing
↓
trim
exit convergence becomes extreme
↓
close

This strategy is shadow-only until prospectively validated and explicitly approved.

⸻

65. ONE OPEN POSITION PER MINT DEFAULT

Initial live policy:

ALLOW_AUTOMATIC_SCALE_IN = false

Multiple wallet signals concerning the same token may increase confidence.

They MUST NOT automatically create additional buys.

Scale-in behavior requires a separately defined and validated strategy.

⸻

66. COPY-SELL LOGIC

Track leader position estimates.

When leader position confidence is HIGH:

leader_fraction_sold =
leader_quantity_sold /
leader_position_before_sale

ARGUS may shadow mirror the same percentage.

If leader position confidence is not HIGH:

do not blindly infer the fraction.

Instead create:

LEADER_EXIT_OBSERVED

for exit intelligence.

Live sell mirroring remains conservative.

⸻

67. INDEPENDENT RISK EXITS

ARGUS does not surrender risk control to a source wallet.

Risk architecture must independently support:

maximum position loss
liquidity collapse
token-risk-state change
maximum daily loss
maximum aggregate exposure
operator emergency exit

Exact capital limits are operator-defined.

⸻

68. TOKEN SAFETY GATE

Where technically available, evaluate deterministic hazards including:

mint authority
freeze authority
Token-2022 extensions
transfer fees
unsupported transfer behavior
supply concentration
extreme liquidity weakness
suspicious mutability

Store:

token_risk_flags
token_risk_version

Unknown dangerous token mechanics:

NO AUTO LIVE TRADE

until understood.

No safety screen is described as a guarantee.

⸻

69. PRE-ENTRY SELLABILITY PROBE

Where practical before live entry:

Request reverse-direction executability for a meaningful amount.

Store:

reverse_route_available
reverse_price_impact
reverse_quote_at

This does not guarantee future sellability.

It is an additional safety observation.

⸻

70. LIVE EXECUTION SECURITY MODEL

The coding agent MUST NEVER:

request a seed phrase
request a private key
display a private key
write a private key into repository
create a funded live wallet
fund a wallet
initiate the human canary
initiate a strategy mainnet trade

Only the isolated executor process may read signing key material.

Suggested host path:

/var/lib/argus/secrets/executor-keypair.json

The exact key remains human-controlled.

⸻

71. OS-LEVEL KEY ISOLATION

Before live operation, the implementation/coding agent must NOT run in a security context capable of reading the executor key.

Required concept:

dedicated executor OS/service identity
research process cannot read key
coding-agent user cannot read key
no sudo/root path from coding-agent user to key
no Docker socket access that defeats isolation

If the coding agent retains root-equivalent access to the key environment:

PRIVATE_KEY_ISOLATION = FAIL
LIVE = DISABLED

⸻

72. DATABASE PRIVILEGE SEPARATION

Create conceptual Postgres roles:

argus_ingest
argus_research
argus_executor

Use least privilege.

Examples:

* research must not rewrite confirmed execution history,
* executor must not rewrite historical wallet scores,
* ingestion must not have unnecessary execution permissions.

⸻

73. LIVE ARMING

Live execution requires an external human-controlled arm file outside repository.

Suggested path:

/var/lib/argus/live_arm.json

Conceptual fields:

{
  "armed": true,
  "expires_at": "...",
  "approved_git_commit": "...",
  "approved_executor_build_hash": "...",
  "approved_risk_config_hash": "...",
  "approved_strategy_versions": ["..."],
  "max_single_trade_sol": "...",
  "max_total_exposure_sol": "...",
  "max_daily_loss_sol": "..."
}

The implementation agent MUST NOT create or modify this file.

Missing, malformed, expired, or hash-mismatched arm file:

LIVE_EXECUTION = DISABLED

Fail closed.

⸻

74. DEFAULT CAPITAL CONFIGURATION

Repository defaults:

LIVE_MAX_SINGLE_TRADE_SOL = 0
LIVE_MAX_TOTAL_EXPOSURE_SOL = 0
LIVE_MAX_DAILY_LOSS_SOL = 0

Therefore no live trade can occur from default configuration.

Capital allocation remains a human decision.

Support staged risk multipliers:

MICRO   = 0.10
QUARTER = 0.25
HALF    = 0.50
NORMAL  = 1.00

The underlying NORMAL notional remains operator-defined.

⸻

75. EXECUTOR SINGLETON

Only one active live executor may control the strategy universe.

Use:

database advisory lock
or robust lease/fencing-token mechanism

If the lock cannot be obtained:

REFUSE LIVE START

If ownership is lost:

DISARM

Do not rely on Docker Compose replica count as the only protection.

⸻

76. EXECUTION STATE MACHINE

Every trade intent has:

intent_id
signal_id
strategy_version
token
side
created_at
idempotency_fingerprint

States:

CREATED
VALIDATING
REJECTED
ORDER_REQUESTED
ORDER_READY
ATTESTING
SIGNED
SUBMITTED
CONFIRMED
FAILED
UNKNOWN

Transitions are transactional and audited.

⸻

77. EXECUTION IDEMPOTENCY

Restart/replay must never execute the same intent twice.

Use database locking/unique idempotency fingerprint.

An ambiguous submitted transaction enters:

UNKNOWN

before any new attempt.

Never blind-retry.

⸻

78. TRANSACTION ATTESTATION BEFORE SIGNING

The executor must not sign a provider-supplied transaction merely because it came from Jupiter.

Before signing:

1. deserialize transaction,
2. verify expected signer,
3. verify executor wallet identity,
4. verify intended input mint,
5. verify intended output mint,
6. verify intended amount,
7. identify user-controlled asset outflows,
8. verify fees/tips/rent remain within approved limits,
9. simulate where technically possible,
10. inspect simulated balance changes,
11. reject unexplained account/authority behavior,
12. only then sign locally.

If interpretation is not sufficiently safe:

REJECT

⸻

79. ACTUAL FILL ACCOUNTING

Provider quote/response is not canonical fill accounting.

After confirmation, reconstruct actual chain balance deltas.

Persist:

quoted input/output
simulated input/output
actual input/output
network fee
priority fee
tip
rent/account costs

Confirmed chain state wins.

⸻

80. NO AUTOMATIC SLIPPAGE ESCALATION

If a trade fails because approved slippage is insufficient:

do not repeatedly raise slippage.

Any retry remains within operator-approved risk ceiling.

If execution cannot occur safely:

ABANDON

⸻

81. LIVE RISK VALIDATION

The executor independently rechecks:

software readiness
canary status
human arm validity
approved build/config hashes
wallet eligibility
signal freshness
token mint
token safety
minimum liquidity
price movement since leader
quote price impact
slippage
single-position limit
total exposure
daily loss
duplicate intent
conflicting position
scale-in prohibition
wallet balance
quote freshness
chain freshness
clock health
stream/reconciliation health

Any failure:

REJECT

with reason codes.

⸻

82. MAINNET CANARY

Software readiness alone is insufficient.

Phase 6 finishes:

LIVE_READY_SOFTWARE = true
LIVE_CANARY_PASSED = false
LIVE_ARMED = false

Before any strategy live trade, the human/orchestrator must explicitly authorize a tiny mainnet canary using a highly liquid route.

Purpose:

verify key access
signing
attestation
simulation
submission
confirmation
chain reconciliation
balance accounting
restart-safe state

The implementation agent may prepare the command/runbook.

It may NOT initiate the canary without explicit authorization.

After successful audited reconciliation:

LIVE_CANARY_PASSED = true

⸻

83. HOST SUSPEND / RESUME

If the host sleeps, hibernates, pauses, or exhibits major scheduling discontinuity:

AUTO-DISARM NEW ENTRIES

On resume:

1. verify clock,
2. reconnect streams,
3. reconcile tracked-wallet watermarks,
4. reconcile live positions,
5. verify executor wallet balance,
6. verify provider health,
7. verify open orders/intents.

Only after healthy reconciliation may live entry resume.

⸻

84. RESTART / CRASH ACCEPTANCE TESTS

Explicitly test:

kill collector during ingest
restart → no duplicate canonical event
disconnect stream
miss event
reconnect → recover event exactly once
kill shadow worker mid-job
restart → no duplicate shadow trade
kill executor after submit
restart → reconcile, do not double-buy
lose DB connection
recover safely
simulate host time discontinuity
new entries disable

These are required tests.

⸻

85. RESEARCH HYPOTHESIS STATES

Every nontrivial feature/strategy moves through:

IDEA
EXPLORATORY
FROZEN_PROSPECTIVE
VALIDATED
REJECTED
RETIRED

Only validated/explicitly approved strategy logic may eventually affect meaningful live capital.

MICRO early trading uses the explicitly defined V1 rules and is treated as continued validation.

⸻

86. HYPOTHESIS REGISTRY

Before prospective validation create:

hypothesis_id
feature definition
universe
primary target
primary horizon
expected direction
minimum sample
success criterion
failure criterion
freeze timestamp
git commit
config hash

Changing the feature creates a new version.

Do not silently retune a failed prospective test.

⸻

87. RESEARCH EXPERIMENT RECORD

Every experiment stores:

experiment_id
hypothesis
created_at
universe
features
target
train period
validation period
test period
cost assumptions
code commit
config hash
result
decision

Experiments are append-only records.

⸻

88. TEMPORAL VALIDATION

Never use random train/test splitting when overlapping forward-return windows could leak information.

Use:

strict temporal splits
purging
embargo where appropriate

Future models must respect time.

⸻

89. OUTCOME TRACKING

Every signal, not merely executed trades, receives outcomes.

Mark outcomes where data exists:

5m
30m
1h
6h
24h
3d
7d

Track:

MFE
MAE

at useful horizons.

Executable outcomes are tracked separately.

Missing data:

NULL + explicit reason

Never silently forward-fill.

⸻

90. REGIME FEATURES

Capture from Day 1 where practical:

SOL return 1h
SOL return 24h
broad DEX activity proxy
new-token launch activity
market-wide volume proxy
token liquidity regime
UTC time of day
day of week

These enable later questions such as:

Does wallet X possess alpha only in particular regimes?

⸻

91. FUTURE PREDICTIVE MODEL

Ultimate target:

P(elite wallet A buys token X within next N minutes)

Potential horizons:

5m
15m
30m
1h

Potential features:

upstream wallet activity
Alpha-Ancestry graph
token state
relative position sizes
previous confirmations
wallet recent behavior
liquidity trajectory
regime

Do not train this early.

When sample becomes adequate, start with:

logistic regression
regularized linear models
gradient-boosted trees

Complex models/neural networks are allowed only if simpler baselines are convincingly beaten out of sample.

⸻

92. PREDICTIVE ORDER-FLOW ENDGAME

The conceptual evolution is:

R buys
↓
A buys
↓
ARGUS buys

eventually becoming:

R buys
ARGUS model:
P(A buys soon) = high
P(B buys soon) = high
↓
ARGUS enters before A/B
↓
A arrives
↓
B arrives

This is behavioral prediction of informed flow.

It is NOT transaction front-running.

⸻

93. DAILY REPORT

Implement:

argus report daily

Report:

SYSTEM

uptime
errors
provider health
provider use

DISCOVERY

new tokens
new wallets
promotions
demotions
quarantines

TRACKING

tracked wallets
wallet trades
stream gaps
reconciliation

SIGNALS

signals
confirmations
convergence events

SHADOW

trades
matured executable outcomes
MFE/MAE

LIVE

ready state
canary state
armed state
orders
fills
PnL
risk events
rejections

RESEARCH

sample counts
hypothesis changes
notable anomalies

DATA QUALITY

ambiguous swaps
missing observations
low-completeness wallets
provider gaps

Avoid causal language in automated reports.

⸻

94. TELEGRAM

Telegram is notification-only initially.

Notify for:

system failure
provider budget warning
wallet promotion/quarantine
high-value signal
shadow event
live order submitted
live order confirmed
live order rejected
risk kill switch
position exit
daily summary

Telegram MUST NOT initially:

arm live trading
modify risk
send arbitrary transactions

Never send secrets.

⸻

95. HEALTH COMMAND

Implement:

argus health

Example:

Postgres: OK
Helius RPC: OK
Live stream: OK
Reconciliation: OK
DexScreener: OK
GeckoTerminal: OK
Jupiter: OK
Tracked wallets: 42
Degraded wallets: 0
Last chain slot:
Last wallet event:
Last reconciliation:
Clock: OK
Provider budget: OK
LIVE_READY_SOFTWARE: false
LIVE_CANARY_PASSED: false
LIVE_ARMED: false

⸻

96. STORAGE REPORT

Implement:

argus storage report

Report:

Postgres size
raw data size
Parquet size
cache size
logs size
total
estimated growth/day

No automatic deletion of evidence required for research reproducibility.

Temporary caches may use TTL.

⸻

97. BACKUPS

Implement:

make backup

Back up:

Postgres
critical Parquet
configuration metadata

Do NOT include signing key.

Provide tested restoration instructions.

Before significant migrations after Phase 3, create a backup or equivalent migration-safe snapshot.

⸻

98. VERSION EVERYTHING

At minimum:

parser_version
winner_definition_version
wallet_score_version
copyability_version
cluster_version
graph_version
counterfactual_version
signal_version
risk_version
strategy_version
model_version
config_hash
git_commit
schema_version

A live fill must be traceable to exact code and configuration.

⸻

99. AUTOMATED SANITY CHECKS

SANITY-001 — Time travel

If:

feature timestamp > decision timestamp

FAIL.

SANITY-002 — Future score leakage

A signal may not use a score snapshot created later.

FAIL.

SANITY-003 — Discovery contamination

Qualification score may not include triggering discovery token/event.

FAIL.

SANITY-004 — Duplicate canonical events

Duplicate ingest must resolve idempotently.

SANITY-005 — Impossible position

Materially negative quantity:

FAIL.

SANITY-006 — Wrong live mint

Signal mint and order mint mismatch:

FAIL.

SANITY-007 — Stale signal

Reject live entry.

SANITY-008 — Missing config/version

Live action or signal missing required versions:

FAIL.

SANITY-009 — Stream gap

Unreconciled chain gap:

REJECT NEW LIVE ENTRY.

SANITY-010 — Clock anomaly

Unhealthy time state:

REJECT NEW LIVE ENTRY.

SANITY-011 — Build mismatch

Executor build/config differs from approved arm values:

DISARM.

⸻

100. TEST PHILOSOPHY

Prioritize financial/data correctness over cosmetic line coverage.

Highest-value tests:

1. transaction balance-delta parsing,
2. temporal correctness,
3. discovery-exclusion correctness,
4. position accounting,
5. deduplication,
6. score versioning,
7. signal reproduction,
8. stream reconciliation,
9. provider-priority behavior,
10. risk rejection,
11. execution idempotency,
12. transaction attestation,
13. crash recovery,
14. secret isolation.

Target:

overall coverage >= 80%
risk/executor modules >= 95% where practical

Do not write meaningless tests merely to inflate coverage.

⸻

101. NO BACKTEST THEATER

Explicitly prohibited:

discover wallet from winner then count same winner as qualification evidence
use future wallet tier for old signal
use future token supply for historical market cap
select only surviving tokens
ignore untradeable exits
assume zero slippage
assume leader execution price was available to follower
drop failed transactions
optimize final thresholds directly on held-out test data
randomly split overlapping temporal labels
retune a failed frozen prospective hypothesis and pretend it is the same test

⸻

102. THINGS NOT TO BUILD

Until explicitly requested:

React frontend
mobile app
Kubernetes
Kafka
microservices
paid-data dependency
social-media sentiment engine
runtime LLM trader
neural network
Ethereum support
multi-chain support
leverage
perpetual futures
NFT trading
multi-user SaaS
complex authentication

Stay focused.

⸻

103. PHASE EXECUTION RULE

Work sequentially.

Every phase has:

BUILD
TEST
ACCEPTANCE
CHECKPOINT
STOP

Do not begin the next phase until explicit orchestrator approval.

⸻

PHASE 0 — FOUNDATION

Goal

Create a reproducible, testable repository and infrastructure foundation.

Build

Implement:

repository structure
MASTER_SPEC.md
docs/ARCHITECTURE.md
docs/BUILD_STATE.md
docs/DECISION_LOG.md
uv environment
Docker Compose
Postgres
Alembic
configuration loader
configuration hashing
spec hashing
structured logging
UTC/monotonic clock abstraction
CLI skeleton
FastAPI skeleton
health framework
provider-usage schema
database roles
checkpoint framework
Makefile

Required commands:

make bootstrap
make up
make test
make lint
argus health

Acceptance

[P/F] fresh repo bootstrap works
[P/F] Postgres starts
[P/F] migration from zero works
[P/F] tests run
[P/F] Ruff runs
[P/F] mypy runs
[P/F] config hash generated
[P/F] MASTER_SPEC hash generated
[P/F] DB roles exist
[P/F] no secrets committed
[P/F] runtime directories ignored
[P/F] BUILD_STATE works

Commit

Suggested:

phase0: scaffold ARGUS architecture and infrastructure

STOP

Produce Phase 0 checkpoint.

Do NOT begin Phase 1.

⸻

PHASE 1 — PROVIDERS, IMMUTABLE INGESTION, LIVE RECONCILIATION

Goal

Prove reliable acquisition and canonical parsing of live chain data.

Build

Implement:

Helius/Solana RPC adapter
standard WebSocket adapter
reconnect handling
per-wallet subscriptions
persistent watermarks
deterministic reconciliation
stream-gap detection
provider probes
provider usage accounting
streaming accounting
DexScreener adapter
GeckoTerminal adapter
Jupiter order/quote adapter WITHOUT signing
central request priority scheduler
chain_events
transaction fetching
generic swap parser
golden fixtures

Required reconciliation test

Simulate:

stream connected
↓
event A observed
↓
disconnect
↓
event B occurs while disconnected
↓
reconnect
↓
reconciliation discovers B

Final canonical ledger:

A exactly once
B exactly once

Required parser fixtures

SOL → token
token → SOL
token → USDC
multi-hop
transfer
partial sell
ambiguous transaction

Acceptance

[P/F] RPC works
[P/F] WSS works
[P/F] disconnect detected
[P/F] reconnect works
[P/F] reconciliation recovers missed event
[P/F] no duplicate canonical event
[P/F] watermarks persist across restart
[P/F] commitment status stored
[P/F] clock health stored
[P/F] provider priority scheduler tested
[P/F] streaming usage counted
[P/F] parser fixtures pass
[P/F] ambiguous transaction cannot create live-copy signal
[P/F] no signing/private-key functionality

STOP

Checkpoint Phase 1.

⸻

PHASE 1.5 — HISTORICAL DATA FEASIBILITY SPIKE

Goal

Prove that the free-first data architecture can reconstruct the historical evidence ARGUS needs before large-scale archaeology is built.

Inputs

Use:

1 verified historical token
1 verified candidate wallet

If these cannot be established automatically, output:

BOOTSTRAP_TOKEN_INPUT_REQUIRED

and stop for orchestrator input.

Test A — Early buyers

Attempt to recover early meaningful buyers.

Report:

provider/source
venue
time range
transactions inspected
buyers recovered
earliest recovered activity
known gaps
estimated completeness

Test B — Wallet history

Attempt to reconstruct:

wallet-level signatures
token-account activity
swaps
transfers
position events
ambiguous events

Test C — Cross validation

Validate at least 20 interpretations against raw transaction evidence or an independent source.

Test D — Cost

Report:

RPC calls
provider credits
archive bytes
BigQuery bytes if used
elapsed processing time
disk usage

Estimate scaling to:

100 wallets
1,000 wallets

Required conclusion

Exactly one:

HISTORICAL_DATA_PATH = PASS
HISTORICAL_DATA_PATH = PASS_WITH_LIMITATIONS
HISTORICAL_DATA_PATH = FAIL

If FAIL:

STOP.

Do not fake completeness.

STOP

Checkpoint Phase 1.5.

⸻

PHASE 2 — TOKEN + WALLET DISCOVERY

Goal

Create historical and prospective candidate-wallet discovery.

Build

token model
market snapshots
reference prices
token lifecycle metadata
bootstrap-token importer
historical provider adapters
early-buyer extraction
wallet discovery provenance
prospective winner watcher
winner milestone events
automatic archaeology trigger
wallet candidate creation
negative-control schema support
on-chain mint validation

Demonstration

At least one verified historical token.

Report:

mint
winner category
baseline methodology
early buyers recovered
data source
history limitations
sample sanitized rows

Acceptance

[P/F] token mint validated
[P/F] lifecycle stage persisted
[P/F] discovery provenance persisted
[P/F] at least one historical archaeology run works
[P/F] early-wallet extraction reproducible
[P/F] source limitations explicit
[P/F] discovery-trigger observations identifiable for later exclusion

STOP

Checkpoint Phase 2.

⸻

PHASE 3 — WALLET RECONSTRUCTION + UNBIASED QUALIFICATION

Goal

Reconstruct candidate histories and score them without using discovery evidence to justify their own selection.

Build

wallet history reconstruction
history completeness
position ledger
round-trip derivation
position confidence
wallet metrics
descriptive score
qualification score
discovery exclusion
lottery dominance
recency decay
initial clustering
tier lifecycle

Critical automated test

Create a fixture where:

TOKEN_A discovers wallet W
TOKEN_A is huge winner

Verify:

TOKEN_A affects descriptive score
TOKEN_A does NOT affect qualification score

FAIL phase if this leaks.

Sample report

At least five candidate wallets:

usable trades
history completeness
discovery-trigger tokens
excluded observations
descriptive score
qualification score
selection skill
entry skill
exit skill
consistency
risk metrics
penalties
tier

Acceptance

[P/F] discovery contamination excluded
[P/F] descriptive/qualification scores differ where expected
[P/F] weighted-average ledger correct
[P/F] transfer uncertainty handled
[P/F] Decimal/raw-unit accounting correct
[P/F] history completeness affects confidence
[P/F] tier transitions timestamped
[P/F] small samples shrunk/constrained

STOP

Checkpoint Phase 3.

⸻

PHASE 4 — PROSPECTIVE MONITORING + SHADOW COPYING

Goal

Begin collecting truly point-in-time follower data.

Build

tracked-wallet live monitoring
confirmation handling
observation-latency metrics
shadow intent creation
scheduled quote probes
shadow positions
reverse exit quotes
mark outcomes
executable outcomes
Telegram notifications
daily report

Required lifecycle demonstration

Show one complete real or REPLAY event:

leader executes
ARGUS observes
source tx confirms
shadow signal created
entry quote obtained
shadow fill recorded
mark outcome recorded
reverse executable quote recorded

If using replay:

label it prominently:

REPLAY — NOT PROSPECTIVE ALPHA EVIDENCE

Acceptance

[P/F] observation timestamp frozen
[P/F] point-in-time score frozen
[P/F] quote actual latency recorded
[P/F] executable return distinct from mark return
[P/F] unsellable state preserved
[P/F] provider-capacity miss preserved as missing data
[P/F] stream gaps block eligible live state

STOP

Checkpoint Phase 4.

⸻

PHASE 5 — COPYABILITY + FORWARD INFORMATION VALUE

Goal

Measure whether profitable wallet activity remains profitable to a follower.

Build

delay-response curves
information half-life
copyability score
copyability confidence
forward information value
relative position-size surprise
trade-readiness score
prospective-vs-historical separation

Report

For tracked wallets where sample exists:

wallet
qualification score
leader result
follower +1s
follower +5s
follower +15s
follower +30s
follower +60s
executable outcomes
copyability
information value
sample size
confidence

Do not manufacture precision.

Acceptance

[P/F] follower outcomes start at ARGUS observation
[P/F] executable outcomes used where available
[P/F] information half-life computed reproducibly
[P/F] low sample produces low confidence
[P/F] trade readiness uses versioned V1 formula

STOP

Checkpoint Phase 5.

⸻

PHASE 6 — HARDENED ISOLATED EXECUTOR

Goal

Become technically live-ready without permitting the coding agent to trade.

Build

separate executor process
DB privilege separation
executor singleton/fencing
Jupiter order construction
local signing interface
transaction attestation
simulation
human arm-file verification
build/config hash pinning
risk engine
idempotency
submission state machine
crash reconciliation
actual fill reconstruction
live position ledger
sell handling
kill switches
host suspend/resume safety

Testing

Use:

mocks
unsigned transactions
simulation
safe test mechanisms

The implementation agent SHALL NOT make a mainnet trade.

Mandatory acceptance

[P/F] executor singleton
[P/F] wrong build hash fails closed
[P/F] wrong risk config fails closed
[P/F] expired arm fails closed
[P/F] malformed arm fails closed
[P/F] default zero risk caps prevent trade
[P/F] research process cannot read signing key
[P/F] coding-agent context cannot read signing key
[P/F] transaction attestation failure rejects
[P/F] simulation failure rejects
[P/F] wrong mint rejects
[P/F] unexpected outflow rejects
[P/F] stale signal rejects
[P/F] excessive price impact rejects
[P/F] chain freshness failure rejects
[P/F] unreconciled stream gap rejects
[P/F] clock anomaly rejects
[P/F] scale-in disabled by default
[P/F] ambiguous submission does not blind-retry
[P/F] crash after submission reconciles
[P/F] actual fill reconstructed from chain
[P/F] emergency kill switch works

Required final state

LIVE_READY_SOFTWARE = true
LIVE_CANARY_PASSED = false
LIVE_ARMED = false

STOP

Checkpoint Phase 6.

⸻

PHASE 6.5 — HUMAN-AUTHORIZED MAINNET CANARY

This is NOT automatically performed by the coding agent.

The orchestrator/human explicitly authorizes it.

The implementation agent may provide exact operational commands.

Canary must verify:

key isolation
transaction attestation
simulation
signing
broadcast
confirmation
balance reconciliation
fill accounting
state-machine completion

After success:

LIVE_CANARY_PASSED = true

Only after explicit human live arming may a qualifying strategy signal execute.

⸻

PHASE 7 — ALPHA ANCESTRY

Goal

Find wallets that lead other skilled wallets.

Build

lead/follow observations
directional graph
base-rate correction
lag distributions
effect sizes
multiple-comparison correction
upstream candidate generation

Report

top directional edges
observation counts
lift
median lag
effect size
p-value
q-value
forward information after leader
upstream candidate wallets

No unsupported causal claims.

STOP

Checkpoint Phase 7.

⸻

PHASE 8 — CONVERGENCE + NEGATIVE EVIDENCE

Build

effective independent-actor count
expected overlap
empirical overlap probabilities
surprisal
calibration
expected-confirmation windows
dog-that-didn't-bark events

Compare outcomes for:

ordinary overlap
high-surprisal overlap
rapid confirmation
failed confirmation

Do not convert to arbitrary 0–100 scores until calibrated.

STOP

Checkpoint Phase 8.

⸻

PHASE 9 — COUNTERFACTUAL ALPHA + SPECIALISTS

Build

matched-token controls
residual selection alpha
entry-specialist metrics
discovery-specialist metrics
exit-specialist metrics
predation score
exit convergence

Key question:

Do supposed smart wallets outperform comparable opportunities that existed at the same time?

STOP

Checkpoint Phase 9.

⸻

PHASE 10 — SYNTHETIC SUPER-WALLET

Shadow only unless later approved.

Build prospective strategies:

A: source entry → source exit
B: discovery specialist → source exit
C: discovery → confirmation → source exit
D: discovery → confirmation → exit oracle
E: high convergence → exit convergence

Compare:

executable return
drawdown
win rate
profit factor
capital utilization
failure rate

after realistic costs.

Do not enable the winner live automatically.

STOP

Checkpoint Phase 10.

⸻

PHASE 11 — PREDICT INFORMED ORDER FLOW

Only begin with adequate clean prospective sample.

Targets:

P(elite wallet enters token within 5m)
P(elite wallet enters within 15m)
P(elite wallet enters within 30m)
P(elite wallet enters within 1h)

Baselines:

random/base rate
token momentum only
wallet history only
graph + token state

Models:

logistic regression
regularized models
gradient-boosted trees

Use strict temporal validation.

Do not build a neural network until simpler models are convincingly beaten out of sample.

STOP

Checkpoint Phase 11.

⸻

104. STANDARD ORCHESTRATOR CHECKPOINT

At the end of EVERY phase:

STOP and output exactly one report beginning:

================ ARGUS ORCHESTRATOR CHECKPOINT ================

and ending:

================ END ARGUS CHECKPOINT =========================

Include:

A. Identity

PROJECT:
MASTER_SPEC_VERSION:
MASTER_SPEC_HASH:
PHASE:
STATUS: PASS / PARTIAL / FAIL
UTC_TIMESTAMP:
GIT_COMMIT:
CONFIG_HASH:
SCHEMA_VERSION:

B. What was built

Concise.

C. Files changed

Include:

git diff --stat <last-approved-commit>..HEAD
git diff --name-status <last-approved-commit>..HEAD

D. Commands actually run

Exact commands.

Never claim an unrun test.

E. Test results

pytest:
passed:
failed:
skipped:
coverage:
ruff:
mypy:

F. Acceptance criteria

Every criterion marked:

PASS
FAIL
NOT TESTED

G. Database/data sanity

Relevant counts.

H. Provider usage

HTTP
streaming
Jupiter
historical
projected free-tier use

I. Data quality warnings

Explicit.

J. Sample outputs

Small sanitized examples.

K. Architectural deviations

Must say:

NONE

or list each deviation.

Unapproved material deviation means:

STATUS = PARTIAL

L. ORCHESTRATOR_REVIEW_REQUIRED

Must say:

NONE

unless genuinely necessary.

Do not put trivial decisions here.

M. Known bugs / debt

Explicit.

N. Security state

Where relevant:

secret scan
key isolation
live readiness
canary
arming

O. Next specified phase

State it.

DO NOT BEGIN IT.

⸻

105. ORCHESTRATOR REVIEW BUNDLE

Implement:

argus checkpoint bundle --phase <N>

Create:

runtime/reports/orchestrator_bundle_phase_<N>.txt

Include:

checkpoint
git status --porcelain
git log -5 --oneline
diff stat
diff name-status
repository tree
dependency summary
Compose service summary
Alembic head
DB counts
provider usage
test summary
coverage
Ruff/mypy
MASTER_SPEC hash
BUILD_STATE
DECISION_LOG changes

High-risk phases additionally include concise relevant code excerpts.

Phase 1:

event model
parser interface
reconciliation logic

Phase 3:

discovery exclusion
score calculation

Phase 4/5:

shadow fill
executable-return calculation

Phase 6:

risk engine
state machine
idempotency
transaction attestation
secret isolation

Never include credentials or key material.

⸻

106. CLEAN SOURCE REQUIREMENT

A PASS checkpoint should have:

git status --porcelain

clean.

Uncommitted source changes cause:

PARTIAL

unless explicitly justified.

⸻

107. AGENT FAILURE BEHAVIOR

If something fails:

Do not hide it.

Do not continue through the phase gate.

Preferred checkpoint:

STATUS: PARTIAL
Completed:
...
Failure:
...
Evidence:
...
Likely cause:
...
Attempted fixes:
...
ORCHESTRATOR_REVIEW_REQUIRED:
...

Then STOP.

⸻

108. CREDENTIAL HANDLING

When a credential is needed, output only:

LOCAL CREDENTIAL REQUIRED:
<NAME>
Place it locally at/in:
<location>
DO NOT paste its value into chat.

.env.example contains empty placeholders only.

Never dump environment variables into checkpoints.

⸻

109. CHANGE CONTROL

Maintain:

docs/DECISION_LOG.md

For every orchestrator-approved material change:

date
requirement ID/section
decision
reason
requested by
impact
git commit

Do not silently edit MASTER_SPEC.md.

If a future canonical v3 is created, it explicitly supersedes v2.

⸻

110. SUCCESS — FIRST FIVE DAYS

Success is NOT positive P&L.

Success means:

Data

chain observations persisted
stream + reconciliation functioning
wallets discovered
point-in-time scoring functioning
market/executable outcomes captured

Research

historical reconstruction proven
prospective monitoring running
shadow copying running
copyability dataset accumulating

Engineering

restart safe
provider budgets controlled
audit trail complete
secret boundary hardened

Trading readiness

LIVE_READY_SOFTWARE = true
LIVE_CANARY_PASSED = true only after human canary
LIVE_ARMED = false until human arms

If a qualifying signal occurs after all gates:

MICRO live execution may occur.

⸻

111. SUCCESS — FIRST 30 DAYS

ARGUS should begin answering:

1. Do historically qualified wallets continue outperforming prospectively?
2. Does exploitable follower return remain after detection?
3. How fast does wallet information decay?
4. Are some wallets more profitable to copy after a delay?
5. Does wallet independence matter?
6. Does convergence surprise outperform raw wallet count?
7. Does relative position-size surprise add information?
8. Does failed expected confirmation predict worse outcomes?
9. Can upstream leaders be discovered?
10. Are exit specialists more useful than entry specialists?
11. Does copy profitability survive executable exit quotes?
12. How much historical apparent alpha disappears once discovery contamination is removed?

A negative result is valid progress.

⸻

112. LONG-TERM TARGET

ARGUS should eventually produce point-in-time reasoning approximately like:

TOKEN X
UPSTREAM
Wallet R entered 8m ago.
QUALIFICATION
R qualification score: 92
Copyability: 88
History quality: HIGH
ALPHA ANCESTRY
R → A lift: 3.1x
R → B lift: 2.4x
PREDICTED FLOW
P(A enters within 30m): 81%
P(B enters within 30m): 72%
CONVICTION
R current size: 4.2x its recent median.
INDEPENDENCE
Wallet Q also entered.
R/Q historical overlap is exceptionally rare.
Common-control probability low.
CONVERGENCE
Empirical convergence probability unusually low.
Calibration confidence adequate.
COPYABILITY
Executable alpha historically remains positive at current delay.
MARKET
Liquidity sufficient.
Reverse route available.
Price impact inside limits.
TRADE READINESS
93/100.
DECISION
MICRO-LIVE ELIGIBLE.
SUPPORT
upstream leader
size surprise
independent confirmation
remaining follower alpha
COUNTEREVIDENCE
no exit-oracle warning
no predation flag
no unresolved token-risk flag

Every value must be traceable to contemporaneous data.

⸻

113. FINAL RESEARCH PRINCIPLE

ARGUS must be capable of proving its favorite ideas wrong.

Possible valid conclusions include:

historical wallet alpha does not persist
copyability disappears after latency
convergence adds no information
Alpha Ancestry is explained by momentum
exit specialists are more useful than entry specialists
30-second delay beats immediate copying
all apparent profit disappears under executable exits

If evidence says an idea is dead:

kill it.

Do not rescue it by endless retuning.

⸻

114. FINAL ARCHITECTURE

                    HUMAN OPERATOR
                          │
            credentials / capital / arming
                          │
                          ▼
                  ARGUS ORCHESTRATOR
               architecture + research
                          │
                    phase approval
                          │
                          ▼
                IMPLEMENTATION AGENT
                 code + tests + CLI
                          │
                          ▼
                       ARGUS
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   DISCOVERY          RESEARCH            SHADOW
        │                 │                  │
        └─────────────────┼──────────────────┘
                          ▼
                       SIGNALS
                          │
                          ▼
                 ISOLATED RISK ENGINE
                          │
                          ▼
                 ISOLATED EXECUTOR
                          │
                          ▼
                       SOLANA
                          │
                          ▼
                 CONFIRMED OUTCOMES
                          │
                          └────────→ RESEARCH

⸻

115. FIRST INSTRUCTION TO IMPLEMENTATION AGENT

Upon receiving this file:

1. Save it verbatim as:

MASTER_SPEC.md

2. Read the entire file.
3. Create:

docs/ARCHITECTURE.md
docs/BUILD_STATE.md
docs/DECISION_LOG.md

4. In no more than five lines, acknowledge:

current phase = 0
architecture = modular monolith
live trading = disabled
next action = Phase 0 only
checkpoint required before Phase 1

5. Implement PHASE 0 ONLY.
6. Run all Phase 0 tests.
7. Commit Phase 0.
8. Generate:

ARGUS ORCHESTRATOR CHECKPOINT
+
orchestrator review bundle

9. STOP.

Do not begin Phase 1.

Do not ask broad design questions.

⸻

116. ABSOLUTE PROHIBITIONS

Until explicitly changed:

NO MAINNET STRATEGY TRADE BY CODING AGENT
NO HUMAN CANARY WITHOUT EXPLICIT AUTHORIZATION
NO PRIVATE-KEY ACCESS BY CODING AGENT
NO SEED-PHRASE ACCESS
NO PAID PROVIDER UPGRADE
NO AUTOMATIC THRESHOLD RELAXATION
NO FUTURE-DATA LEAKAGE
NO DISCOVERY-CONTAMINATION LEAKAGE
NO BLIND TRANSACTION RETRIES
NO AUTOMATIC SLIPPAGE ESCALATION
NO UNVALIDATED SCALE-IN
NO DELETION OF BAD OUTCOMES
NO CALLING MARK RETURN EXECUTABLE RETURN
NO ARCHITECTURAL REDESIGN
NO NEXT PHASE BEFORE ORCHESTRATOR APPROVAL

⸻

117. BEGIN

Implement Phase 0.

At completion, return the standardized Phase 0 orchestrator checkpoint and review bundle.

Then STOP.

END OF PROJECT ARGUS MASTER BUILD SPECIFICATION v2.0
