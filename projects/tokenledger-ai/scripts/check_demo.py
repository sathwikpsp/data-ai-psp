"""A release gate on held-out synthetic incidents and pipeline completeness."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
evaluation = json.loads((ROOT / "reports/evaluation.json").read_text())
report = json.loads((ROOT / "reports/demo-report.json").read_text())
assert evaluation["anomaly_detection"]["recall"] == 1.0
assert evaluation["anomaly_detection"]["precision"] == 1.0
assert evaluation["anomaly_detection"]["scored_team_days"] == 42
assert report["overview"]["requests"] == 5424
assert report["overview"]["quality"]["rejected"] == 0
assert len(report["daily"]) == 84
assert report["forecast"]["status"] == "ready"
assert report["dataset_fingerprint"] == evaluation["dataset_fingerprint"]
print("Synthetic end-to-end release gates passed.")
