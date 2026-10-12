"""Deterministic synthetic usage; labels are held separately from pipeline records."""

import json
import math
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def generate(seed: int = 17, days: int = 84, end: date = date(2026, 10, 11)) -> tuple[list, list]:
    rng = random.Random(seed)
    records, labels = [], []
    start = end - timedelta(days=days - 1)
    configs = [
        ("support", 30, "demo-cloud", "swift-small"),
        ("research", 18, "demo-lab", "reasoner-pro"),
        ("platform", 22, "demo-cloud", "swift-small"),
    ]
    incidents = {(end - timedelta(days=2), "research"), (end - timedelta(days=5), "support")}
    for offset in range(days):
        day = start + timedelta(days=offset)
        weekday_factor = 0.72 if day.weekday() >= 5 else 1.0
        for team, count, provider, model in configs:
            incident = (day, team) in incidents
            n = round(count * weekday_factor)
            labels.append({"day": day.isoformat(), "team": team, "is_anomaly": incident})
            for index in range(n):
                growth = 1 + offset * 0.001
                noise = rng.uniform(0.88, 1.12)
                multiplier = 8 if incident else 1
                input_tokens = round(24_000 * noise * growth * multiplier)
                output_tokens = round(2300 * rng.uniform(0.85, 1.15) * multiplier)
                cached = round(input_tokens * (0.03 if incident else rng.uniform(0.30, 0.50)))
                timestamp = datetime.combine(day, datetime.min.time(), UTC) + timedelta(
                    hours=8 + (index % 14), minutes=rng.randrange(60)
                )
                records.append(
                    {
                        "schema_version": "1",
                        "request_id": f"demo-{seed}-{day}-{team}-{index}",
                        "timestamp": timestamp.isoformat(),
                        "provider": provider,
                        "model": model,
                        "team": team,
                        "environment": "production",
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cached_input_tokens": cached,
                        "latency_ms": round(
                            450
                            + 80 * math.sin(index)
                            + rng.uniform(0, 120)
                            + (1200 if incident else 0),
                            2,
                        ),
                        "status": "error"
                        if rng.random() < (0.20 if incident else 0.02)
                        else "success",
                    }
                )
    return records, labels


def write_demo(directory: Path, seed: int = 17) -> tuple[list, list]:
    directory.mkdir(parents=True, exist_ok=True)
    records, labels = generate(seed=seed)
    (directory / "usage.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    (directory / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    return records, labels
