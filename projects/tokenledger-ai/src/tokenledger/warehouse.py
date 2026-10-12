"""Transactional bronze/silver/gold pipeline with replay and conflict detection."""

import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import duckdb
from pydantic import ValidationError

from tokenledger.contracts import UsageEvent
from tokenledger.pricing import RateCard


class Warehouse:
    """One connection + process-local lock. Run exactly one application worker."""

    def __init__(self, path: str | Path, rates: RateCard | None = None):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.rates = rates or RateCard()
        self.lock = threading.RLock()
        self.db = duckdb.connect(str(path))
        self.db.execute("SET TimeZone='UTC'")
        self.db.execute(files("tokenledger").joinpath("assets/schema.sql").read_text())
        document = json.dumps(self.rates.document, sort_keys=True)
        row = self.db.execute(
            "SELECT document FROM rate_cards WHERE version = ?", [self.rates.version]
        ).fetchone()
        if row and row[0] != document:
            self.db.close()
            raise ValueError("rate card contents changed without a new version")
        self.db.execute(
            "INSERT INTO rate_cards VALUES (?, ?) ON CONFLICT DO NOTHING",
            [self.rates.version, document],
        )

    def close(self):
        with self.lock:
            self.db.close()

    @contextmanager
    def snapshot(self):
        with self.lock:
            yield self

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        with self.lock:
            result = self.db.execute(sql, params or [])
            columns = [item[0] for item in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]

    def ingest(self, records: list[dict], source: str = "api") -> dict:
        if not 1 <= len(records) <= 5000:
            raise ValueError("a batch must contain 1 to 5000 records")
        if source not in {"api", "cli", "demo", "test"}:
            raise ValueError("invalid source")
        batch_id = str(uuid4())
        with self.lock:
            existing = dict(
                self.db.execute("SELECT request_id, payload_hash FROM bronze_events").fetchall()
            )
            bronze, silver, issues = [], [], []
            duplicates = 0
            for index, record in enumerate(records, start=1):
                try:
                    event = UsageEvent.model_validate(record)
                except (ValidationError, TypeError, ValueError):
                    # Never persist a rejected raw payload or Pydantic's input echo.
                    issues.append((batch_id, index, "invalid_contract"))
                    continue
                canonical = event.model_dump_json()
                digest = hashlib.sha256(canonical.encode()).hexdigest()
                if event.request_id in existing:
                    if existing[event.request_id] == digest:
                        duplicates += 1
                    else:
                        issues.append((batch_id, index, "conflicting_request_id"))
                    continue
                try:
                    cost = self.rates.cost(event)
                except ValueError:
                    issues.append((batch_id, index, "unpriced_model_or_date"))
                    continue
                existing[event.request_id] = digest
                bronze.append((event.request_id, batch_id, digest, canonical))
                silver.append(
                    (
                        event.request_id,
                        event.timestamp,
                        event.provider,
                        event.model,
                        event.team,
                        event.environment,
                        event.input_tokens,
                        event.output_tokens,
                        event.cached_input_tokens,
                        event.latency_ms,
                        event.status,
                        cost,
                        self.rates.version,
                        batch_id,
                    )
                )
            self.db.execute("BEGIN TRANSACTION")
            try:
                self.db.execute(
                    "INSERT INTO ingestion_batches "
                    "(batch_id, source, accepted, duplicates, rejected) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [batch_id, source, len(silver), duplicates, len(issues)],
                )
                if bronze:
                    self.db.executemany("INSERT INTO bronze_events VALUES (?, ?, ?, ?)", bronze)
                    self.db.executemany(
                        "INSERT INTO usage_events VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        silver,
                    )
                if issues:
                    self.db.executemany("INSERT INTO quality_issues VALUES (?, ?, ?)", issues)
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return {
            "batch_id": batch_id,
            "accepted": len(silver),
            "duplicates": duplicates,
            "rejected": len(issues),
            "issues": [{"row": row, "reason": reason} for _, row, reason in issues[:50]],
        }

    def fingerprint(self) -> str:
        with self.lock:
            rows = self.db.execute(
                "SELECT b.request_id, b.payload_hash, u.rate_card_version, u.cost_microusd "
                "FROM bronze_events b JOIN usage_events u USING (request_id) ORDER BY b.request_id"
            ).fetchall()
            return hashlib.sha256(json.dumps(rows).encode()).hexdigest()

    def daily(self) -> list[dict]:
        return self.query("SELECT * FROM daily_usage ORDER BY day, team")

    def overview(self) -> dict:
        with self.lock:
            aggregate = self.query(
                "SELECT COUNT(*) AS requests, COALESCE(SUM(cost_microusd),0)::BIGINT "
                "AS cost_microusd, COALESCE(SUM(input_tokens+output_tokens),0)::BIGINT AS tokens, "
                "MIN(event_time) AS first_event, MAX(event_time) AS last_event, "
                "COUNT(DISTINCT team) AS teams, "
                "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes "
                "FROM usage_events"
            )[0]
            aggregate["cost_usd"] = aggregate["cost_microusd"] / 1e6
            aggregate["cost_per_success_usd"] = (
                aggregate["cost_usd"] / aggregate["successes"] if aggregate["successes"] else None
            )
            aggregate["data_lag_hours"] = (
                max(0, (datetime.now(UTC) - aggregate["last_event"]).total_seconds() / 3600)
                if aggregate["last_event"]
                else None
            )
            aggregate["freshness"] = (
                "no_data"
                if aggregate["last_event"] is None
                else "stale"
                if aggregate["last_event"] < datetime.now(UTC) - timedelta(hours=48)
                else "fresh"
            )
            aggregate["by_team"] = self.query(
                "SELECT team, SUM(cost_microusd)/1e6 AS cost_usd, COUNT(*) AS requests, "
                "SUM(cached_input_tokens)*1.0/NULLIF(SUM(input_tokens),0) AS cache_ratio, "
                "AVG(CASE WHEN status='error' THEN 1.0 ELSE 0.0 END) AS error_rate "
                "FROM usage_events GROUP BY team ORDER BY cost_usd DESC"
            )
            aggregate["by_model"] = self.query(
                "SELECT provider, model, SUM(cost_microusd)/1e6 AS cost_usd, COUNT(*) AS requests "
                "FROM usage_events GROUP BY provider, model ORDER BY cost_usd DESC"
            )
            aggregate["quality"] = self.query(
                "SELECT COALESCE(SUM(accepted),0)::BIGINT AS accepted, "
                "COALESCE(SUM(duplicates),0)::BIGINT AS duplicates, "
                "COALESCE(SUM(rejected),0)::BIGINT AS rejected FROM ingestion_batches"
            )[0]
            return aggregate
