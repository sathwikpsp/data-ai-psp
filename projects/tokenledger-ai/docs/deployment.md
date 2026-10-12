# Deployment and operations

## Local demonstration

Run the README's `uv` commands or `docker compose up --build`. The container creates synthetic data only when `TOKENLEDGER_BOOTSTRAP_DEMO=true` and the warehouse is empty. Re-running `tokenledger demo` is safe for the same fixture: requests become audited duplicates. `tokenledger serve` does not bootstrap unless explicitly configured.

The service listens at port 8000. Compose publishes it only on loopback and persists the database in `tokenledger-data`. The image runs as UID/GID 10001 with a read-only root filesystem, dropped capabilities, and a writable data volume. Use exactly one worker and one replica per database file. Do not open the same writable DuckDB file from a running API and a separate CLI process; stop the service before CLI ingestion, evaluation, or backup, or use HTTP ingestion while it is running.

## Real usage

1. Use a separate empty directory/volume; never mix the synthetic demo with your real data.
2. Configure `TOKENLEDGER_MODE=production`, `TOKENLEDGER_BOOTSTRAP_DEMO=false`, and a random `TOKENLEDGER_API_KEY` of at least 32 characters through your deployment secret manager. The service refuses production startup without a sufficiently long key.
3. Mount your versioned rate card read-only and set `TOKENLEDGER_RATE_CARD` to its container path. The sample Compose file can be extended with `./config/rates.json:/config/rates.json:ro` and this environment variable. It otherwise uses the explicitly synthetic bundled card.
4. Persist `/data` with ownership suitable for UID 10001. Restrict access to the volume and backups.
5. Put a TLS reverse proxy with request timeouts, connection limits, body limits, and rate limiting in front. Keep the API on a private network where possible. The built-in bearer token is single-tenant authentication, not SSO or user-level authorization.
6. Send normalized events using `Authorization: Bearer <token>`. API reads, explanations, and metrics use the same token. The dashboard asks for it and keeps it only in tab memory. Tokens are not placed in URLs or local storage.

Production mode disables the interactive API documentation. Public `/healthz` and `/readyz` expose only service state. Root/static assets are public shells; usage data still requires authentication. No billing provider connection or paid hosting account is provisioned by this repository.

## Endpoints

| Endpoint | Purpose | Authentication |
| --- | --- | --- |
| `GET /healthz` | Liveness | None |
| `GET /readyz` | Database readiness | None |
| `GET /api/v1/report` | Snapshot, allocation, quality, ML output | Required when key is configured |
| `POST /api/v1/events` | Bounded normalized usage ingestion | Always requires a configured key |
| `POST /api/v1/explain` | Supported question → evidence | Required when key is configured |
| `GET /metrics` | Events, cumulative rejected records, total estimated cost | Required when key is configured |

Readiness does not promise fresh data or a trained model. Report `freshness` becomes `stale` when the newest event is more than 48 hours old. It is evaluated against actual wall-clock UTC; historical demo snapshots will eventually be stale by design. Structured application logs contain method, status, duration, and generated request ID, without bodies or tokens. No metric labels expose teams or request IDs.

## Backups and recovery

Stop the service cleanly, copy the entire data directory to protected backup storage, and restart. Do not copy an actively written DuckDB file. Restore into an empty volume with matching ownership, then confirm readiness, accepted event count, total cost, and dataset fingerprint against your previous report. Test restores regularly. No automated backup service is installed.

For a bad deployment, stop the application and use the prior source commit/container plus the last validated backup. Schema v1 uses additive create-if-absent initialization and has no destructive migrations. Future schema changes need explicit migration/rollback design. Database corruption, price-card version conflicts, and unsupported rate windows should fail visibly; do not “repair” them by deleting the live database.

## GitHub delivery

`.github/workflows/tokenledger-ci.yml` runs lint, formatting, tests, a new synthetic pipeline, model release gates, wheel build, and Docker smoke tests. Actions are pinned to verified commit SHAs. The workflow uploads the demo site, reports, and Python distribution as a reviewable artifact. It has read-only repository permissions and does not publish packages or a production service.

For a static preview:

```bash
uv run python scripts/build_site.py
uv run python -m http.server 8080 --directory site
```

Open http://127.0.0.1:8080. The static build deliberately uses the committed synthetic `reports/demo-report.json`, never the live database. It contains interactive budget scenarios and a local evidence router, but no live ingestion/backend. It can be uploaded to static hosting or a separately configured GitHub Pages workflow. GitHub stores source code; it does not run this Python API merely because the repository was pushed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `401` | Supply the configured bearer token; refresh tab authentication after key rotation |
| `403` on ingest | Set an API key; write endpoints stay disabled without one |
| `413` | Split the HTTP body below 2 MB and 5,000 records |
| Forecast unavailable | Check 56 complete contiguous days and freshness; do not fill unknown days with zero |
| DuckDB lock error | Stop extra workers/CLI writers; one process owns the database |
| Rate version conflict | Restore original document or assign a new version to changed prices |
| Unexpected duplicates | Confirm the producer's ID scope; inspect batch audits rather than removing history |

For an exposed deployment, add uptime monitoring, log retention, disk alerts, and secret rotation according to your environment. These integrations are operator responsibilities, not services silently deployed by this project.
