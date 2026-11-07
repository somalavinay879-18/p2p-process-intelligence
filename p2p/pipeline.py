"""One entry point: XES -> DuckDB raw tables -> staging -> quality checks."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .ingest import load
from .quality import assert_no_errors, run_checks

SQL_DIR = Path(__file__).parent / "sql"


def run_sql(con: duckdb.DuckDBPyConnection, name: str) -> None:
    con.execute((SQL_DIR / name).read_text())


def build(xes_path: str | Path, db_path: str | Path, report_dir: str | Path | None = None) -> list[dict]:
    load(xes_path, db_path)
    con = duckdb.connect(str(db_path))
    run_sql(con, "staging.sql")
    results = run_checks(con)
    if not [r for r in results if r["severity"] == "error" and not r["passed"]]:
        run_sql(con, "process.sql")
    if report_dir:
        Path(report_dir).mkdir(parents=True, exist_ok=True)
        (Path(report_dir) / "data_quality.json").write_text(json.dumps(results, indent=2))
    assert_no_errors(results)
    con.close()
    return results
