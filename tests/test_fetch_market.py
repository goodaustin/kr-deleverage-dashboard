import pytest
from src.fetch_market import fetch_market


@pytest.mark.network
def test_fetch_market_recent_shape():
    df = fetch_market("20260701", "20260710")
    assert set(["kospi_idx", "kosdaq_idx", "mcap", "turn_val"]).issubset(df.columns)
    assert df.index.name == "date"
    assert (df["kospi_idx"] > 0).all()
    assert (df["mcap"] > 1000).all()  # KOSPI+KOSDAQ 市值必 > 1000조
    assert df.index.max() <= "20260710"
