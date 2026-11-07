from p2p.ingest import _norm, parse_xes
from p2p.quality import run_checks


def test_parser_reads_cases_and_events(tmp_path):
    from make_synthetic import build as make_log
    cases, events = parse_xes(make_log(tmp_path / "x.xes", n_per_category=2))
    assert len(cases) == 4 * 2 + 1
    assert all(e["case_id"] for e in events)
    assert cases[0]["Item Category"] == "3-way match, invoice after GR"
    assert isinstance(events[0]["Cumulative net worth (EUR)"], float)


def test_column_names_are_normalised():
    assert _norm("Cumulative net worth (EUR)") == "cumulative_net_worth_eur"
    assert _norm("time:timestamp") == "time_timestamp"
    assert _norm("GR-Based Inv. Verif.") == "gr_based_inv_verif"


def test_staging_types(db):
    row = db.execute("SELECT typeof(ts), typeof(net_worth_eur) FROM events LIMIT 1").fetchone()
    assert row == ("TIMESTAMP", "DOUBLE")
    assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 161


def test_quality_checks_find_the_planted_problems(db):
    res = {r["check"]: r["rows"] for r in run_checks(db)}
    assert res["timestamps_out_of_range"] == 1      # the 1948 event
    assert res["duplicate_events"] == 1
    assert res["cases_without_po_creation"] == 1    # its creation event was the 1948 one
    assert res["duplicate_case_ids"] == res["events_without_case"] == res["unknown_item_category"] == 0


def test_clean_events_exclude_bad_rows(db):
    assert db.execute("SELECT count(*) FROM events WHERE year(ts) < 2017").fetchone()[0] == 0
    total, distinct = db.execute("SELECT count(*), count(DISTINCT (case_id, activity, ts)) FROM events").fetchone()
    assert total == distinct
