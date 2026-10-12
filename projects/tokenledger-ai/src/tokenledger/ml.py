"""Chronological ML evaluation. No labels or future observations enter fitting."""

from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import Ridge

MODEL_VERSION = "1.0.0"


def _date(value) -> date:
    return date.fromisoformat(str(value)[:10]) if not isinstance(value, date) else value


def detect_anomalies(daily: list[dict], holdout_days: int = 14) -> dict:
    if not daily:
        return {"status": "insufficient_data", "alerts": [], "scored": [], "models": []}
    last = max(_date(row["day"]) for row in daily)
    cutoff = last - timedelta(days=holdout_days - 1)
    groups = defaultdict(list)
    for row in daily:
        groups[row["team"]].append({**row, "day": _date(row["day"])})
    scored, models = [], []
    for team, rows in sorted(groups.items()):
        rows.sort(key=lambda row: row["day"])
        train = [r for r in rows if r["day"] < cutoff]
        test = [r for r in rows if r["day"] >= cutoff]
        if len(train) < 28 or not test:
            models.append({"team": team, "status": "insufficient_data"})
            continue

        def features(row):
            return [
                np.log1p(row["cost_microusd"] / 1e6),
                np.log1p(row["requests"]),
                np.log1p(row["latency_ms"]),
                row["errors"] / max(row["requests"], 1),
                np.log1p((row["input_tokens"] + row["output_tokens"]) / row["requests"]),
                row["cached_input_tokens"] / max(row["input_tokens"], 1),
            ]

        forest = IsolationForest(n_estimators=100, contamination=0.05, random_state=17, n_jobs=1)
        forest.fit([features(row) for row in train])
        scores = forest.decision_function([features(row) for row in test])
        models.append(
            {
                "team": team,
                "status": "ready",
                "train_start": train[0]["day"].isoformat(),
                "train_end": train[-1]["day"].isoformat(),
                "training_days": len(train),
            }
        )
        for row, score in zip(test, scores, strict=True):
            peers = [r for r in train if r["day"].weekday() == row["day"].weekday()]
            baseline = float(np.median([r["cost_microusd"] / 1e6 for r in peers]))
            mad = float(np.median([abs(r["cost_microusd"] / 1e6 - baseline) for r in peers]))
            actual = row["cost_microusd"] / 1e6
            robust_z = (actual - baseline) / max(1.4826 * mad, baseline * 0.05, 0.01)
            material = actual > baseline * 1.8 and actual - baseline > 2
            alert = bool(material and (score < 0 or robust_z > 6))
            tokens = (row["input_tokens"] + row["output_tokens"]) / row["requests"]
            expected_tokens = float(
                np.median([(r["input_tokens"] + r["output_tokens"]) / r["requests"] for r in peers])
            )
            expected_requests = float(np.median([r["requests"] for r in peers]))
            drivers = []
            if tokens > expected_tokens * 1.5:
                drivers.append("tokens_per_request")
            if row["requests"] > expected_requests * 1.5:
                drivers.append("request_volume")
            if row["errors"] / row["requests"] > 0.15:
                drivers.append("error_rate")
            if not drivers:
                drivers.append("model_mix_or_token_composition")
            scored.append(
                {
                    "id": f"anomaly:{team}:{row['day']}",
                    "team": team,
                    "day": row["day"].isoformat(),
                    "cost_usd": round(actual, 6),
                    "baseline_usd": round(baseline, 6),
                    "excess_usd": round(max(0, actual - baseline), 6),
                    "is_anomaly": alert,
                    "isolation_score": round(float(score), 6),
                    "robust_z": round(robust_z, 3),
                    "drivers": drivers,
                    "severity": "high" if actual > baseline * 3 else "medium",
                }
            )
    alerts = sorted((r for r in scored if r["is_anomaly"]), key=lambda r: -r["excess_usd"])
    return {
        "status": "ready" if scored else "insufficient_data",
        "alerts": alerts,
        "scored": scored,
        "models": models,
        "model_version": MODEL_VERSION,
        "scoring_start": cutoff.isoformat(),
        "as_of": last.isoformat(),
    }


def _predict(values: np.ndarray, days: list[date], future: list[date], model: str) -> np.ndarray:
    if model == "seasonal_median":
        return np.array(
            [
                np.median(
                    [
                        v
                        for d, v in zip(days[-28:], values[-28:], strict=True)
                        if d.weekday() == target.weekday()
                    ]
                )
                for target in future
            ]
        )
    origin = days[0]

    def features(ds):
        return np.array(
            [
                [
                    (d - origin).days / 30,
                    np.sin(2 * np.pi * d.weekday() / 7),
                    np.cos(2 * np.pi * d.weekday() / 7),
                ]
                for d in ds
            ]
        )

    regressor = Ridge(alpha=1.0)
    regressor.fit(features(days), values)
    return np.maximum(0, regressor.predict(features(future)))


def forecast(daily: list[dict], horizon: int = 14) -> dict:
    if not 1 <= horizon <= 30:
        raise ValueError("horizon must be between 1 and 30")
    totals = defaultdict(int)
    for row in daily:
        totals[_date(row["day"])] += row["cost_microusd"]
    days = sorted(totals)
    if len(days) < 56:
        return {"status": "insufficient_data", "required_days": 56, "observed_days": len(days)}
    if (days[-1] - days[0]).days + 1 != len(days):
        return {"status": "data_gaps", "reason": "Missing days are unknown, not assumed zero."}
    values = np.array([totals[day] / 1e6 for day in days])
    n = len(days)
    selection_end, calibration_start, test_start = n - 28, n - 21, n - 14
    losses = {}
    for name in ("seasonal_median", "ridge_calendar"):
        predictions = _predict(
            values[:selection_end],
            days[:selection_end],
            days[selection_end:calibration_start],
            name,
        )
        losses[name] = float(np.mean(abs(values[selection_end:calibration_start] - predictions)))
    champion = min(losses, key=losses.get)
    cal = _predict(
        values[:calibration_start],
        days[:calibration_start],
        days[calibration_start:test_start],
        champion,
    )
    radius = float(
        np.quantile(abs(values[calibration_start:test_start] - cal), 0.9, method="higher")
    )
    test = _predict(values[:test_start], days[:test_start], days[test_start:], champion)
    baseline = _predict(
        values[:test_start], days[:test_start], days[test_start:], "seasonal_median"
    )
    truth = values[test_start:]

    def metrics(prediction):
        return {
            "mae_usd": round(float(np.mean(abs(truth - prediction))), 6),
            "wape": round(float(np.sum(abs(truth - prediction)) / max(np.sum(truth), 1e-9)), 6),
        }

    future = [days[-1] + timedelta(days=i) for i in range(1, horizon + 1)]
    predictions = _predict(values, days, future, champion)
    return {
        "status": "ready",
        "model": champion,
        "model_version": MODEL_VERSION,
        "as_of": days[-1].isoformat(),
        "training_days": n,
        "selection_mae_usd": {k: round(v, 6) for k, v in losses.items()},
        "backtest": {
            "start": days[test_start].isoformat(),
            "end": days[-1].isoformat(),
            "selected": metrics(test),
            "seasonal_baseline": metrics(baseline),
            "interval_coverage": round(float(np.mean(abs(truth - test) <= radius)), 6),
            "calibration_days": 7,
            "calibration_end": days[test_start - 1].isoformat(),
        },
        "interval_note": "Empirical 90th-percentile absolute-error band from 7 calibration days; "
        "not a guaranteed 90% interval and not calibrated for long horizons.",
        "points": [
            {
                "day": day.isoformat(),
                "predicted_usd": round(float(value), 6),
                "lower_usd": round(max(0, float(value) - radius), 6),
                "upper_usd": round(float(value) + radius, 6),
            }
            for day, value in zip(future, predictions, strict=True)
        ],
        "projected_usd": round(float(sum(predictions)), 6),
    }


def complete_days(rows: list[dict], today: date | None = None) -> list[dict]:
    from datetime import UTC

    today = today or datetime.now(UTC).date()
    return [row for row in rows if _date(row["day"]) < today]
