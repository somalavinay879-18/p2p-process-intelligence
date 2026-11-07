-- Process mining on the cleaned event log, in plain SQL.
-- Ties: many events share a timestamp; a fixed P2P order breaks them deterministically.

CREATE OR REPLACE MACRO step_rank(a) AS CASE a
    WHEN 'Create Purchase Requisition Item' THEN 1 WHEN 'Create Purchase Order Item' THEN 2
    WHEN 'Vendor creates invoice' THEN 3 WHEN 'Record Goods Receipt' THEN 4
    WHEN 'Record Invoice Receipt' THEN 5 WHEN 'Set Payment Block' THEN 6
    WHEN 'Remove Payment Block' THEN 7 WHEN 'Clear Invoice' THEN 8 ELSE 5 END;

CREATE OR REPLACE TABLE events_ordered AS
SELECT *, row_number() OVER (PARTITION BY case_id ORDER BY ts, step_rank(activity), activity) AS seq
FROM events;

-- one row per purchase order item
CREATE OR REPLACE TABLE case_summary AS
WITH agg AS (
    SELECT case_id,
        min(ts)                                                     AS first_ts,
        max(ts)                                                     AS last_ts,
        min(ts) FILTER (activity = 'Create Purchase Order Item')   AS po_created,
        min(ts) FILTER (activity = 'Record Goods Receipt')         AS first_gr,
        min(ts) FILTER (activity = 'Record Invoice Receipt')       AS first_ir,
        min(ts) FILTER (activity = 'Clear Invoice')                AS first_clear,
        max(ts) FILTER (activity = 'Clear Invoice')                AS last_clear,
        count(*)                                                    AS n_events,
        -- in this log blocks are mostly set automatically when an invoice is posted, so only
        -- "Remove Payment Block" is recorded; either event means the item had a payment block
        count(*) FILTER (activity IN ('Set Payment Block', 'Remove Payment Block')) AS n_payment_blocks,
        count(*) FILTER (activity LIKE 'Change Price%')            AS n_price_changes,
        count(*) FILTER (activity LIKE 'Change Quantity%')         AS n_quantity_changes,
        count(*) FILTER (activity LIKE 'Delete%' OR activity LIKE 'Cancel%') AS n_cancellations,
        count(*) FILTER (activity = 'Record Goods Receipt')        AS n_gr,
        count(*) FILTER (activity = 'Record Invoice Receipt')      AS n_ir,
        arg_max(net_worth_eur, seq)                                 AS net_worth_eur,
        string_agg(activity, ' > ' ORDER BY seq)                    AS trace
    FROM events_ordered GROUP BY case_id
)
SELECT c.*, a.* EXCLUDE (case_id),
    -- variant = sequence with immediate repetitions collapsed is done in Python; raw trace kept here
    date_diff('hour', a.po_created, a.last_clear) / 24.0              AS cycle_days,
    date_diff('hour', a.po_created, a.first_gr) / 24.0                AS po_to_gr_days,
    date_diff('hour', a.first_ir, a.first_clear) / 24.0               AS ir_to_clear_days,
    a.last_clear IS NOT NULL                                           AS is_paid,
    -- compliance against the item's matching type
    CASE
        WHEN c.item_category = '3-way match, invoice after GR'
             THEN a.first_ir IS NOT NULL AND (a.first_gr IS NULL OR a.first_ir < a.first_gr)
        WHEN c.item_category = '3-way match, invoice before GR'
             THEN a.first_clear IS NOT NULL AND (a.first_gr IS NULL OR a.first_clear < a.first_gr)
        WHEN c.item_category = '2-way match'   THEN a.n_gr > 0
        WHEN c.item_category = 'Consignment'   THEN a.n_ir > 0
    END                                                                AS violates_matching_rule,
    a.first_clear IS NOT NULL AND a.first_ir IS NULL                   AS paid_without_invoice_receipt
FROM cases c JOIN agg a USING (case_id);

-- directly-follows relations: how often activity A is directly followed by B, and how long it takes
CREATE OR REPLACE TABLE dfg AS
SELECT e1.activity AS source, e2.activity AS target, count(*) AS frequency,
       median(date_diff('hour', e1.ts, e2.ts)) / 24.0 AS median_days
FROM events_ordered e1 JOIN events_ordered e2 ON e1.case_id = e2.case_id AND e2.seq = e1.seq + 1
GROUP BY ALL;

-- matching-rule compliance per item category
CREATE OR REPLACE TABLE compliance AS
SELECT item_category,
       count(*)                                         AS items,
       sum(violates_matching_rule::INT)                 AS violations,
       avg(violates_matching_rule::INT)                 AS violation_rate,
       sum(net_worth_eur) FILTER (violates_matching_rule) AS value_at_risk_eur,
       avg((n_payment_blocks > 0)::INT)                 AS payment_block_rate,
       median(cycle_days)                               AS median_cycle_days
FROM case_summary GROUP BY item_category ORDER BY items DESC;

-- vendor scorecard (vendors with at least 5 items)
CREATE OR REPLACE TABLE vendor_scorecard AS
SELECT vendor,
       count(*)                                  AS items,
       sum(net_worth_eur)                        AS spend_eur,
       avg(violates_matching_rule::INT)          AS violation_rate,
       avg((n_payment_blocks > 0)::INT)          AS payment_block_rate,
       avg((n_price_changes > 0)::INT)           AS price_change_rate,
       median(po_to_gr_days)                     AS median_po_to_gr_days,
       median(cycle_days)                        AS median_cycle_days
FROM case_summary GROUP BY vendor HAVING count(*) >= 5;

-- process variants: distinct activity sequences, most frequent first
CREATE OR REPLACE TABLE variants AS
SELECT trace AS variant, count(*) AS items, count(*) / sum(count(*)) OVER () AS share,
       median(cycle_days) AS median_cycle_days, avg(violates_matching_rule::INT) AS violation_rate
FROM case_summary GROUP BY trace ORDER BY items DESC;

-- monthly KPIs by PO creation month
CREATE OR REPLACE TABLE monthly AS
SELECT date_trunc('month', po_created) AS month, count(*) AS items,
       sum(net_worth_eur) AS spend_eur,
       median(cycle_days) AS median_cycle_days,
       avg(violates_matching_rule::INT) AS violation_rate,
       avg((n_payment_blocks > 0)::INT) AS payment_block_rate
FROM case_summary WHERE po_created IS NOT NULL
GROUP BY ALL ORDER BY month;

-- median duration of each P2P step, per item category
CREATE OR REPLACE TABLE step_durations AS
SELECT item_category, 'PO created → goods receipt' AS step, median(po_to_gr_days) AS median_days,
       quantile_cont(po_to_gr_days, 0.9) AS p90_days, count(po_to_gr_days) AS items FROM case_summary GROUP BY 1
UNION ALL
SELECT item_category, 'Invoice receipt → payment', median(ir_to_clear_days), quantile_cont(ir_to_clear_days, 0.9),
       count(ir_to_clear_days) FROM case_summary GROUP BY 1
UNION ALL
SELECT item_category, 'PO created → payment', median(cycle_days), quantile_cont(cycle_days, 0.9),
       count(cycle_days) FROM case_summary GROUP BY 1;
