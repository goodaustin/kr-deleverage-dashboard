"""Yahoo Finance 指數：KOSPI(^KS11) / KOSDAQ(^KQ11) 收盤。

KRX(pykrx) 已需登入(KRX_ID/KRX_PW)，改走 Yahoo Finance chart API（免登入）。
成交金額(turn_val)、市值(mcap) 免費源無完整歷史 -> 留 NaN（partial，見 docs/superpowers/specs/data-sources.md §C）。
"""
import calendar
import datetime as dt
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests

_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_KOSPI_SYM = "^KS11"
_KOSDAQ_SYM = "^KQ11"

_KST_OFFSET = dt.timedelta(hours=9)


class MarketFetchError(Exception):
    """Raised on any network or parse failure while fetching Yahoo index data."""


def _epoch(date_str: str, add_days: int = 0) -> int:
    """YYYYMMDD -> epoch seconds (UTC midnight), optionally shifted by add_days."""
    d = dt.datetime.strptime(date_str, "%Y%m%d") + dt.timedelta(days=add_days)
    return calendar.timegm(d.timetuple())


def parse_yahoo_chart(obj: dict) -> pd.Series:
    """Pure parser: Yahoo chart API response dict -> date-indexed close Series.

    Epoch timestamps (UTC seconds) are converted to KST (UTC+9) calendar dates
    (YYYYMMDD str). Null closes are dropped. If two timestamps map to the same
    KST date, the later one wins. Returned series is sorted ascending by date.
    """
    result = obj["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]

    dates, values = [], []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        kst = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc) + _KST_OFFSET
        dates.append(kst.strftime("%Y%m%d"))
        values.append(close)

    s = pd.Series(values, index=pd.Index(dates, name="date"), dtype=float)
    s = s[~s.index.duplicated(keep="last")]
    s = s.sort_index()
    return s


def _fetch_yahoo(symbol: str, start: str, end: str) -> pd.Series:
    period1 = _epoch(start)
    period2 = _epoch(end, add_days=1)  # +1 day so `end` itself is included
    url = _ENDPOINT.format(sym=quote(symbol, safe=""))
    params = {"period1": period1, "period2": period2, "interval": "1d"}
    r = requests.get(url, params=params, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return parse_yahoo_chart(r.json())


def fetch_market(start: str, end: str) -> pd.DataFrame:
    """Fetch KOSPI/KOSDAQ index close for [start, end] (YYYYMMDD) from Yahoo Finance.

    Returns date-indexed (index name "date", sorted ascending) DataFrame with columns:
    kospi_idx, kosdaq_idx, mcap, turn_val. mcap/turn_val are NaN (no free historical
    source; see docs/superpowers/specs/data-sources.md §C).
    Raises MarketFetchError on any network/parse failure.
    """
    try:
        kospi = _fetch_yahoo(_KOSPI_SYM, start, end)
        kosdaq = _fetch_yahoo(_KOSDAQ_SYM, start, end)

        idx = kospi.index.union(kosdaq.index)
        idx = idx[(idx >= start) & (idx <= end)]
        idx = idx.sort_values()
        idx.name = "date"

        out = pd.DataFrame(index=idx)
        out.index.name = "date"
        out["kospi_idx"] = kospi.reindex(idx)
        out["kosdaq_idx"] = kosdaq.reindex(idx)
        out["mcap"] = np.nan
        out["turn_val"] = np.nan
        return out
    except MarketFetchError:
        raise
    except Exception as e:
        raise MarketFetchError(str(e)) from e
