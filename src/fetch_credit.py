"""KOFIA freeSIS 信用資料：融資餘額(margin) + 股市資金(deposit/misu/bandae)。

單位: margin_*/deposit/misu 조(KRW/1e12, 原始億/1e4)；bandae_amt 億(原始不轉換)。
"""
import pandas as pd
import requests

_ENDPOINT = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

_MARGIN_SERVICE = "STATSCU0100000070BO"
_DEPOSIT_SERVICE = "STATSCU0100000060BO"

_MARGIN_COLMAP = {
    "TMPV2": "margin_total",
    "TMPV3": "margin_kospi",
    "TMPV4": "margin_kosdaq",
}
_DEPOSIT_COLMAP = {
    "TMPV2": "deposit",
    "TMPV5": "misu",
    "TMPV6": "bandae_amt",
}

# columns that need raw 億 -> 조 conversion (÷1e4); bandae_amt stays in 億.
_TO_JO = {"margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu"}


class CreditFetchError(Exception):
    """Raised on any network or parse failure while fetching KOFIA credit data."""


def parse_service(obj: dict, colmap: dict) -> pd.DataFrame:
    """Pure parser: freeSIS JSON response (dict with key 'ds1') + column map -> date-indexed DataFrame.

    ds1 is newest-first in the raw response; the returned frame is sorted ascending (oldest first).
    """
    rows = obj["ds1"]
    df = pd.DataFrame(rows)
    df = df.rename(columns=colmap)
    df["date"] = df["TMPV1"]
    df = df.set_index("date")
    cols = list(colmap.values())
    df = df[cols]
    for col in cols:
        if col in _TO_JO:
            df[col] = df[col] / 1e4
    df = df.sort_index()
    return df


def _post_service(obj_nm: str, start: str, end: str) -> dict:
    body = {
        "dmSearch": {
            "tmpV40": "100000000",
            "tmpV41": "1",
            "tmpV1": "D",
            "tmpV45": start,
            "tmpV46": end,
            "OBJ_NM": obj_nm,
        }
    }
    r = requests.post(_ENDPOINT, json=body, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_credit(start: str, end: str) -> pd.DataFrame:
    """Fetch and merge KOFIA freeSIS margin + deposit data for [start, end] (YYYYMMDD).

    Returns date-indexed (index name "date", sorted ascending) DataFrame with columns:
    margin_total, margin_kospi, margin_kosdaq, deposit, misu, bandae_amt.
    Raises CreditFetchError on any network/parse failure.
    """
    try:
        margin_obj = _post_service(_MARGIN_SERVICE, start, end)
        deposit_obj = _post_service(_DEPOSIT_SERVICE, start, end)
        margin_df = parse_service(margin_obj, _MARGIN_COLMAP)
        deposit_df = parse_service(deposit_obj, _DEPOSIT_COLMAP)
        merged = margin_df.join(deposit_df, how="outer")
        merged.index.name = "date"
        merged = merged.sort_index()
        return merged
    except Exception as e:
        raise CreditFetchError(str(e)) from e
