"""Load the BPI Challenge 2019 event log (XES) into DuckDB.

The XES file is parsed as a stream (one trace at a time), so the 1.5 million events
fit in memory on a laptop. Output: two Parquet files and a DuckDB database with
raw_cases (one row per purchase order item) and raw_events (one row per event).
"""
from __future__ import annotations

import gzip
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

TYPES = {"string", "date", "int", "float", "boolean", "id"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _open(path: Path):
    """Open .xes, .xes.gz or a .zip containing one .xes file."""
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    if path.suffix == ".zip":
        z = zipfile.ZipFile(path)
        name = next(n for n in z.namelist() if n.lower().endswith(".xes"))
        return z.open(name)
    return open(path, "rb")


def _attr(el) -> tuple[str, object] | None:
    kind = _local(el.tag)
    if kind not in TYPES:
        return None
    key, value = el.get("key"), el.get("value")
    if kind in ("int",):
        value = int(value)
    elif kind == "float":
        value = float(value)
    elif kind == "boolean":
        value = value.lower() == "true"
    return key, value


def parse_xes(path: str | Path) -> tuple[list[dict], list[dict]]:
    """Return (cases, events). One trace is processed and freed at a time.

    Case attributes keep their XES keys (case id = concept:name); every event gets
    the case id in "case_id".
    """
    cases, events = [], []
    with _open(Path(path)) as fh:
        context = ET.iterparse(fh, events=("end",))
        for _, el in context:
            if _local(el.tag) != "trace":
                continue
            case: dict = {}
            trace_events = []
            for child in el:
                if _local(child.tag) == "event":
                    ev = {}
                    for a in child:
                        kv = _attr(a)
                        if kv:
                            ev[kv[0]] = kv[1]
                    trace_events.append(ev)
                else:
                    kv = _attr(child)
                    if kv:
                        case[kv[0]] = kv[1]
            case_id = case.get("concept:name")
            for ev in trace_events:
                ev["case_id"] = case_id
            cases.append(case)
            events.extend(trace_events)
            el.clear()
    return cases, events


def _norm(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "_" for c in name.replace(":", "_"))
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _table(rows: list[dict]) -> pa.Table:
    """Build an Arrow table with snake_case column names; all columns as text except numbers."""
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    cols = {}
    for k in keys:
        vals = [r.get(k) for r in rows]
        if all(v is None or isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            cols[_norm(k)] = pa.array(vals, type=pa.float64())
        else:
            cols[_norm(k)] = pa.array([None if v is None else str(v) for v in vals], type=pa.string())
    return pa.table(cols)


def load(xes_path: str | Path, db_path: str | Path) -> dict:
    """Parse the XES file and write raw_cases / raw_events into DuckDB. Returns row counts."""
    cases, events = parse_xes(xes_path)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cases_pq, events_pq = db_path.with_name("raw_cases.parquet"), db_path.with_name("raw_events.parquet")
    pq.write_table(_table(cases), cases_pq)
    pq.write_table(_table(events), events_pq)
    con = duckdb.connect(str(db_path))
    con.execute(f"CREATE OR REPLACE TABLE raw_cases AS SELECT * FROM read_parquet('{cases_pq}')")
    con.execute(f"CREATE OR REPLACE TABLE raw_events AS SELECT * FROM read_parquet('{events_pq}')")
    counts = {"cases": con.execute("SELECT count(*) FROM raw_cases").fetchone()[0],
              "events": con.execute("SELECT count(*) FROM raw_events").fetchone()[0]}
    con.close()
    return counts
