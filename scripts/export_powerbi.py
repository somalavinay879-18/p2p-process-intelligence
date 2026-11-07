"""Export a star-schema workbook for the Power BI version of the dashboard.

    python scripts/export_powerbi.py                 # after `make run`
    -> powerbi/P2P_PowerBI_Model.xlsx

One sheet per model table. Fact table: one row per PO item. Dimensions: date, vendor,
matching type, spend area. Small helper tables: process flow (directly-follows),
variants, model results, risk drivers, data quality.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "p2p.duckdb"
APP = ROOT / "data" / "app"
OUT = ROOT / "powerbi" / "P2P_PowerBI_Model.xlsx"

SHORT = {"Create Purchase Requisition Item": "Requisition", "Create Purchase Order Item": "PO created",
         "Record Goods Receipt": "Goods receipt", "Record Invoice Receipt": "Invoice receipt",
         "Vendor creates invoice": "Vendor invoice", "Clear Invoice": "Payment",
         "Remove Payment Block": "Block removed", "Set Payment Block": "Block set",
         "Record Service Entry Sheet": "Service entry sheet", "Receive Order Confirmation": "Order confirmation"}
STEP_ORDER = {"Requisition": 1, "PO created": 2, "Order confirmation": 3, "Vendor invoice": 4, "Goods receipt": 5,
              "Service entry sheet": 6, "Invoice receipt": 7, "Block set": 8, "Block removed": 9, "Payment": 10}
RULES = {
    "3-way match, invoice before GR": ("3-way, invoice first", 1, "Invoice may arrive first; payment needs the goods receipt"),
    "3-way match, invoice after GR": ("3-way, GR first", 2, "Invoice may only be recorded after the goods receipt"),
    "Consignment": ("Consignment", 3, "No invoice per item"),
    "2-way match": ("2-way", 4, "No goods receipt expected"),
}


def main(db_path: Path = DB, out: Path = OUT) -> Path:
    con = duckdb.connect(str(db_path), read_only=True)
    variants = con.execute("""SELECT trace, row_number() OVER (ORDER BY count(*) DESC) AS rank, count(*) AS items,
                                     median(cycle_days) AS median_days
                              FROM case_summary GROUP BY trace""").df()
    fact = con.execute("""
        SELECT s.case_id AS CaseID, CAST(s.po_created AS DATE) AS PODate, s.vendor AS VendorID,
               s.item_category AS MatchingType, s.spend_area AS SpendArea, s.document_type AS DocumentType,
               s.company AS Company, s.net_worth_eur AS OrderValue,
               s.violates_matching_rule::INT AS IsViolation, (s.n_payment_blocks > 0)::INT AS IsBlocked,
               (s.n_price_changes > 0)::INT AS HasPriceChange, s.is_paid::INT AS IsPaid,
               round(s.po_to_gr_days, 2) AS DaysToGoodsReceipt,
               round(date_diff('hour', s.po_created, s.first_ir) / 24.0, 2) AS DaysToInvoiceReceipt,
               round(s.ir_to_clear_days, 2) AS DaysInvoiceToPayment, round(s.cycle_days, 2) AS DaysToPayment,
               s.trace
        FROM case_summary s WHERE s.po_created IS NOT NULL ORDER BY s.po_created, s.case_id""").df()
    flow = con.execute("""
        SELECT c.item_category AS MatchingType, e1.activity AS src, e2.activity AS dst, count(*) AS Transitions,
               round(median(date_diff('hour', e1.ts, e2.ts)) / 24.0, 2) AS MedianDays
        FROM events_ordered e1 JOIN events_ordered e2 ON e1.case_id = e2.case_id AND e2.seq = e1.seq + 1
        JOIN cases c ON c.case_id = e1.case_id GROUP BY ALL""").df()
    con.close()

    for col in ["SpendArea", "VendorID", "DocumentType", "Company"]:
        fact[col] = fact[col].replace("", None).fillna("Unknown")

    # fact: variant rank, model risk score for the test period
    vr = dict(zip(variants["trace"], variants["rank"]))
    fact["VariantRank"] = fact.pop("trace").map(vr).where(lambda r: r <= 50, 0).astype(int)   # 0 = "Other"
    risk = pd.read_parquet(APP / "risk_scores.parquet")[["case_id", "risk", "target"]]
    fact = fact.merge(risk.rename(columns={"case_id": "CaseID", "risk": "RiskScore", "target": "BlockedWithin120Days"}),
                      on="CaseID", how="left")
    fact["InTestSet"] = fact["RiskScore"].notna().astype(int)
    # rank 1 = riskiest item of the test period; precomputed so Power BI needs no expensive RANKX column
    fact["RiskRank"] = fact["RiskScore"].rank(ascending=False, method="first").astype("Int64")
    fact.insert(1, "PONumber", fact["CaseID"].str.split("_").str[0])

    # dimensions
    dates = pd.DataFrame({"Date": pd.date_range("2018-01-01", "2019-01-31", freq="D")})
    dates["Year"] = dates["Date"].dt.year
    dates["MonthNumber"] = dates["Date"].dt.month
    dates["MonthStart"] = dates["Date"].dt.to_period("M").dt.to_timestamp()
    dates["Month"] = dates["Date"].dt.strftime("%b %Y")
    dates["MonthSort"] = dates["Year"] * 100 + dates["MonthNumber"]
    dates["Quarter"] = "Q" + dates["Date"].dt.quarter.astype(str) + " " + dates["Year"].astype(str)
    dates["Weekday"] = dates["Date"].dt.strftime("%a")
    dates["WeekdayNumber"] = dates["Date"].dt.day_of_week + 1
    dates["IsCensored"] = (dates["Date"] >= "2018-11-01").astype(int)   # too recent to be blocked or paid yet
    dates["Date"] = dates["Date"].dt.date
    dates["MonthStart"] = dates["MonthStart"].dt.date

    vendors = (fact.groupby("VendorID").agg(FirstOrder=("PODate", "min"), ItemsAll=("CaseID", "size"))
               .reset_index())
    vendors["VendorSize"] = pd.cut(vendors["ItemsAll"], [0, 10, 100, 1000, 10**9],
                                   labels=["1-10 items", "11-100 items", "101-1,000 items", "1,000+ items"]).astype(str)
    vendors = vendors.drop(columns="ItemsAll")
    matching = pd.DataFrame([{"MatchingType": k, "ShortName": v[0], "SortOrder": v[1], "Rule": v[2]}
                             for k, v in RULES.items()])
    areas = pd.DataFrame({"SpendArea": sorted(fact["SpendArea"].dropna().unique())})

    flow["From"] = flow.pop("src").map(lambda a: SHORT.get(a, a))
    flow["To"] = flow.pop("dst").map(lambda a: SHORT.get(a, a))
    flow["FromOrder"] = flow["From"].map(STEP_ORDER).fillna(99).astype(int)
    flow["ToOrder"] = flow["To"].map(STEP_ORDER).fillna(99).astype(int)
    flow["IsSlow"] = (flow["MedianDays"] > 14).astype(int)
    flow = flow[["MatchingType", "From", "To", "FromOrder", "ToOrder", "Transitions", "MedianDays", "IsSlow"]]

    var = variants[variants["rank"] <= 50].copy()
    var["Variant"] = var["trace"].map(lambda t: " → ".join(SHORT.get(a, a) for a in t.split(" > ")))
    var["Share"] = var["items"] / variants["items"].sum()
    var = var.rename(columns={"rank": "VariantRank", "items": "Items", "median_days": "MedianDaysToPay"})
    var = pd.concat([var[["VariantRank", "Variant", "Items", "Share", "MedianDaysToPay"]],
                     pd.DataFrame([{"VariantRank": 0, "Variant": "Other (11,000+ rare variants)",
                                    "Items": int(variants.loc[variants["rank"] > 50, "items"].sum()),
                                    "Share": float(variants.loc[variants["rank"] > 50, "items"].sum() / variants["items"].sum()),
                                    "MedianDaysToPay": None}])])

    model = json.loads((ROOT / "reports" / "model_payment_block.json").read_text())
    results = pd.DataFrame([{"Model": k.replace("baseline_", "Baseline: ").replace("_", " ").capitalize(),
                             "ROC_AUC": v["roc_auc"], "PR_AUC": v["pr_auc"], "HitRateTop10": v["precision_top10"]}
                            for k, v in model["models"].items()])
    coef = pd.read_parquet(APP / "model_coefficients.parquet")
    coef = coef[~coef["feature"].str.startswith("cat__company")]
    coef["Driver"] = (coef["feature"].str.replace("cat__", "").str.replace("num__", "")
                      .str.replace("infrequent_sklearn", "other")
                      .str.replace("item_category_", "Matching: ").str.replace("document_type_", "Document: ")
                      .str.replace("spend_area_", "Spend area: ").str.replace("spend_class_", "Spend class: ")
                      .str.replace("vendor_block_rate_hist", "Vendor's past block rate")
                      .str.replace("vendor_items_hist", "Vendor's past item count")
                      .str.replace("log_value", "Order value (log)").str.replace("has_requisition", "Has a requisition"))
    drivers = coef.rename(columns={"coefficient": "Weight"})[["Driver", "Weight"]]
    drivers["Direction"] = drivers["Weight"].map(lambda w: "Raises risk" if w > 0 else "Lowers risk")
    dq = pd.DataFrame(json.loads((ROOT / "reports" / "data_quality.json").read_text()))
    dq = dq.rename(columns={"check": "Check", "severity": "Severity", "rows": "Rows", "passed": "Passed", "meaning": "Meaning"})
    dq["Passed"] = dq["Passed"].astype(int)

    sheets = {"FactPOItem": fact, "DimDate": dates, "DimVendor": vendors, "DimMatchingType": matching,
              "DimSpendArea": areas, "ProcessFlow": flow, "Variants": var, "ModelResults": results,
              "RiskDrivers": drivers, "DataQuality": dq}
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="xlsxwriter") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
    for name, df in sheets.items():
        print(f"  {name:16s} {len(df):>8,} rows")
    return out


if __name__ == "__main__":
    print(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DB))
