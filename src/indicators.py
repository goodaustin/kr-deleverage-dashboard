"""方法論核心（純函式）。所有比率公式逆向自原站 2026-07-10 快照。"""
import numpy as np
import pandas as pd


def rolling_pctl(s: pd.Series, window: int, min_periods: int = 60) -> pd.Series:
    """每點相對過去 window 個值的百分位 (0-100) = rank/N*100。"""

    def _p(x):
        cur = x[-1]
        valid = x[~np.isnan(x)]
        if len(valid) < min_periods:
            return np.nan
        return (valid < cur).sum() / len(valid) * 100.0

    return s.rolling(window, min_periods=min_periods).apply(_p, raw=True)


def derive(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["margin_dep"] = d["margin_total"] / d["deposit"] * 100      # 融資/預託金 %
    d["margin_mcap"] = d["margin_total"] / d["mcap"] * 100        # 融資/市值 %
    d["margin_val"] = d["margin_total"] / d["turn_val"]           # 融資/成交 (倍)
    # bandae_amt 單位為億元、misu 單位為兆元（相差 10,000 倍），
    # 換算為同單位後再取百分比，淨效果為 /100（非 *100，經 golden 值反推確認）
    d["bandae_ratio"] = d["bandae_amt"] / d["misu"] / 100          # 斷頭/未繳款 %
    d["turn_heat"] = d["turn_val"] / d["mcap"] * 100              # 成交熱度 %
    ret = np.log(d["kospi_idx"]).diff()
    d["rv20"] = ret.rolling(20).std() * np.sqrt(252) * 100        # 年化20日已實現波動 %
    hi = d["kospi_idx"].cummax()
    d["kospi_dd"] = (d["kospi_idx"] / hi - 1) * 100                # 回撤 %（收盤對收盤）
    return d
