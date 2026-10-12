# Architecture and decisions

## Request-to-insight path

1. A trusted gateway/exporter emits metadata-only usage records with globally unique `request_id` values. A record represents one provider invocation, including failed invocations that consumed tokens.
2. Pydantic validates schema version, identifiers, timestamps, counters, latency, and cache relationships. Unknown fields are rejected so prompts and completions cannot accidentally enter bronze.
3. UTC-normalized canonical JSON is hashed. The same ID and payload is an exact replay; a changed payload under an existing ID is a conflict. Both are audited without changing prior charges.
4. An effective-dated price is selected. Unknown models or dates are rejected rather than priced at zero. Accepted metadata, charges, and batch counters commit in one DuckDB transaction.
5. The `daily_usage` SQL view aggregates by UTC day and team. ML excludes today's incomplete day. Late arrivals update the view and the dataset fingerprint; the next report recomputes models.
6. A snapshot lock makes every report internally consistent. The API caches report calculations for at most 60 seconds and invalidates after ingestion, including rejected-only batches.
7. The UI displays the actual cost window and dataset lineage. The evidence assistant chooses one of four supported intents and returns referenced facts. It has no SQL generator, shell, network tools, or action executor.

## Why this stack

| Decision | Reason | Tradeoff |
| --- | --- | --- |
| Embedded DuckDB | Reproducible SQL analytics without paid infrastructure | One process owns the file; not a concurrent distributed writer |
| Integer micro-USD | Auditable per-request rounding without binary-float accumulation | Sub-micro-USD precision is rounded half-up; not an invoicing system |
| Explicit rate-card versions | Historical estimates remain reproducible | Changing a price requires a new version; no retroactive repricing command |
| Isolation Forest + materiality | Uses multiple usage signals while suppressing low-value alerts | Thresholds and contamination are defaults, not business-calibrated |
| Seasonal model challenger | Tests whether a regression adds value over a simple baseline | Limited history and no external demand regressors |
| Local evidence router | Traceable, offline, deterministic answers | Limited intents; no general-purpose conversational understanding |
| Vanilla web UI | No frontend build service, CDN, or API key needed | Application state and charting are deliberately small |
| Hashed dependency lock | Repeatable package resolution | Base container tags need periodic refresh and security review |

## Storage and lineage

`rate_cards` archives every price document under an immutable version. `bronze_events` retains canonical accepted metadata and its SHA-256. `usage_events` references the rate version and ingestion batch. `ingestion_batches` records accepted/duplicate/rejected counters. `quality_issues` stores only batch, row, and reason; rejected contents are not retained. All tables are in one DuckDB database for transaction consistency.

The dataset fingerprint hashes ordered IDs, canonical payload hashes, rate versions, and integer charges. It deliberately excludes volatile ingestion timestamps. The model version, split dates, and metrics appear in exported reports. Models are fit in process from the priced snapshot; no untrusted pickle/joblib files are loaded.

## Current limits and scale path

Each ingestion batch scans stored event IDs to check replays. Fingerprinting also scans the dataset, and the process lock serializes ingestion and report reads. This is suitable for this reference project, not a demonstrated million-event service. No throughput or uptime claim has been benchmarked.

For larger workloads: land immutable batches in object storage with retention policies, use a durable queue and consumer checkpoints, enforce unique event keys in a transactional store, materialize partitioned aggregates, and run model jobs separately. An API database and object store should replace the shared embedded file before adding replicas. A tenant key must be enforced across data, auth, and caches before accepting multiple customers. None of those components are represented as already implemented.

Request payload limits do not replace an edge rate limiter. Schedule jobs in an orchestrator only after defining expected arrival times, missing-data semantics, correction policy, and owner-specific alert thresholds. This repository supplies a reproducible batch CLI and CI workflow rather than an always-running scheduled ingestion service.
