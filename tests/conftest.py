import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_synthetic import build as make_log  # noqa: E402
from p2p.pipeline import build  # noqa: E402


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    d = tmp_path_factory.mktemp("p2p")
    xes = make_log(d / "synthetic.xes")
    build(xes, d / "p2p.duckdb")
    con = duckdb.connect(str(d / "p2p.duckdb"))
    yield con
    con.close()
