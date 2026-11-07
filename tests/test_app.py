"""Smoke test: the dashboard renders without errors on whichever data is present."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(not any((ROOT / "data" / d / "items.parquet").exists() for d in ("app", "app_demo")),
                    reason="no dashboard data; run `make demo` or `make run` first")
def test_dashboard_renders():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
