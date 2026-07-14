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


_ZONES = [(0,15,"low","0-15 尾聲：去化近完成"),(15,45,"early","15-45 初期：壓力累積"),
          (45,70,"mid","45-70 中後期：去化進行中"),(70,100,"high","70-100 高壓：槓桿滿載")]

# parts 的中文鍵（順序與 spec §3 一致）
_PART_KEYS = {
 "lvl_margin_pctl":"槓桿水位·融資餘額百分位","lvl_mcap_pctl":"槓桿水位·融資/市值百分位",
 "lvl_dep_pctl":"槓桿水位·融資/預託金百分位","unwind_remaining":"出清進度·未出清比例",
 "momentum":"出清進度·融資動能","forced_amt_pctl":"被動賣壓·斷頭金額百分位",
 "forced_ratio_pctl":"被動賣壓·斷頭比率百分位","vol_pctl":"市場應激·波動率",
 "turnover_pctl":"市場應激·成交熱度"}


def unwind(margin: pd.Series, baseline_date: str) -> dict:
    baseline = float(margin.loc[baseline_date]) if baseline_date in margin.index else float(margin.iloc[0])
    seg = margin.loc[baseline_date:] if baseline_date in margin.index else margin
    peak = float(seg.max()); peak_date = str(seg.idxmax())
    current = float(margin.iloc[-1])
    denom = peak - baseline
    U = 0.0 if denom <= 0 else max(0.0, min(1.0, (peak - current) / denom))
    return {"peak":round(peak,2),"peak_date":peak_date,"baseline":round(baseline,2),
            "baseline_date":baseline_date,"current":round(current,2),"U":round(U,4),
            "excess_peak":round(peak-baseline,2),"excess_now":round(current-baseline,2)}


# 動能映射：融資5日跌幅越深 → norm 越低（去槓桿中）。
# 校準：golden d5=-5.87% → norm 0.25。線性 clamp，常數 MOM_HALF/MOM_SLOPE 之後可用原 repo
# git 歷史多點精修（見「校準備註」）。目前單點校準: 0.5 + d5/23.48 → -5.87 得 0.25。
MOM_SLOPE = 23.48
def momentum_norm(margin_d5_pct: float) -> float:
    return max(0.0, min(1.0, 0.5 + margin_d5_pct / MOM_SLOPE))


def _zone(score: float):
    for lo,hi,z,lbl in _ZONES:
        if lo <= score < hi: return z,lbl
    return _ZONES[-1][2], _ZONES[-1][3]


def composite(pctl: dict, U: float, mom_norm: float, weights: dict) -> dict:
    # 各分項標準化值(0–1)
    norm = {
      "lvl_margin_pctl": pctl["margin_total"]/100, "lvl_mcap_pctl": pctl["margin_mcap"]/100,
      "lvl_dep_pctl": pctl["margin_dep"]/100, "unwind_remaining": (1.0 - U),
      "momentum": mom_norm, "forced_amt_pctl": pctl["bandae_amt"]/100,
      "forced_ratio_pctl": pctl["bandae_ratio"]/100, "vol_pctl": pctl["rv20"]/100,
      "turnover_pctl": pctl["turn_heat"]/100,
    }
    parts = {_PART_KEYS[k]: round(norm[k]*weights[k], 2) for k in weights}
    score = round(sum(parts.values()), 1)
    z,lbl = _zone(score)
    return {"score":score,"zone":z,"zone_label":lbl,"parts":parts}


def _downsample(df: pd.DataFrame, daily_from: str) -> pd.DataFrame:
    # df.index 為 YYYYMMDD 字串；轉 datetime 做 resample
    dt = df.copy(); dt.index = pd.to_datetime(dt.index)
    early = dt[dt.index < pd.to_datetime(daily_from)].resample("W-FRI").last().dropna(how="all")
    late  = dt[dt.index >= pd.to_datetime(daily_from)]
    out = pd.concat([early, late])
    out.index = out.index.strftime("%Y%m%d")
    return out


_SERIES = ["margin_total","margin_kospi","margin_kosdaq","deposit","margin_dep","margin_mcap",
           "margin_val","misu","bandae_amt","bandae_ratio","bandae_amt_ma","bandae_ratio_ma",
           "kospi_idx","kosdaq_idx","kospi_dd","rv20","turn_val","turn_heat","pctl_margin_total"]


def build_ind(full_df: pd.DataFrame, cfg: dict, flags: dict, generated: str, partial: bool) -> dict:
    df = derive(full_df)
    df["bandae_amt_ma"]   = df["bandae_amt"].rolling(5, min_periods=1).mean()
    df["bandae_ratio_ma"] = df["bandae_ratio"].rolling(5, min_periods=1).mean()
    w = cfg["pctl_window_days"]
    pctl_series = {
      "margin_total": rolling_pctl(df["margin_total"], w), "margin_mcap": rolling_pctl(df["margin_mcap"], w),
      "margin_dep": rolling_pctl(df["margin_dep"], w), "bandae_amt": rolling_pctl(df["bandae_amt_ma"], w),
      "bandae_ratio": rolling_pctl(df["bandae_ratio_ma"], w), "rv20": rolling_pctl(df["rv20"], w),
      "turn_heat": rolling_pctl(df["turn_heat"], w),
    }
    df["pctl_margin_total"] = pctl_series["margin_total"]
    last = df.index[-1]
    pctl = {k: round(float(v.loc[last]),1) if pd.notna(v.loc[last]) else None for k,v in pctl_series.items()}
    u = unwind(df["margin_total"], cfg["baseline_date"])
    margin_d5_pct = round((df["margin_total"].iloc[-1]/df["margin_total"].iloc[-6]-1)*100, 2)
    comp = composite(pctl, u["U"], momentum_norm(margin_d5_pct), cfg["weights"])
    # 訊號 s1（自動）
    bandae_ma_pctl = pctl["bandae_amt"]; s1_ok = (bandae_ma_pctl is not None and bandae_ma_pctl < 50 and margin_d5_pct > -1)
    s1_status = "green" if s1_ok else ("amber" if (bandae_ma_pctl or 100) < 70 else "red")
    ds = _downsample(df, cfg["daily_from"])
    return {
      "generated": generated, "sample": False, "partial": partial, "pctl_source": "rolling",
      "data_from": df.index[0], "asof": last, "asof_market": last, "asof_credit": last, "asof_funds": last,
      "n_days_total": len(df), "daily_from": cfg["daily_from"],
      "config": {k: cfg[k] for k in ["baseline_date","pctl_window_days","weights","etf_enabled"]},
      "dates": list(ds.index),
      "series": {k: [None if pd.isna(x) else round(float(x),6) for x in ds[k]] if k in ds else [None]*len(ds) for k in _SERIES},
      "latest": {k: round(float(df[k].iloc[-1]),6) for k in
                 ["margin_total","margin_kospi","margin_kosdaq","deposit","margin_dep","margin_mcap",
                  "margin_val","misu","bandae_amt","bandae_ratio","kospi_idx","kosdaq_idx","turn_val","turn_heat"]},
      "latest_extra": {
        "kospi_dd": round(float(df["kospi_dd"].iloc[-1]),2),
        "kospi_hi52": round(float(df["kospi_idx"].tail(252).max()),2),
        "kospi_hi52_date": str(df["kospi_idx"].tail(252).idxmax()),
        "rv20": round(float(df["rv20"].iloc[-1]),1),
        "bandae_amt_ma": round(float(df["bandae_amt_ma"].iloc[-1]),2),
        "bandae_ratio_ma": round(float(df["bandae_ratio_ma"].iloc[-1]),2),
        "margin_d5_pct": margin_d5_pct,
        "bandae_peak": [round(float(df["bandae_amt"].max()),2), str(df["bandae_amt"].idxmax())],
        "deposit_peak": [round(float(df["deposit"].max()),6), str(df["deposit"].idxmax())],
        "pctl": pctl,
      },
      "unwind": u, "composite": comp,
      "signals": {
        "s1": {"status": s1_status, "label": "技術性賣壓衰竭",
               "detail": f"斷頭金額5日均百分位 {bandae_ma_pctl}｜融資5日 {margin_d5_pct}%"},
        "s2": {"status": flags["s2"]["status"], "label": "外部催化劑落地", "detail": flags["s2"]["detail"]},
        "s3": {"status": flags["s3"]["status"], "label": "監管干預力度", "detail": flags["s3"]["detail"]},
      },
      "etf": {"enabled": cfg["etf_enabled"], "note": flags["etf_note"]},
    }
