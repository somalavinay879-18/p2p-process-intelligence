"""Run everything: XES -> DuckDB -> process mining -> model -> dashboard data.

    python scripts/run.py data/raw/BPI_Challenge_2019.xes
    python scripts/run.py --synthetic            # small demo log, no download needed
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from p2p.export import export  # noqa: E402
from p2p.model import run as run_model  # noqa: E402
from p2p.pipeline import build  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("xes", nargs="?", default=str(ROOT / "data" / "raw" / "BPI_Challenge_2019.xes"))
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    xes = Path(args.xes)
    if args.synthetic:
        from make_synthetic import build as make_log
        xes = make_log(ROOT / "data" / "raw" / "synthetic.xes")
    if not xes.exists():
        raise SystemExit(f"{xes} not found. Download BPI_Challenge_2019.xes into data/raw/ (see README).")
    db = ROOT / "data" / "p2p.duckdb"
    reports = ROOT / "reports"
    t = time.perf_counter()
    quality = build(xes, db, reports)
    print(f"pipeline: {time.perf_counter() - t:.0f}s")
    for q in quality:
        print(f"  {'OK ' if q['passed'] else q['severity'].upper()}  {q['check']}: {q['rows']}")
    app_dir = ROOT / "data" / ("app_demo" if args.synthetic else "app")
    res = run_model(db, reports, app_dir)
    print(json.dumps(res["models"], indent=2))
    export(db, app_dir)
    print(f"done in {time.perf_counter() - t:.0f}s")


if __name__ == "__main__":
    main()
