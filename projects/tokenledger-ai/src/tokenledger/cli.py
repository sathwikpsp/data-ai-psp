"""Local orchestration, evaluation, export, and serving."""

import argparse
import json
import os
from pathlib import Path

from tokenledger.demo import write_demo
from tokenledger.ml import complete_days, detect_anomalies
from tokenledger.pricing import RateCard
from tokenledger.service import build_report
from tokenledger.warehouse import Warehouse


def evaluate(warehouse: Warehouse, labels: list[dict]) -> dict:
    result = detect_anomalies(complete_days(warehouse.daily()))
    expected = {(r["day"], r["team"]): r["is_anomaly"] for r in labels}
    tp = fp = fn = tn = 0
    for row in result["scored"]:
        truth = expected[(row["day"], row["team"])]
        predicted = row["is_anomaly"]
        tp += int(truth and predicted)
        fp += int(not truth and predicted)
        fn += int(truth and not predicted)
        tn += int(not truth and not predicted)
    return {
        "dataset": "synthetic-demo-seed-17",
        "scope": "held-out final 14 calendar days",
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "scored_team_days": len(result["scored"]),
        "limitation": "Two designed incidents; these metrics do not establish real-world accuracy.",
    }


def main():
    parser = argparse.ArgumentParser(prog="tokenledger")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("demo", "ingest", "report", "evaluate", "export", "serve"):
        cmd = sub.add_parser(command)
        cmd.add_argument(
            "--data-dir", type=Path, default=Path(os.getenv("TOKENLEDGER_DATA_DIR", ".local"))
        )
        if command == "ingest":
            cmd.add_argument("path", type=Path)
        if command in {"report", "evaluate", "export"}:
            cmd.add_argument("--output", type=Path)
        if command == "serve":
            cmd.add_argument("--host", default="127.0.0.1")
            cmd.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        from tokenledger.api import create_app

        uvicorn.run(create_app(data_dir=args.data_dir), host=args.host, port=args.port, workers=1)
        return
    rate_path = os.getenv("TOKENLEDGER_RATE_CARD")
    warehouse = Warehouse(
        args.data_dir / "warehouse.duckdb", RateCard(Path(rate_path)) if rate_path else None
    )
    try:
        if args.command == "demo":
            records, _ = write_demo(args.data_dir / "synthetic")
            result = [
                warehouse.ingest(records[i : i + 5000], "demo")
                for i in range(0, len(records), 5000)
            ]
        elif args.command == "ingest":
            # Stream file in bounded batches. Earlier batches stay committed on later errors.
            result, batch = [], []
            with args.path.open() as stream:
                while line := stream.readline(100_002):
                    if len(line) > 100_000:
                        raise ValueError("JSONL line exceeds 100,000 characters")
                    if line.strip():
                        batch.append(json.loads(line))
                    if len(batch) == 5000:
                        result.append(warehouse.ingest(batch, "cli"))
                        batch = []
                if batch:
                    result.append(warehouse.ingest(batch, "cli"))
        elif args.command == "evaluate":
            labels = json.loads((args.data_dir / "synthetic/labels.json").read_text())
            result = {
                "anomaly_detection": evaluate(warehouse, labels),
                "forecast": build_report(warehouse)["forecast"],
                "dataset_fingerprint": warehouse.fingerprint(),
            }
        else:
            result = build_report(warehouse)
            if args.command == "export":
                result["mode"] = "static-demo"
        output = json.dumps(result, indent=2, default=str) + "\n"
        if getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output)
            print(args.output)
        else:
            print(output)
    finally:
        warehouse.close()


if __name__ == "__main__":
    main()
