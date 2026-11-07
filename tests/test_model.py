import numpy as np
import pandas as pd

from p2p.model import add_vendor_history, evaluate, load_frame, precision_at, time_split


def test_features_only_use_creation_time_information(db):
    df = load_frame(db)
    assert "Consignment" not in set(df["item_category"])
    assert df["po_created"].is_monotonic_increasing
    # value at creation, not the final cumulative value
    assert df["value_at_creation"].notna().all()


def test_time_split_keeps_order():
    df = pd.DataFrame({"po_created": pd.date_range("2018-01-01", periods=8), "target": [0, 1] * 4})
    tr, te = time_split(df)
    assert tr["po_created"].max() < te["po_created"].min() and len(te) == 2


def test_vendor_history_has_no_leakage():
    train = pd.DataFrame({"vendor": ["a", "a", "b"], "target": [1, 0, 1]})
    test = pd.DataFrame({"vendor": ["a", "c"], "target": [1, 1]})
    add_vendor_history(train, test, prior=1)
    base = 2 / 3
    assert train.loc[0, "vendor_block_rate_hist"] == base               # no earlier "a" item: prior only
    assert train.loc[1, "vendor_block_rate_hist"] == (1 + base) / 2     # sees only the earlier "a" item
    assert test.loc[0, "vendor_block_rate_hist"] == (1 + base) / 3      # all training "a" items
    assert test.loc[1, "vendor_items_hist"] == 0              # unseen vendor


def test_precision_at_top():
    y = np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 1])
    s = np.array([.9, .1, .1, .1, .1, .1, .1, .1, .1, .8])
    assert precision_at(y, s, 0.2) == 1.0


def test_evaluate_runs_end_to_end(db):
    res = evaluate(load_frame(db))
    assert {"baseline_constant", "baseline_vendor_history", "logistic_regression", "gradient_boosting"} \
        <= set(res["models"])
    assert res["n_train"] > res["n_test"] > 0


def test_models_handle_many_categories():
    """The real log has hundreds of spend areas; one-hot output must stay dense for gradient boosting."""
    import pandas as pd
    from p2p.model import CATEGORICAL, NUMERIC, models
    n = 600
    rng = np.random.default_rng(0)
    X = pd.DataFrame({c: [f"{c}_{i % 150}" for i in range(n)] for c in CATEGORICAL})
    for c in NUMERIC:
        X[c] = rng.random(n)
    y = rng.integers(0, 2, n)
    for m in models().values():
        m.fit(X, y)
        assert m.predict_proba(X).shape == (n, 2)
