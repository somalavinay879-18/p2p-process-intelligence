"""Write a small synthetic event log in the exact format of the BPI Challenge 2019 XES file.

Used by the tests and for a quick demo without the 700 MB original. Every rule the
analysis checks (3-way match order, payment blocks, data-quality problems) appears
here on purpose, so the expected results are known.

    python scripts/make_synthetic.py data/raw/synthetic.xes
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import quoteattr

CATS = ["3-way match, invoice after GR", "3-way match, invoice before GR", "2-way match", "Consignment"]
SPEND = [("Packaging", "Labels"), ("Logistics", "Road Packed"), ("Sales", "Promotion"), ("Metal Products", "Steel")]


def _a(kind: str, key: str, value) -> str:
    if kind == "date":
        value = value.strftime("%Y-%m-%dT%H:%M:%S.000+01:00")
    if kind == "boolean":
        value = "true" if value else "false"
    return f'<{kind} key={quoteattr(key)} value={quoteattr(str(value))}/>'


def _flow(cat: str, rng: random.Random, start: datetime, violation: bool, blocked: bool):
    """Return [(activity, timestamp)] for one purchase order item."""
    t = start
    steps = []

    def add(act, days):
        nonlocal t
        t = t + timedelta(days=days, hours=rng.randint(0, 8))
        steps.append((act, t))

    if rng.random() < 0.5:
        steps.append(("Create Purchase Requisition Item", t))
        add("Create Purchase Order Item", rng.randint(1, 5))
    else:
        steps.append(("Create Purchase Order Item", t))
    if cat == "Consignment":
        add("Record Goods Receipt", rng.randint(5, 20))
        return steps
    add("Vendor creates invoice", rng.randint(3, 25))
    if cat == "3-way match, invoice after GR":
        if violation:   # invoice recorded before the goods arrive: not allowed in this category
            add("Record Invoice Receipt", rng.randint(1, 3))
            add("Record Goods Receipt", rng.randint(2, 10))
        else:
            add("Record Goods Receipt", rng.randint(1, 10))
            add("Record Invoice Receipt", rng.randint(1, 5))
    elif cat == "3-way match, invoice before GR":
        add("Record Invoice Receipt", rng.randint(1, 5))
        add("Record Goods Receipt", rng.randint(1, 15))
    else:  # 2-way match: no goods receipt
        add("Record Invoice Receipt", rng.randint(1, 5))
    if blocked:
        add("Set Payment Block", 1)
        add("Remove Payment Block", rng.randint(5, 30))
    add("Clear Invoice", rng.randint(10, 40))
    return steps


def build(path: str | Path, n_per_category: int = 40, seed: int = 42) -> Path:
    rng = random.Random(seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<log xes.version="1.0" xmlns="http://www.xes-standard.org/">']
    n = 0
    for c, cat in enumerate(CATS):
        for i in range(n_per_category):
            n += 1
            doc, item = f"45070{n:05d}", f"{(i % 3 + 1) * 10:05d}"
            vendor = f"vendorID_{rng.randint(0, 9):04d}"
            area, sub = SPEND[(n + c) % len(SPEND)]
            start = datetime(2018, 1, 1) + timedelta(days=rng.randint(0, 330))
            violation = cat == "3-way match, invoice after GR" and i % 8 == 0     # 5 of 40
            blocked = cat != "Consignment" and i % 5 == 0                          # 8 of 40 per category
            value = round(rng.uniform(50, 5000), 2)
            gr = cat != "2-way match"
            out.append("<trace>")
            out += [
                _a("string", "concept:name", f"{doc}_{item}"),
                _a("string", "Purchasing Document", doc), _a("string", "Item", item),
                _a("string", "Item Type", "Consignment" if cat == "Consignment" else "Standard"),
                _a("boolean", "GR-Based Inv. Verif.", cat == "3-way match, invoice after GR"),
                _a("boolean", "Goods Receipt", gr),
                _a("string", "Source", "sourceSystemID_0000"),
                _a("string", "Doc. Category name", "Purchase order"),
                _a("string", "Company", "companyID_0000"),
                _a("string", "Spend classification text", "PR" if c % 2 else "NPR"),
                _a("string", "Spend area text", area), _a("string", "Sub spend area text", sub),
                _a("string", "Vendor", vendor), _a("string", "Name", vendor.replace("ID", "")),
                _a("string", "Document Type", "Standard PO"), _a("string", "Item Category", cat),
            ]
            for act, ts in _flow(cat, rng, start, violation, blocked):
                out += ["<event>", _a("string", "concept:name", act), _a("date", "time:timestamp", ts),
                        _a("string", "org:resource", f"user_{rng.randint(0, 20):03d}"),
                        _a("string", "User", f"user_{rng.randint(0, 20):03d}"),
                        _a("float", "Cumulative net worth (EUR)", value), "</event>"]
            out.append("</trace>")
    # Known data-quality problems, as in the real log: a timestamp decades too early and a duplicate event
    out.append("<trace>" + _a("string", "concept:name", "4509999999_00010") + _a("string", "Item Category", CATS[2])
               + _a("string", "Vendor", "vendorID_0001") + _a("string", "Spend area text", "Sales")
               + "".join(["<event>" + _a("string", "concept:name", a) + _a("date", "time:timestamp", d)
                          + _a("float", "Cumulative net worth (EUR)", 100.0) + "</event>"
                          for a, d in [("Create Purchase Order Item", datetime(1948, 1, 26)),
                                       ("Record Invoice Receipt", datetime(2018, 3, 1)),
                                       ("Record Invoice Receipt", datetime(2018, 3, 1)),
                                       ("Clear Invoice", datetime(2018, 4, 1))]]) + "</trace>")
    out.append("</log>")
    path.write_text("\n".join(out))
    return path


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "data/raw/synthetic.xes"))
