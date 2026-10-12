# Model card — v1.0.0

## Intended use

Analyst decision support for token-based AI usage cost. Detect material upward daily cost deviations per team and provide a short-horizon aggregate forecast. The models must not automatically disable services, change model routing, or allocate financial commitments. Output drivers are associations, not causal attribution.

## Anomaly model

- Inputs: daily cost, request count, average latency, error rate, tokens per request, and cached-input fraction.
- Transforms: logarithms for scale-heavy features; Isolation Forest with 100 estimators, contamination 0.05, fixed seed 17, and one compute thread.
- Split: the final 14 complete calendar days are scoring data; earlier team history is training data. A team needs at least 28 observed training days. Labels never enter fitting.
- Business gate: spend must exceed 1.8× the training weekday median and exceed that median by more than $2. Then either an Isolation Forest outlier or robust cost z-score above 6 triggers an alert.
- Robust scale: max(1.4826 × weekday MAD, 5% of baseline, $0.01). Severity is high above 3× baseline.
- Explanation: identify higher request volume, higher tokens per request, or error rate above 15%; otherwise flag model mix/token composition for review.

The forest score is an outlier score, not a probability. This detector targets upward **cost** incidents: missing usage, latency-only failures, gradual drift, or low-cost attacks can go unflagged. It is not a complete availability or security monitor. Teams with sparse/missing history should be investigated separately.

## Forecast model

At least 56 contiguous complete daily totals are required. Missing days cause abstention because an absent event feed cannot be distinguished from genuine zero usage. Today's partial UTC day is excluded. The forecast is anchored to the last available complete day; stale data does not magically make it a forecast from today.

Two candidates are compared: a 28-day weekday median and Ridge regression using elapsed time plus weekly sine/cosine features. For `n` observed days:

| Stage | Fit history | Evaluation window |
| --- | --- | --- |
| Select champion by MAE | Days before `n-28` | `[n-28, n-21)` |
| Calibrate error band | Days before `n-21` | `[n-21, n-14)` |
| Report held-out error | Days before `n-14` | `[n-14, n)` |
| Produce forecast | All observed days | Next 1–30 days; dashboard uses 14 |

Selection never uses calibration or test observations. Tests assert that perturbing the test window cannot change the champion. Holdout WAPE uses the absolute-error sum divided by the actual-cost sum; a near-zero floor avoids division by zero. Both the champion and seasonal baseline metrics are retained.

The band uses the 90th-percentile absolute error of only seven calibration days, with nonnegative lower bounds. It is **not a guaranteed 90% predictive interval**, and it is not calibrated independently for each horizon. Coverage is measured and disclosed on the later holdout. Regime shifts, rapid adoption, pricing changes, and injected spikes can cause poor coverage. The bands are available in API/report evidence; the chart shows the point forecast only.

## Dataset and evaluation

The deterministic generator creates 84 days, 3 teams, 5,424 invocations, weekday seasonality, mild growth, variable cache ratios, and occasional errors. Two incidents in the final 14 days multiply tokens and increase latency/error rates. Ground truth is stored separately in `labels.json` and used only during evaluation.

On this designed fixture, the anomaly release gate requires both incidents detected and no extra alerts across 42 held-out team-days. Do not present this as an independently validated production benchmark. There are only two positives, no representative customer cohorts, and no benchmark against adversarial or unseen incident families. Run historical backtests on your own labeled data and choose per-team business thresholds before operational use.

The exact forecast metrics, split dates, calibration coverage, and dataset SHA-256 are in [`evaluation.json`](../reports/evaluation.json). Reproduce with the README commands. No cloud model registry, online learning, automated retraining scheduler, drift detector, or deployment promotion service is implemented. A model-version string and report lineage provide lightweight reproducibility for this reference deployment.

## Evidence assistant

The assistant routes spending, anomaly, forecast, and optimization questions to precomputed data. It never calls an LLM. Unsupported intents abstain; instruction-like text cannot grant tool access. Responses cite evidence IDs and expose their records. The static export uses the same report facts through a small JavaScript router, with slightly different wording from the API.
