import json
import re
import pathlib

import numpy as np
import pandas as pd

from src import update as U
from src.fetch_credit import CreditFetchError
from src.fetch_market import MarketFetchError


def test_merge_prefers_new_but_keeps_old_credit_on_nan():
    existing = pd.DataFrame(
        {
            "margin_total": [35.0], "margin_kospi": [28.0], "margin_kosdaq": [7.0],
            "deposit": [100.0], "misu": [1.0], "bandae_amt": [800.0],
            "kospi_idx": [7000.0], "kosdaq_idx": [780.0],
            "mcap": [np.nan], "turn_val": [np.nan],
        },
        index=pd.Index(["20260713"], name="date"),
    )
    # credit fetch failed for 20260713 (all credit cols NaN) but market fetch succeeded
    # (kospi/kosdaq present); 20260714 is a brand-new date from market only.
    recent = pd.DataFrame(
        {
            "margin_total": [np.nan, np.nan], "margin_kospi": [np.nan, np.nan], "margin_kosdaq": [np.nan, np.nan],
            "deposit": [np.nan, np.nan], "misu": [np.nan, np.nan], "bandae_amt": [np.nan, np.nan],
            "kospi_idx": [3000.0, 3100.0], "kosdaq_idx": [900.0, 910.0],
            "mcap": [np.nan, np.nan], "turn_val": [np.nan, np.nan],
        },
        index=pd.Index(["20260713", "20260714"], name="date"),
    )

    merged = U.merge_recent(existing, recent)

    assert list(merged.index) == ["20260713", "20260714"]
    # old credit value preserved, not clobbered by the new NaN
    assert merged.loc["20260713", "margin_total"] == 35.0
    # new market value applied
    assert merged.loc["20260713", "kospi_idx"] == 3000.0
    # brand-new date appended
    assert merged.loc["20260714", "kospi_idx"] == 3100.0
    assert pd.isna(merged.loc["20260714", "margin_total"])


def _make_tmp_daily_csv(path: pathlib.Path) -> None:
    dates = [f"202607{d:02d}" for d in range(1, 11)]  # 20260701..20260710, 10 rows
    df = pd.DataFrame(
        {
            "margin_total": np.linspace(34.0, 35.0, 10),
            "margin_kospi": np.linspace(27.0, 28.0, 10),
            "margin_kosdaq": np.linspace(7.0, 7.5, 10),
            "deposit": np.linspace(100.0, 105.0, 10),
            "misu": np.linspace(1.0, 1.4, 10),
            "bandae_amt": np.linspace(500.0, 800.0, 10),
            "kospi_idx": np.linspace(7000.0, 7400.0, 10),
            "kosdaq_idx": np.linspace(770.0, 800.0, 10),
            "mcap": [np.nan] * 10,
            "turn_val": [np.nan] * 10,
        },
        index=pd.Index(dates, name="date"),
    )
    df.to_csv(path, index_label="date")


def _make_tmp_index_html(path: pathlib.Path) -> None:
    path.write_text(
        "<!doctype html><html><body><script>"
        "/*IND-START*/const IND = {};/*IND-END*/"
        "</script></body></html>",
        encoding="utf-8",
    )


def _read_ind(html_path: pathlib.Path) -> dict:
    html = html_path.read_text(encoding="utf-8")
    m = re.search(r"/\*IND-START\*/const IND = (.*?);/\*IND-END\*/", html, re.S)
    assert m is not None
    return json.loads(m.group(1))


def test_degrades_when_credit_fails(monkeypatch, tmp_path):
    tmp_csv = tmp_path / "daily.csv"
    tmp_html = tmp_path / "index.html"
    _make_tmp_daily_csv(tmp_csv)
    _make_tmp_index_html(tmp_html)

    small_market = pd.DataFrame(
        {"kospi_idx": [7500.0], "kosdaq_idx": [810.0], "mcap": [np.nan], "turn_val": [np.nan]},
        index=pd.Index(["20260711"], name="date"),
    )
    monkeypatch.setattr(U, "fetch_market", lambda s, e: small_market)

    def boom(s, e):
        raise CreditFetchError("down")

    monkeypatch.setattr(U, "fetch_credit", boom)

    changed = U.main(csv_path=str(tmp_csv), html_path=str(tmp_html))

    assert changed is True

    ind = _read_ind(tmp_html)
    assert ind["partial"] is True

    result_df = pd.read_csv(tmp_csv, index_col="date", dtype={"date": str})
    assert "20260711" in result_df.index
    # credit fetch failed -> new row has no credit data
    assert pd.isna(result_df.loc["20260711", "margin_total"])


def test_degrades_when_market_fails(monkeypatch, tmp_path):
    """market fetch raises MarketFetchError; credit fetch still succeeds.

    Regression for the _empty_frame object-dtype bug: an empty market frame used
    to default to object dtype, which combine_first-contaminated the float columns
    on merge, crashing indicators.derive()'s np.log(kospi_idx) with a TypeError.
    main() must not crash, must still write output, and the resulting IND must be
    partial (credit-only data flowing through derive() without a dtype crash).
    """
    tmp_csv = tmp_path / "daily.csv"
    tmp_html = tmp_path / "index.html"
    _make_tmp_daily_csv(tmp_csv)
    _make_tmp_index_html(tmp_html)

    def boom(s, e):
        raise MarketFetchError("down")

    monkeypatch.setattr(U, "fetch_market", boom)

    small_credit = pd.DataFrame(
        {
            "margin_total": [35.2], "margin_kospi": [28.1], "margin_kosdaq": [7.1],
            "deposit": [106.0], "misu": [1.35], "bandae_amt": [700.0],
        },
        index=pd.Index(["20260711"], name="date"),
    )
    monkeypatch.setattr(U, "fetch_credit", lambda s, e: small_credit)

    changed = U.main(csv_path=str(tmp_csv), html_path=str(tmp_html))

    assert changed is True

    ind = _read_ind(tmp_html)
    assert ind["partial"] is True

    result_df = pd.read_csv(tmp_csv, index_col="date", dtype={"date": str})
    assert "20260711" in result_df.index
    # market fetch failed -> new row has no market data
    assert pd.isna(result_df.loc["20260711", "kospi_idx"])
    # credit fetch succeeded -> new row has credit data
    assert result_df.loc["20260711", "margin_total"] == 35.2


def test_both_fetches_fail_leaves_output_untouched(monkeypatch, tmp_path):
    """Safety net: if BOTH sources fail there is nothing new to merge in —
    daily.csv and index.html must be left byte-for-byte untouched, and main()
    must return False (no update) rather than crash or write garbage."""
    tmp_csv = tmp_path / "daily.csv"
    tmp_html = tmp_path / "index.html"
    _make_tmp_daily_csv(tmp_csv)
    _make_tmp_index_html(tmp_html)

    csv_before = tmp_csv.read_bytes()
    html_before = tmp_html.read_bytes()

    def market_boom(s, e):
        raise MarketFetchError("down")

    def credit_boom(s, e):
        raise CreditFetchError("down")

    monkeypatch.setattr(U, "fetch_market", market_boom)
    monkeypatch.setattr(U, "fetch_credit", credit_boom)

    changed = U.main(csv_path=str(tmp_csv), html_path=str(tmp_html))

    assert changed is False
    assert tmp_csv.read_bytes() == csv_before
    assert tmp_html.read_bytes() == html_before
