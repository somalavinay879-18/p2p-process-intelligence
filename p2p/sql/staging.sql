-- Staging: typed, cleanly named tables from the raw XES import.
-- One row per purchase order item (case) and one row per event.

CREATE OR REPLACE TABLE cases AS
SELECT
    concept_name                                  AS case_id,
    purchasing_document                           AS po_number,
    item                                          AS po_item,
    item_category,
    item_type,
    document_type,
    company,
    vendor,
    spend_classification_text                     AS spend_class,
    spend_area_text                               AS spend_area,
    sub_spend_area_text                           AS sub_spend_area,
    lower(coalesce(gr_based_inv_verif, '')) = 'true' AS gr_based_invoice_verification,
    lower(coalesce(goods_receipt, '')) = 'true'      AS goods_receipt_expected
FROM raw_cases;

CREATE OR REPLACE TABLE events_all AS
SELECT
    case_id,
    concept_name                                              AS activity,
    timezone('UTC', CAST(time_timestamp AS TIMESTAMPTZ))      AS ts,
    org_resource                                              AS resource,
    "user"                                                    AS user_id,
    cumulative_net_worth_eur                                  AS net_worth_eur
FROM raw_events;

-- Analysis view: drop exact duplicates and timestamps outside the log period
-- (the real log contains a few events dated decades too early). Both are counted
-- by the data-quality checks, so nothing disappears silently.
CREATE OR REPLACE TABLE events AS
SELECT DISTINCT case_id, activity, ts, resource, user_id, net_worth_eur
FROM events_all
WHERE ts BETWEEN TIMESTAMP '2017-01-01' AND TIMESTAMP '2020-12-31';
