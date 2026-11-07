"""Export the small aggregate tables the dashboard needs (a few hundred KB), so the
dashboard can be deployed without the 700 MB raw log."""
from __future__ import annotations

from pathlib import Path

import duckdb

TABLES = {
    # one slim row per PO item, so the dashboard can filter by period, category, spend area and company
    "items": """SELECT case_id, CAST(po_created AS DATE) AS po_date, item_category, spend_area, company,
                       document_type, vendor, net_worth_eur,
                       violates_matching_rule AS violation, n_payment_blocks > 0 AS blocked,
                       n_price_changes > 0 AS price_changed, is_paid,
                       round(cycle_days, 2) AS cycle_days, round(po_to_gr_days, 2) AS po_to_gr_days,
                       round(date_diff('hour', po_created, first_ir) / 24.0, 2) AS po_to_ir_days,
                       round(ir_to_clear_days, 2) AS ir_to_clear_days
                FROM case_summary WHERE po_created IS NOT NULL""",
    # directly-follows graph per item category
    "dfg_category": """SELECT c.item_category, e1.activity AS source, e2.activity AS target, count(*) AS frequency,
                              median(date_diff('hour', e1.ts, e2.ts)) / 24.0 AS median_days
                       FROM events_ordered e1
                       JOIN events_ordered e2 ON e1.case_id = e2.case_id AND e2.seq = e1.seq + 1
                       JOIN cases c ON c.case_id = e1.case_id
                       GROUP BY ALL""",
    "compliance": "SELECT * FROM compliance",
    "dfg": "SELECT * FROM dfg",
    "variants": "SELECT * FROM variants LIMIT 50",
    "vendor_scorecard": "SELECT * FROM vendor_scorecard",
    "monthly": "SELECT * FROM monthly",
    "step_durations": "SELECT * FROM step_durations",
    "spend_area": """SELECT spend_area, count(*) AS items, sum(net_worth_eur) AS spend_eur,
                            avg(violates_matching_rule::INT) AS violation_rate,
                            avg((n_payment_blocks > 0)::INT) AS payment_block_rate
                     FROM case_summary GROUP BY 1 ORDER BY spend_eur DESC""",
    "overview": """SELECT count(*) AS items, count(DISTINCT po_number) AS purchase_orders,
                          count(DISTINCT vendor) AS vendors, sum(net_worth_eur) AS spend_eur,
                          (SELECT count(*) FROM events) AS events,
                          avg(violates_matching_rule::INT) AS violation_rate,
                          sum(net_worth_eur) FILTER (violates_matching_rule) AS value_at_risk_eur,
                          avg((n_payment_blocks > 0)::INT) AS payment_block_rate,
                          median(cycle_days) AS median_cycle_days
                   FROM case_summary""",
}


def export(db_path: str | Path, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    paths = []
    for name, sql in TABLES.items():
        p = out / f"{name}.parquet"
        con.execute(f"COPY ({sql}) TO '{p}' (FORMAT parquet)")
        paths.append(p)
    con.close()
    return paths
