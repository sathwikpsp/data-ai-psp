"""Snapshot-consistent evidence and explanations. No model-generated SQL or actions."""

from datetime import UTC, datetime

from tokenledger.ml import complete_days, detect_anomalies, forecast
from tokenledger.warehouse import Warehouse


def build_report(warehouse: Warehouse, budget_usd: float = 100) -> dict:
    with warehouse.snapshot():
        overview = warehouse.overview()
        daily = warehouse.daily()
        completed = complete_days(daily)
        anomalies = detect_anomalies(completed)
        prediction = forecast(completed)
        fingerprint = warehouse.fingerprint()
        totals = {}
        for row in daily:
            day = str(row["day"])
            totals[day] = totals.get(day, 0) + row["cost_microusd"]
        return {
            "schema_version": "1",
            "generated_at": datetime.now(UTC).isoformat(),
            "dataset_fingerprint": fingerprint,
            "rate_card_version": warehouse.rates.version,
            "pricing_note": warehouse.rates.document.get("description", "Custom rate card"),
            "overview": overview,
            "daily": [{"day": d, "cost_usd": c / 1e6} for d, c in sorted(totals.items())],
            "anomalies": {k: v for k, v in anomalies.items() if k != "scored"},
            "forecast": prediction,
            "budget": {
                "horizon_days": 14,
                "budget_usd": budget_usd,
                "projected_usd": prediction.get("projected_usd"),
                "at_risk": prediction.get("projected_usd", 0) > budget_usd,
            },
        }


def explain(question: str, report: dict) -> dict:
    """Constrained intent routing to computed evidence, explicitly not an LLM."""
    question = question.lower()
    evidence, sentences = [], []
    if any(word in question for word in ("anomal", "spike", "why", "incident")):
        for alert in report["anomalies"]["alerts"][:3]:
            evidence.append({"id": alert["id"], "data": alert})
            sentences.append(
                f"{alert['team']} spent ${alert['cost_usd']:.2f} on {alert['day']} against "
                f"a ${alert['baseline_usd']:.2f} historical weekday median. "
                f"Observed signals: {', '.join(alert['drivers'])}. [{alert['id']}]"
            )
        if not evidence:
            sentences.append(
                "No cost spikes meet the detector's materiality thresholds. "
                "This does not prove that all usage is normal."
            )
    elif any(word in question for word in ("forecast", "budget", "future", "next")):
        forecast_data = report["forecast"]
        if forecast_data["status"] == "ready":
            evidence.append({"id": "forecast:14d", "data": forecast_data})
            sentences.append(
                f"The next 14 days are projected at ${forecast_data['projected_usd']:.2f} "
                f"using {forecast_data['model']}. This is a forecast from the last "
                "observed complete day, not a guarantee. [forecast:14d]"
            )
        else:
            sentences.append(f"Forecast unavailable: {forecast_data['status']}.")
    elif any(word in question for word in ("cost", "spend", "team", "expensive", "summary")):
        for team in report["overview"]["by_team"][:3]:
            key = f"team:{team['team']}"
            evidence.append({"id": key, "data": team})
            sentences.append(
                f"{team['team']}: ${team['cost_usd']:.2f} across "
                f"{team['requests']} requests in the observed window. [{key}]"
            )
        if not evidence:
            sentences.append("There are no accepted usage records yet.")
    elif any(word in question for word in ("save", "optim", "cache", "recommend")):
        for team in report["overview"]["by_team"][:3]:
            key = f"team:{team['team']}"
            evidence.append({"id": key, "data": team})
            cache = team["cache_ratio"] or 0
            sentences.append(
                f"Review {team['team']}: cached input share is {cache:.1%}, "
                f"error rate is {team['error_rate']:.1%}. Evaluate retry limits and "
                f"cache eligibility before changing model routing. [{key}]"
            )
        if not evidence:
            sentences.append("No accepted usage is available to review.")
    else:
        return {
            "mode": "evidence_router",
            "status": "unsupported",
            "answer": "Ask about spending by team, cost spikes, the 14-day forecast, or "
            "optimization. This assistant cannot execute instructions or SQL.",
            "evidence": [],
        }
    return {
        "mode": "evidence_router",
        "status": "answered",
        "answer": "\n\n".join(sentences),
        "evidence": evidence,
        "dataset_fingerprint": report["dataset_fingerprint"],
        "caveat": "Signals show association, not proven root cause. No actions were executed.",
    }
