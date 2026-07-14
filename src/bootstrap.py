"""一次性建立 data/daily.csv：行情自 Yahoo Finance（2000→今），信用自 KOFIA freeSIS（回溯到 2000-11-01）。

daily.csv 為 pipeline 真相來源。若任一來源失敗，仍寫出已取得的部分並印出明確警告，
不硬中斷（見 docs/superpowers/specs/data-sources.md）。
"""
import datetime as dt
import warnings

import pandas as pd

from src.fetch_credit import CreditFetchError, fetch_credit
from src.fetch_market import MarketFetchError, fetch_market

_COLUMNS = [
    "margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu", "bandae_amt",
    "kospi_idx", "kosdaq_idx", "mcap", "turn_val",
]

_KST = dt.timezone(dt.timedelta(hours=9))


def bootstrap(start_credit: str = "20001101", start_index: str = "20000101", end: str = None) -> pd.DataFrame:
    """組裝 data/daily.csv：信用(KOFIA) outer-join 行情(Yahoo)，依日期升冪排序。

    end 預設為今天（KST）。任一來源失敗時仍寫出已取得的部分並印出警告，不中斷整體流程。
    """
    end = end or dt.datetime.now(_KST).strftime("%Y%m%d")

    cr = pd.DataFrame(columns=["margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu", "bandae_amt"])
    try:
        cr = fetch_credit(start_credit, end)
    except CreditFetchError as e:
        warnings.warn(f"bootstrap: fetch_credit failed ({e}); writing daily.csv without credit data", stacklevel=2)
        print(f"WARNING: fetch_credit failed: {e}; proceeding without credit data")

    mkt = pd.DataFrame(columns=["kospi_idx", "kosdaq_idx", "mcap", "turn_val"])
    try:
        mkt = fetch_market(start_index, end)
    except MarketFetchError as e:
        warnings.warn(f"bootstrap: fetch_market failed ({e}); writing daily.csv without market data", stacklevel=2)
        print(f"WARNING: fetch_market failed: {e}; proceeding without market data")

    df = cr.join(mkt, how="outer")
    df.index.name = "date"
    df = df.sort_index()
    df = df[_COLUMNS]

    df.to_csv("data/daily.csv", index_label="date")
    return df


if __name__ == "__main__":
    df = bootstrap()
    print(df.tail())
    print("rows", len(df))
