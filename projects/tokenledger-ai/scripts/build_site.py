"""Build a portable, static dashboard from the committed synthetic report only."""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site"


def main():
    source = ROOT / "src/tokenledger/static"
    report = ROOT / "reports/demo-report.json"
    data = json.loads(report.read_text())
    if data.get("mode") != "static-demo" or not data["rate_card_version"].startswith("demo-"):
        raise ValueError("only the explicitly labeled synthetic demo may be published")
    OUT.mkdir(exist_ok=True)
    shutil.copytree(source, OUT / "static", dirs_exist_ok=True)
    html = (
        (source / "index.html")
        .read_text()
        .replace(
            'name="tokenledger-mode" content="live"', 'name="tokenledger-mode" content="static"'
        )
    )
    (OUT / "index.html").write_text(html)
    shutil.copy2(report, OUT / "report.json")
    (OUT / ".nojekyll").touch()
    print(OUT)


if __name__ == "__main__":
    main()
