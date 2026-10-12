import copy
from datetime import date

from tokenledger.demo import generate
from tokenledger.ml import complete_days, detect_anomalies, forecast


def test_synthetic_incidents_are_detected_without_training_on_labels(daily):
    result = detect_anomalies(daily)
    _, labels = generate()
    truth = {(r["day"], r["team"]) for r in labels if r["is_anomaly"]}
    predictions = {(r["day"], r["team"]) for r in result["alerts"]}
    assert predictions == truth
    assert len(result["scored"]) == 42
    assert all(m["train_end"] < result["scoring_start"] for m in result["models"])


def test_holdout_changes_cannot_change_anomaly_baseline(daily):
    before = detect_anomalies(daily)
    changed = copy.deepcopy(daily)
    changed[-1]["cost_microusd"] *= 100
    after = detect_anomalies(changed)
    assert before["models"] == after["models"]
    assert [r["baseline_usd"] for r in before["scored"]] == [
        r["baseline_usd"] for r in after["scored"]
    ]


def test_forecast_is_reproducible_and_nonnegative(daily):
    first = forecast(daily)
    assert first == forecast(daily)
    assert len(first["points"]) == 14
    assert all(0 <= p["lower_usd"] <= p["predicted_usd"] <= p["upper_usd"] for p in first["points"])
    assert first["points"][0]["day"] > first["backtest"]["end"]
    assert first["backtest"]["calibration_end"] < first["backtest"]["start"]


def test_test_period_never_selects_forecast_champion(daily):
    before = forecast(daily)
    changed = copy.deepcopy(daily)
    for row in changed[-42:]:
        row["cost_microusd"] *= 100
    after = forecast(changed)
    assert before["selection_mae_usd"] == after["selection_mae_usd"]
    assert before["model"] == after["model"]


def test_missing_days_and_cold_start_abstain(daily):
    assert forecast(daily[:30])["status"] == "insufficient_data"
    missing = [r for r in daily if r["day"] != daily[30]["day"]]
    assert forecast(missing)["status"] == "data_gaps"
    assert detect_anomalies(daily[:30])["status"] == "insufficient_data"


def test_partial_current_day_is_excluded(daily):
    rows = complete_days(daily, today=date(2026, 10, 11))
    assert all(row["day"] < date(2026, 10, 11) for row in rows)


def test_empty_dataset_and_short_horizon():
    assert detect_anomalies([])["alerts"] == []
    assert forecast([])["observed_days"] == 0
