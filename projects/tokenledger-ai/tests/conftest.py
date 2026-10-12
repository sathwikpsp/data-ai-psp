from collections import defaultdict
from datetime import date

import pytest

from tokenledger.contracts import UsageEvent
from tokenledger.demo import generate
from tokenledger.pricing import RateCard
from tokenledger.warehouse import Warehouse


@pytest.fixture
def event():
    return {
        "request_id": "request-1",
        "timestamp": "2026-09-01T12:00:00Z",
        "provider": "demo-cloud",
        "model": "swift-small",
        "team": "platform",
        "input_tokens": 1000,
        "output_tokens": 100,
        "cached_input_tokens": 200,
        "latency_ms": 500,
    }


@pytest.fixture
def warehouse():
    instance = Warehouse(":memory:")
    yield instance
    instance.close()


@pytest.fixture(scope="session")
def daily():
    records, _ = generate()
    rates = RateCard()
    groups = defaultdict(list)
    for row in records:
        groups[(date.fromisoformat(row["timestamp"][:10]), row["team"])].append(row)
    result = []
    for (day, team), rows in sorted(groups.items()):
        result.append(
            {
                "day": day,
                "team": team,
                "requests": len(rows),
                "cost_microusd": sum(rates.cost(UsageEvent.model_validate(r)) for r in rows),
                "input_tokens": sum(r["input_tokens"] for r in rows),
                "output_tokens": sum(r["output_tokens"] for r in rows),
                "cached_input_tokens": sum(r["cached_input_tokens"] for r in rows),
                "latency_ms": sum(r["latency_ms"] for r in rows) / len(rows),
                "errors": sum(r["status"] == "error" for r in rows),
            }
        )
    return result
