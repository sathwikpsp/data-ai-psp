# Usage contract v1

Each JSONL line or HTTP `events` element is one provider invocation. `request_id` must be globally unique; prefix it with provider/application identifiers or use a UUID. Reusing an ID for a different event is rejected.

```json
{
  "schema_version": "1",
  "request_id": "gateway:request-123",
  "timestamp": "2026-10-10T08:30:00Z",
  "provider": "demo-cloud",
  "model": "swift-small",
  "team": "support",
  "environment": "production",
  "input_tokens": 1000,
  "output_tokens": 100,
  "cached_input_tokens": 200,
  "latency_ms": 480,
  "status": "success"
}
```

| Field | Constraint / meaning |
| --- | --- |
| `schema_version` | Literal `"1"`; omitted values default to v1 |
| `request_id`, `provider`, `model`, `team` | 1–100 characters from letters, numbers, underscore, period, colon, hyphen |
| `timestamp` | Timezone required; normalized to UTC; 2020 onward; no more than five minutes in the future |
| `environment` | `production`, `staging`, or `development`; default production |
| `input_tokens`, `output_tokens` | Required strict integers in [0, 1 billion]; booleans and floats rejected |
| `cached_input_tokens` | Integer subset of `input_tokens`; default 0 |
| `latency_ms` | Required finite number in [0, 86,400,000] |
| `status` | `success` or `error`; default success |

Any extra field rejects the record, including prompts, completions, secrets, arbitrary tags, or labels. Identifiers still may be sensitive: use pseudonymous team/request IDs where necessary. All environments are aggregated together in this version; use separate warehouses for separate environments when that distinction matters.

## Pricing

All amounts use USD per million tokens. For one request:

`micro-USD = round_half_up((input - cached) × input_rate + cached × cached_rate + output × output_rate)`

The example above is `800 × 0.4 + 200 × 0.1 + 100 × 1.6 = 500 micro-USD`, or $0.0005, under the demo card. Failed requests with tokens are still priced. Cost per successful request divides **all** request costs by successful request count; it is null when there are no successes.

Rate validity is `[valid_from, valid_to)` in UTC. Windows for a provider/model cannot overlap. Rate numbers must be finite and nonnegative; only USD is accepted. See [`rates.json`](../src/tokenledger/assets/rates.json). Replace the entire document and version for real usage. Capture the vendor/source and verification date in its description. Existing records retain their original valuation; replaying them after a rate change does not reprice them.

These are token-cost estimates. Discounts, batch fees, cache-write fees, tool charges, GPU rental, taxes, credits, currencies other than USD, and invoice adjustments are outside the contract. Reconcile to vendor invoices before using estimates as accounting records. This schema is not claimed to be FOCUS-compliant.

## Ingestion and failures

`POST /api/v1/events` accepts `{"events": [...]}` with 1–5,000 records and a maximum 2 MB request body. It requires the configured bearer token, even in demo mode. Responses report counts and the first 50 issue summaries; all issue reasons are retained in the warehouse.

| Reason | Meaning / recovery |
| --- | --- |
| `invalid_contract` | Correct the schema, timezone, counter, or unexpected field and resend |
| `unpriced_model_or_date` | Add an appropriate rate under a new version, restart, and resend |
| `conflicting_request_id` | Investigate the producer; this version has no automatic correction/reversal pathway |

Valid rows and all batch audit records commit together. Bad individual rows do not prevent unrelated valid rows from being accepted. Database failures roll back the whole batch. JSON parse errors or request-envelope validation errors prevent ingestion. CLI ingestion commits bounded batches incrementally: if a later line is malformed, earlier batches remain committed. Fix the line and replay safely. There is no automatic deletion, invoice correction, or dead-letter payload retention.
