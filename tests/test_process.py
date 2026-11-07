def test_matching_violations_match_the_planted_ones(db):
    rows = dict(db.execute("SELECT item_category, violations FROM compliance").fetchall())
    assert rows["3-way match, invoice after GR"] == 5     # i % 8 == 0 for 40 items
    assert rows["3-way match, invoice before GR"] == 0
    assert rows["2-way match"] == 0 and rows["Consignment"] == 0


def test_payment_blocks_counted(db):
    rate = db.execute("SELECT payment_block_rate FROM compliance "
                      "WHERE item_category = '3-way match, invoice before GR'").fetchone()[0]
    assert rate == 8 / 40


def test_cycle_time_runs_from_po_creation_to_payment(db):
    bad = db.execute("SELECT count(*) FROM case_summary WHERE cycle_days < 0").fetchone()[0]
    assert bad == 0
    consign = db.execute("SELECT count(*) FROM case_summary WHERE item_category = 'Consignment' "
                         "AND cycle_days IS NOT NULL").fetchone()[0]
    assert consign == 0   # consignment items are not invoiced per item


def test_same_timestamp_events_follow_p2p_order(db):
    seqs = db.execute("SELECT activity FROM events_ordered WHERE case_id = '4509999999_00010' ORDER BY seq").fetchall()
    assert [s[0] for s in seqs] == ["Record Invoice Receipt", "Clear Invoice"]


def test_dfg_and_variants(db):
    total_pairs = db.execute("SELECT sum(frequency) FROM dfg").fetchone()[0]
    events, cases = db.execute("SELECT count(*), count(DISTINCT case_id) FROM events_ordered").fetchone()
    assert total_pairs == events - cases            # n-1 transitions per case
    assert abs(db.execute("SELECT sum(share) FROM variants").fetchone()[0] - 1) < 1e-9
