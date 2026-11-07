"""Data-quality checks on the staged event log.

Each check returns the number of offending rows. "error" checks must be 0 for the
pipeline to continue; "warning" checks are reported and handled by the staging rules.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

KNOWN_CATEGORIES = ("3-way match, invoice after GR", "3-way match, invoice before GR", "2-way match", "Consignment")


@dataclass
class Check:
    name: str
    severity: str  # "error" or "warning"
    sql: str
    meaning: str


CHECKS = [
    Check("duplicate_case_ids", "error",
          "SELECT count(*) - count(DISTINCT case_id) FROM cases",
          "every purchase order item appears once"),
    Check("events_without_case", "error",
          "SELECT count(*) FROM events_all e LEFT JOIN cases c USING (case_id) WHERE c.case_id IS NULL",
          "every event belongs to a known purchase order item"),
    Check("unknown_item_category", "error",
          f"SELECT count(*) FROM cases WHERE item_category NOT IN {KNOWN_CATEGORIES}",
          "item category is one of the four matching types"),
    Check("timestamps_out_of_range", "warning",
          "SELECT count(*) FROM events_all WHERE ts NOT BETWEEN TIMESTAMP '2017-01-01' AND TIMESTAMP '2020-12-31'",
          "events dated outside 2017-2020 are excluded from timing analysis"),
    Check("duplicate_events", "warning",
          "SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM events_all)) FROM events_all",
          "exact duplicate events are removed"),
    Check("cases_without_po_creation", "warning",
          "SELECT count(*) FROM cases c WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.case_id = c.case_id "
          "AND e.activity = 'Create Purchase Order Item')",
          "items whose PO creation is missing cannot be timed from creation"),
    Check("negative_net_worth", "warning",
          "SELECT count(*) FROM events_all WHERE net_worth_eur < 0",
          "negative cumulative net worth (corrections)"),
]


def run_checks(con: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = []
    for c in CHECKS:
        n = con.execute(c.sql).fetchone()[0]
        rows.append({"check": c.name, "severity": c.severity, "rows": int(n), "passed": n == 0, "meaning": c.meaning})
    return rows


def assert_no_errors(results: list[dict]) -> None:
    failed = [r for r in results if r["severity"] == "error" and not r["passed"]]
    if failed:
        raise ValueError("Data-quality errors: " + ", ".join(f"{r['check']} ({r['rows']})" for r in failed))
