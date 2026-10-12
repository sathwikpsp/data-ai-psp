import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tokenledger.contracts import UsageEvent
from tokenledger.pricing import RateCard
from tokenledger.warehouse import Warehouse


@pytest.mark.parametrize(
    "changes",
    [
        {"input_tokens": -1},
        {"input_tokens": True},
        {"input_tokens": 1.5},
        {"cached_input_tokens": 1001},
        {"timestamp": "2026-09-01T12:00:00"},
        {"latency_ms": float("nan")},
        {"latency_ms": float("inf")},
        {"prompt": "must not be persisted"},
        {"team": "<script>unsafe</script>"},
        {"timestamp": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    ],
)
def test_contract_rejects_invalid_metadata(event, changes):
    with pytest.raises(ValidationError):
        UsageEvent.model_validate(event | changes)


def test_cost_does_not_double_count_cached_input(event):
    # 800*0.4 + 200*0.1 + 100*1.6 = 500 micro-USD.
    assert RateCard().cost(UsageEvent.model_validate(event)) == 500


def test_decimal_rounding_is_per_request(event):
    event.update(input_tokens=1, cached_input_tokens=0, output_tokens=1)
    assert RateCard().cost(UsageEvent.model_validate(event)) == 2


def test_utc_normalization_precedes_fingerprinting(warehouse, event):
    warehouse.ingest([event], "test")
    replay = event | {"timestamp": "2026-09-01T17:30:00+05:30"}
    assert warehouse.ingest([replay], "test")["duplicates"] == 1


def test_replays_conflicts_and_unknown_prices_are_audited(warehouse, event):
    first = warehouse.ingest([event, event], "test")
    assert (first["accepted"], first["duplicates"]) == (1, 1)
    before = warehouse.fingerprint()
    result = warehouse.ingest(
        [
            event,
            event | {"output_tokens": 900},
            event | {"request_id": "new", "model": "unknown"},
        ],
        "test",
    )
    assert (result["accepted"], result["duplicates"], result["rejected"]) == (0, 1, 2)
    assert warehouse.fingerprint() == before
    assert warehouse.overview()["cost_microusd"] == 500
    assert warehouse.query("SELECT COUNT(*) AS n FROM bronze_events")[0]["n"] == 1


def test_invalid_payload_content_is_not_retained(warehouse, event):
    result = warehouse.ingest([event | {"prompt": "private-content"}], "test")
    assert result["rejected"] == 1
    assert "private-content" not in str(warehouse.query("SELECT * FROM quality_issues"))
    assert warehouse.query("SELECT * FROM bronze_events") == []


def test_concurrent_replays_are_idempotent(warehouse, event):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: warehouse.ingest([event], "test"), range(12)))
    assert sum(r["accepted"] for r in results) == 1
    assert sum(r["duplicates"] for r in results) == 11


def test_rejected_only_batch_does_not_change_data_fingerprint(warehouse, event):
    before = warehouse.fingerprint()
    warehouse.ingest([event | {"input_tokens": -1}], "test")
    assert warehouse.fingerprint() == before
    assert warehouse.overview()["quality"]["rejected"] == 1


def test_rate_card_version_is_immutable(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    warehouse = Warehouse(path)
    warehouse.close()
    rates = RateCard()
    rates.document["description"] = "changed"
    with pytest.raises(ValueError, match="without a new version"):
        Warehouse(path, rates)


def test_overlapping_rates_are_rejected(tmp_path):
    document = copy.deepcopy(RateCard().document)
    document["rates"].append(document["rates"][0])
    path = tmp_path / "rates.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="overlapping"):
        RateCard(path)


def test_effective_end_is_exclusive(tmp_path, event):
    document = copy.deepcopy(RateCard().document)
    document["rates"][0]["valid_to"] = event["timestamp"]
    path = tmp_path / "rates.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="unpriced"):
        RateCard(path).cost(UsageEvent.model_validate(event))


def test_rate_version_changes_preserve_old_valuations(tmp_path, event):
    path = tmp_path / "warehouse.duckdb"
    warehouse = Warehouse(path)
    warehouse.ingest([event], "test")
    before = warehouse.fingerprint()
    warehouse.close()
    rates = RateCard()
    rates.version = rates.document["version"] = "new-version"
    rates.rates[0]["input"] = "100.00"
    warehouse = Warehouse(path, rates)
    try:
        assert warehouse.ingest([event], "test")["duplicates"] == 1
        assert warehouse.overview()["cost_microusd"] == 500
        assert warehouse.fingerprint() == before
    finally:
        warehouse.close()


def test_success_denominator_includes_failed_request_costs(warehouse, event):
    warehouse.ingest([event, event | {"request_id": "err", "status": "error"}], "test")
    assert warehouse.overview()["cost_per_success_usd"] == 0.001


def test_batch_bounds(warehouse):
    with pytest.raises(ValueError):
        warehouse.ingest([])
    with pytest.raises(ValueError):
        warehouse.ingest([{}] * 5001)
