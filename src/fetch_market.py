"""兩市（KOSPI 1001 / KOSDAQ 2001）指數收盤、成交金額、市值。單位: 조(KRW/1e12)。"""
import pandas as pd
from pykrx import stock

KOSPI, KOSDAQ = "1001", "2001"


def _index_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = stock.get_index_ohlcv(start, end, ticker)  # cols: 시가 고가 저가 종가 거래량 거래대금 상장시가총액
    df = df.rename(columns={"종가": "close", "거래대금": "val", "상장시가총액": "mcap"})
    df.index = df.index.strftime("%Y%m%d")
    df.index.name = "date"
    return df[["close", "val", "mcap"]]


def fetch_market(start: str, end: str) -> pd.DataFrame:
    k = _index_ohlcv(KOSPI, start, end)
    q = _index_ohlcv(KOSDAQ, start, end)
    out = pd.DataFrame(index=k.index.union(q.index))
    out.index.name = "date"
    out["kospi_idx"] = k["close"]
    out["kosdaq_idx"] = q["close"]
    out["turn_val"] = (k["val"].reindex(out.index).fillna(0) + q["val"].reindex(out.index).fillna(0)) / 1e12
    out["mcap"] = (k["mcap"].reindex(out.index).fillna(0) + q["mcap"].reindex(out.index).fillna(0)) / 1e12
    return out.dropna(subset=["kospi_idx"])
