import json
import pathlib

import pytest

from src.fetch_credit import parse_service, fetch_credit, CreditFetchError

FIXTURES = pathlib.Path("tests/fixtures")

MARGIN_COLMAP = {
    "TMPV2": "margin_total",
    "TMPV3": "margin_kospi",
    "TMPV4": "margin_kosdaq",
}
DEPOSIT_COLMAP = {
    "TMPV2": "deposit",
    "TMPV5": "misu",
    "TMPV6": "bandae_amt",
}


def _load(name):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def test_parse_service_margin_columns_and_index():
    obj = _load("freesis_STATSCU0100000070.json")
    df = parse_service(obj, MARGIN_COLMAP)
    assert df.index.name == "date"
    assert set(["margin_total", "margin_kospi", "margin_kosdaq"]).issubset(df.columns)
    assert list(df.index) == sorted(df.index)  # ascending (oldest first)


def test_parse_service_margin_known_value():
    obj = _load("freesis_STATSCU0100000070.json")
    df = parse_service(obj, MARGIN_COLMAP)
    row = df.loc["20260710"]
    assert row["margin_total"] == pytest.approx(35.574, abs=1e-3)
    assert row["margin_kospi"] == pytest.approx(28.0196, abs=1e-3)
    assert row["margin_kosdaq"] == pytest.approx(7.5543, abs=1e-3)


def test_parse_service_deposit_known_value():
    obj = _load("freesis_STATSCU0100000060.json")
    df = parse_service(obj, DEPOSIT_COLMAP)
    row = df.loc["20260710"]
    assert row["deposit"] == pytest.approx(105.576, abs=1e-3)
    assert row["misu"] == pytest.approx(1.4294, abs=1e-4)
    assert row["bandae_amt"] == pytest.approx(816, abs=1)


def test_fetch_credit_merges_columns(monkeypatch):
    margin_obj = _load("freesis_STATSCU0100000070.json")
    deposit_obj = _load("freesis_STATSCU0100000060.json")

    calls = []

    def fake_post(obj_nm, start, end):
        calls.append(obj_nm)
        return margin_obj if obj_nm == "STATSCU0100000070BO" else deposit_obj

    monkeypatch.setattr("src.fetch_credit._post_service", fake_post)

    df = fetch_credit("20260701", "20260713")

    expected_cols = {"margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu", "bandae_amt"}
    assert expected_cols.issubset(df.columns)
    assert df.index.name == "date"
    assert list(df.index) == sorted(df.index)

    row = df.loc["20260710"]
    assert row["margin_total"] == pytest.approx(35.574, abs=1e-3)
    assert row["deposit"] == pytest.approx(105.576, abs=1e-3)
    assert row["misu"] == pytest.approx(1.4294, abs=1e-4)
    assert row["bandae_amt"] == pytest.approx(816, abs=1)


def test_fetch_credit_wraps_failure(monkeypatch):
    def boom(obj_nm, start, end):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.fetch_credit._post_service", boom)

    with pytest.raises(CreditFetchError):
        fetch_credit("20260701", "20260713")


@pytest.mark.network
def test_fetch_credit_live():
    from src.fetch_credit import fetch_credit as live_fetch_credit

    df = live_fetch_credit("20260701", "20260713")
    expected_cols = {"margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu", "bandae_amt"}
    assert expected_cols.issubset(df.columns)
    assert df.index.name == "date"
    assert list(df.index) == sorted(df.index)
    row = df.loc["20260710"]
    assert row["margin_total"] == pytest.approx(35.574, abs=1e-2)
