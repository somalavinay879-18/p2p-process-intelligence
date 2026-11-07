"""Predict, at purchase-order creation, which items will get a payment block.

A payment block stops an invoice from being paid until someone resolves it (price
or quantity mismatch, missing goods receipt). Knowing the risky items early lets
purchasing fix the order before the invoice arrives.

Only information available when the PO item is created is used: item category,
document type, spend area, vendor, order value at creation, whether a purchase
requisition preceded it. Vendor history (block rate,
item count) is computed from the training period only, so the test period never
leaks into the features. The split is by time: train on earlier items, test on
later ones.

Right-censoring: items created shortly before the log ends have had no time to get
a block yet (the block rate falls from ~25% to ~7% in the last month). The target is
therefore "payment block within HORIZON days of PO creation", and only items created
at least HORIZON days before the end of the log are used.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 42
CATEGORICAL = ["item_category", "document_type", "spend_area", "spend_class", "company"]
HORIZON_DAYS = 120   # 90% of payment blocks are resolved within ~115 days of PO creation
NUMERIC = ["log_value", "has_requisition", "vendor_items_hist", "vendor_block_rate_hist"]

FEATURE_SQL = """
SELECT c.case_id, c.item_category, c.document_type, c.spend_area, c.spend_class, c.company, c.vendor,
       s.po_created,
       (SELECT arg_min(e.net_worth_eur, e.seq) FROM events_ordered e
         WHERE e.case_id = c.case_id AND e.activity = 'Create Purchase Order Item') AS value_at_creation,
       EXISTS (SELECT 1 FROM events_ordered e WHERE e.case_id = c.case_id
               AND e.activity = 'Create Purchase Requisition Item' AND e.ts <= s.po_created) AS has_requisition,
       EXISTS (SELECT 1 FROM events_ordered e WHERE e.case_id = c.case_id
               AND e.activity IN ('Set Payment Block', 'Remove Payment Block')
               AND e.ts <= s.po_created + INTERVAL ({h}) DAY) AS target
FROM cases c JOIN case_summary s USING (case_id)
WHERE s.po_created IS NOT NULL
  AND c.item_category <> 'Consignment'          -- consignment items are not invoiced per item
  -- enough follow-up time: the log effectively ends at its 99.9th-percentile timestamp
  AND s.po_created <= (SELECT quantile_disc(ts, 0.999) FROM events) - INTERVAL ({h}) DAY
ORDER BY s.po_created, c.case_id
"""


def load_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute(FEATURE_SQL.format(h=HORIZON_DAYS)).df()
    df["log_value"] = np.log1p(df["value_at_creation"].fillna(0).clip(lower=0))
    df["has_requisition"] = df["has_requisition"].astype(int)
    df["target"] = df["target"].astype(int)
    for col in CATEGORICAL + ["vendor"]:
        df[col] = df[col].fillna("unknown").astype(str)
    return df


def time_split(df: pd.DataFrame, test_share: float = 0.25) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Earliest (1 - test_share) of items by creation time for training, the rest for testing."""
    cut = int(len(df) * (1 - test_share))
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def add_vendor_history(train: pd.DataFrame, test: pd.DataFrame, prior: int = 20) -> None:
    """Vendor block rate, smoothed towards the overall rate.

    Training rows only see the vendor's *earlier* items (expanding history in creation
    order), as at prediction time. A leave-one-out rate would leak the label: within one
    vendor, blocked items would always get a slightly lower rate than unblocked ones,
    and a tree model learns exactly that inverted pattern. Test rows use the whole
    training period.
    """
    base = train["target"].mean()
    grp = train.groupby("vendor")["target"]
    prev_sum = grp.cumsum() - train["target"]
    prev_n = grp.cumcount()
    train["vendor_items_hist"] = prev_n
    train["vendor_block_rate_hist"] = (prev_sum + prior * base) / (prev_n + prior)
    g = grp.agg(["sum", "count"])
    test["vendor_items_hist"] = test["vendor"].map(g["count"]).fillna(0)
    test["vendor_block_rate_hist"] = ((test["vendor"].map(g["sum"]).fillna(0) + prior * base)
                                      / (test["vendor_items_hist"] + prior))


def _pre():
    return ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20, sparse_output=False), CATEGORICAL),
        ("num", StandardScaler(), NUMERIC),
    ], sparse_threshold=0)   # dense output: gradient boosting does not accept sparse matrices


def models() -> dict:
    return {
        "logistic_regression": make_pipeline(_pre(), LogisticRegression(max_iter=2000, class_weight="balanced")),
        "gradient_boosting": make_pipeline(_pre(), HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, random_state=SEED)),
    }


def precision_at(y: np.ndarray, score: np.ndarray, share: float = 0.1) -> float:
    """Share of true blocks among the top `share` highest-risk items (what a buyer would review)."""
    k = max(1, int(len(y) * share))
    tiebreak = np.random.default_rng(SEED).random(len(y))   # ties (e.g. a constant score) broken at random
    return float(y[np.lexsort((tiebreak, -score))[:k]].mean())


def evaluate(df: pd.DataFrame, scores: dict | None = None) -> dict:
    """Train on the earlier items, score the later ones. If `scores` is a dict, it receives the
    scored test frame and the logistic-regression coefficients for the dashboard."""
    train, test = time_split(df)
    add_vendor_history(train, test)
    y_tr, y_te = train["target"].to_numpy(), test["target"].to_numpy()
    out = {"target": f"payment block within {HORIZON_DAYS} days of PO creation",
           "n_train": len(train), "n_test": len(test),
           "block_rate_train": float(y_tr.mean()), "block_rate_test": float(y_te.mean()),
           "train_period": [str(train["po_created"].min()), str(train["po_created"].max())],
           "test_period": [str(test["po_created"].min()), str(test["po_created"].max())],
           "models": {}}

    def score(name, s):
        both = len(set(y_te)) > 1
        out["models"][name] = {
            "roc_auc": float(roc_auc_score(y_te, s)) if both else None,
            "pr_auc": float(average_precision_score(y_te, s)) if both else None,
            "precision_top10": precision_at(y_te, s),
        }

    # Baselines: constant rate (= random ranking) and the vendor's historical block rate alone
    score("baseline_constant", np.full(len(test), y_tr.mean()))   # no ranking: ROC-AUC 0.5, PR-AUC = block rate
    score("baseline_vendor_history", test["vendor_block_rate_hist"].to_numpy())
    fitted = {}
    for name, m in models().items():
        m.fit(train[CATEGORICAL + NUMERIC], y_tr)
        fitted[name] = m.predict_proba(test[CATEGORICAL + NUMERIC])[:, 1]
        score(name, fitted[name])
    if scores is not None:
        scored = test[["case_id", "po_created", "vendor", "item_category", "spend_area", "value_at_creation",
                       "vendor_block_rate_hist", "target"]].copy()
        scored["risk"] = fitted["logistic_regression"]
        scores["test"] = scored.reset_index(drop=True)
        lr = models()["logistic_regression"].fit(train[CATEGORICAL + NUMERIC], y_tr)
        names = lr[0].get_feature_names_out()
        scores["coefficients"] = pd.DataFrame({"feature": names, "coefficient": lr[-1].coef_[0]})
    return out


def run(db_path: str | Path, report_dir: str | Path, app_dir: str | Path | None = None) -> dict:
    con = duckdb.connect(str(db_path), read_only=True)
    df = load_frame(con)
    con.close()
    scores: dict = {}
    res = evaluate(df, scores)
    if app_dir is not None:
        Path(app_dir).mkdir(parents=True, exist_ok=True)
        scores["test"].to_parquet(Path(app_dir) / "risk_scores.parquet", index=False)
        scores["coefficients"].to_parquet(Path(app_dir) / "model_coefficients.parquet", index=False)
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    (Path(report_dir) / "model_payment_block.json").write_text(json.dumps(res, indent=2))
    return res
