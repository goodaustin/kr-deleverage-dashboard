"""每日編排：抓新資料 -> merge 進 data/daily.csv -> 重算 IND -> 注入 index.html。

Graceful degradation: 任一來源（尤其信用 KOFIA freeSIS，常有 T+1 延遲或暫時性故障）失敗時，
不中斷整體流程 —— 保留舊資料、標記 partial=True，並照樣重算+渲染。
"""
import hashlib
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.fetch_credit import CreditFetchError, fetch_credit
from src.fetch_market import MarketFetchError, fetch_market
from src.indicators import build_ind
from src.render import render

_KST = timezone(timedelta(hours=9))

# daily.csv 的真相欄位順序（見 docs/superpowers/specs/data-sources.md）
_COLUMNS = [
    "margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu", "bandae_amt",
    "kospi_idx", "kosdaq_idx", "mcap", "turn_val",
]
_CREDIT_COLS = ["margin_total", "margin_kospi", "margin_kosdaq", "deposit", "misu", "bandae_amt"]
_MARKET_ONLY_COLS = ["mcap", "turn_val"]

CSV_PATH = "data/daily.csv"
HTML_PATH = "index.html"


def merge_recent(existing: pd.DataFrame, recent: pd.DataFrame) -> pd.DataFrame:
    """Merge freshly-fetched `recent` rows into the `existing` daily frame.

    For dates present in both: keep the NEW (recent) value when it is non-null,
    but never let a NaN in `recent` clobber an existing non-null value — this is
    what preserves old credit data on dates where the credit fetch failed while
    the market fetch still succeeded (or vice versa). Dates only in `recent`
    are appended. Result is column-aligned to `_COLUMNS` and sorted ascending.
    """
    existing = existing.reindex(columns=_COLUMNS)
    recent = recent.reindex(columns=_COLUMNS)

    idx = existing.index.union(recent.index)
    existing_r = existing.reindex(idx)
    recent_r = recent.reindex(idx)

    # combine_first: take `recent_r`'s value where non-null, else fall back to `existing_r`.
    merged = recent_r.combine_first(existing_r)
    merged = merged.sort_index()
    merged.index.name = "date"
    return merged[_COLUMNS]


def _hash_file(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _empty_frame(cols: list) -> pd.DataFrame:
    df = pd.DataFrame(columns=cols)
    df.index.name = "date"
    return df


def main(csv_path: str = CSV_PATH, html_path: str = HTML_PATH) -> bool:
    csv_p = pathlib.Path(csv_path)
    html_p = pathlib.Path(html_path)

    before_csv_hash = _hash_file(csv_p)
    before_html_hash = _hash_file(html_p)

    now = datetime.now(_KST)
    end = now.strftime("%Y%m%d")
    start = (now - timedelta(days=30)).strftime("%Y%m%d")

    credit_ok = True
    try:
        credit_df = fetch_credit(start, end)
    except CreditFetchError:
        credit_ok = False
        credit_df = _empty_frame(_CREDIT_COLS)

    market_ok = True
    try:
        market_df = fetch_market(start, end)
    except MarketFetchError:
        market_ok = False
        market_df = _empty_frame(["kospi_idx", "kosdaq_idx"] + _MARKET_ONLY_COLS)

    recent = market_df.join(credit_df, how="outer")
    recent = recent.reindex(columns=_COLUMNS)
    recent.index.name = "date"

    existing = pd.read_csv(csv_p, index_col="date", dtype={"date": str})
    existing.index = existing.index.astype(str)

    full_df = merge_recent(existing, recent)
    full_df.to_csv(csv_p, index_label="date")

    cfg = json.loads(pathlib.Path("config.json").read_text(encoding="utf-8"))
    flags = json.loads(pathlib.Path("flags.json").read_text(encoding="utf-8"))

    latest = full_df.iloc[-1]
    latest_credit_nan = bool(latest[_CREDIT_COLS].isna().any())
    latest_market_only_nan = bool(latest[_MARKET_ONLY_COLS].isna().any())
    partial = (not credit_ok) or (not market_ok) or latest_credit_nan or latest_market_only_nan

    generated = datetime.now(_KST).strftime("%Y-%m-%dT%H:%MZ")
    ind = build_ind(full_df, cfg, flags, generated, partial)
    render(ind, str(html_p))

    after_csv_hash = _hash_file(csv_p)
    after_html_hash = _hash_file(html_p)
    return (before_csv_hash != after_csv_hash) or (before_html_hash != after_html_hash)


if __name__ == "__main__":
    print("updated" if main() else "no change")
