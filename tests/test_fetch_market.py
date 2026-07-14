import json
import math
from pathlib import Path

import pytest

from src.fetch_market import fetch_market, parse_yahoo_chart

_FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_KS11.json"


def test_parse_yahoo_chart_offline():
    """Pure parser on a captured live Yahoo chart response (^KS11, 2026-07-01..2026-07-13)."""
    obj = json.loads(_FIXTURE.read_text())
    s = parse_yahoo_chart(obj)
    assert s.index.name == "date"
    assert list(s.index) == sorted(s.index)  # ascending
    assert "20260710" in s.index
    val = s.loc["20260710"]
    assert 1000 < val < 20000  # plausible KOSPI level
    assert math.isclose(val, 7475.93994140625, rel_tol=1e-6)


@pytest.mark.network
def test_fetch_market_recent_shape():
    df = fetch_market("20260701", "20260713")
    assert list(df.columns) == ["kospi_idx", "kosdaq_idx", "mcap", "turn_val"]
    assert df.index.name == "date"
    assert (df["kospi_idx"] > 0).all()
    assert df["mcap"].isna().all()
    assert df["turn_val"].isna().all()
