"""方法論核心（純函式）。所有比率公式逆向自原站 2026-07-10 快照。"""
import math
import warnings
import numpy as np
import pandas as pd


def _is_missing(v) -> bool:
    """None 或 NaN 皆視為缺值（turnover/mcap 無免費資料來源時會是其一）。"""
    return v is None or (isinstance(v, float) and math.isnan(v))


def rolling_pctl(s: pd.Series, window: int, min_periods: int = 60) -> pd.Series:
    """每點相對過去 window 個值的百分位 (0-100) = rank/N*100。"""

    def _p(x):
        cur = x[-1]
        if np.isnan(cur):
            # 當期值本身缺值（例如信用資料 T+1 延遲、當日尚未入帳）→ 無法評百分位，
            # 回傳 NaN 而非誤判為 0（0 百分位會被誤讀為「歷史新低」）。
            return np.nan
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
    # baseline_date 若非交易日（例：假日）→ 取 >= baseline_date 的最早交易日；
    # 若 baseline_date 晚於全部資料 → 退回 iloc[0]（最後手段）。
    resolved_date = baseline_date
    if baseline_date not in margin.index:
        fwd = margin.index[margin.index >= baseline_date]
        resolved_date = fwd.min() if len(fwd) > 0 else None
    baseline = float(margin.loc[resolved_date]) if resolved_date is not None else float(margin.iloc[0])
    seg = margin.loc[resolved_date:] if resolved_date is not None else margin
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


# 7 個百分位分項各自來源於 pctl 字典的哪個 key
_PCTL_SRC = {
  "lvl_margin_pctl": "margin_total", "lvl_mcap_pctl": "margin_mcap",
  "lvl_dep_pctl": "margin_dep", "forced_amt_pctl": "bandae_amt",
  "forced_ratio_pctl": "bandae_ratio", "vol_pctl": "rv20",
  "turnover_pctl": "turn_heat",
}


def composite(pctl: dict, U: float, mom_norm: float, weights: dict) -> dict:
    # 各分項標準化值(0–1)；百分位缺值（None/NaN，turnover、市值無免費資料來源時常見）→ None，
    # 不計入 score（僅 unwind_remaining / momentum 恆有值）。
    norm = {"unwind_remaining": (1.0 - U), "momentum": mom_norm}
    for k, src in _PCTL_SRC.items():
        v = pctl[src]
        norm[k] = None if _is_missing(v) else v / 100

    parts = {}
    for k in weights:
        n = norm[k]
        parts[_PART_KEYS[k]] = None if n is None else round(n * weights[k], 2)
    score = round(sum(v for v in parts.values() if v is not None), 1)
    z,lbl = _zone(score)
    return {"score":score,"zone":z,"zone_label":lbl,"parts":parts}


def episode_scores(df: pd.DataFrame, pctl_series: dict, cfg: dict):
    """本輪(baseline_date 解析後的交易日 → asof_credit)每日綜合分數序列。

    逐日重建 unwind()/momentum_norm()/composite() 所需的輸入，並直接呼叫
    composite() 取得該日分數 —— 與 build_ind 單日 composite 共用同一份公式，
    避免時間序列與 gauge 分數之間出現公式漂移。turn_heat / margin_mcap 對每
    一天皆視為缺值（partial），與目前 gauge 呈現方式一致。
    回傳 (dates, scores, excess)；若無信用資料則回傳 ([], [], [])。
    excess[i] = 融資餘額(t) − 基期融資餘額（相對基期的超額槓桿，單位 조）。
    """
    credit_valid_idx = df.index[df["margin_total"].notna()]
    if len(credit_valid_idx) == 0:
        return [], [], []
    asof_credit = credit_valid_idx[-1]

    margin_full = df["margin_total"]
    baseline_date = cfg["baseline_date"]
    if baseline_date not in margin_full.index:
        fwd = margin_full.index[margin_full.index >= baseline_date]
        resolved_date = fwd.min() if len(fwd) > 0 else margin_full.index[0]
    else:
        resolved_date = baseline_date
    baseline_val = float(margin_full.loc[resolved_date])

    seg_index = margin_full.loc[resolved_date:asof_credit].index
    seg_dates = [t for t in seg_index if pd.notna(margin_full.loc[t])]

    weights = cfg["weights"]
    dates, scores, excess = [], [], []
    running_peak = -math.inf
    for t in seg_dates:
        val = float(margin_full.loc[t])
        running_peak = max(running_peak, val)
        denom = running_peak - baseline_val
        U_t = 0.0 if denom <= 0 else max(0.0, min(1.0, (running_peak - val) / denom))
        U_t = round(U_t, 4)

        pos = margin_full.index.get_loc(t)
        if pos >= 5 and pd.notna(margin_full.iloc[pos - 5]) and margin_full.iloc[pos - 5] != 0:
            d5_t = round((val / float(margin_full.iloc[pos - 5]) - 1) * 100, 2)
        else:
            d5_t = 0.0

        pctl_t = {}
        for src in ("margin_total", "margin_dep", "bandae_amt", "bandae_ratio", "rv20"):
            v = pctl_series[src].loc[t]
            pctl_t[src] = None if pd.isna(v) else round(float(v), 1)
        pctl_t["margin_mcap"] = None
        pctl_t["turn_heat"] = None

        comp_t = composite(pctl_t, U_t, momentum_norm(d5_t), weights)
        dates.append(t)
        scores.append(comp_t["score"])
        excess.append(round(val - baseline_val, 2))
    return dates, scores, excess


def _downsample(df: pd.DataFrame, daily_from: str) -> pd.DataFrame:
    # df.index 為 YYYYMMDD 字串；轉 datetime 做 resample
    dt = df.copy(); dt.index = pd.to_datetime(dt.index)
    early_raw = dt[dt.index < pd.to_datetime(daily_from)]
    # known pandas 2.3.x wart: "W-FRI" resample emits a DeprecationWarning about
    # generic NumPy timedelta units internally; harmless, contained here at source.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        early = early_raw.resample("W-FRI").last().dropna(how="all")
    late  = dt[dt.index >= pd.to_datetime(daily_from)]
    out = pd.concat([early, late])
    out.index = out.index.strftime("%Y%m%d")
    return out


_SERIES = ["margin_total","margin_kospi","margin_kosdaq","deposit","margin_dep","margin_mcap",
           "margin_val","misu","bandae_amt","bandae_ratio","bandae_amt_ma","bandae_ratio_ma",
           "kospi_idx","kosdaq_idx","kospi_dd","rv20","turn_val","turn_heat","pctl_margin_total"]


def build_ind(full_df: pd.DataFrame, cfg: dict, flags: dict, generated: str, partial: bool) -> dict:
    df = derive(full_df)
    bandae_ma_days = cfg.get("bandae_ma_days", 5)
    df["bandae_amt_ma"]   = df["bandae_amt"].rolling(bandae_ma_days, min_periods=1).mean()
    df["bandae_ratio_ma"] = df["bandae_ratio"].rolling(bandae_ma_days, min_periods=1).mean()
    w = cfg["pctl_window_days"]
    pctl_series = {
      "margin_total": rolling_pctl(df["margin_total"], w), "margin_mcap": rolling_pctl(df["margin_mcap"], w),
      "margin_dep": rolling_pctl(df["margin_dep"], w), "bandae_amt": rolling_pctl(df["bandae_amt_ma"], w),
      "bandae_ratio": rolling_pctl(df["bandae_ratio_ma"], w), "rv20": rolling_pctl(df["rv20"], w),
      "turn_heat": rolling_pctl(df["turn_heat"], w),
    }
    df["pctl_margin_total"] = pctl_series["margin_total"]

    # KOFIA 信用資料常有 T+1 公布延遲：df.index[-1]（asof_market）當天信用欄位可能仍是 NaN。
    # asof_credit = 最後一個 margin_total 非缺值的日期 —— 所有「信用驅動」的計算
    # （latest/latest_extra/pctl/unwind/composite/s1）都應以 asof_credit 為準，
    # 避免當期 NaN 污染百分位／複合分數（見 task-8fix）。
    credit_valid_idx = df.index[df["margin_total"].notna()]
    asof_market = df.index[-1]
    asof_credit = credit_valid_idx[-1] if len(credit_valid_idx) > 0 else asof_market
    asof = asof_credit
    asof_funds = asof_credit

    pctl = {k: round(float(v.loc[asof_credit]),1) if pd.notna(v.loc[asof_credit]) else None for k,v in pctl_series.items()}
    partial = partial or any(pctl[k] is None for k in pctl)
    margin_upto_credit = df["margin_total"].loc[:asof_credit]
    u = unwind(margin_upto_credit, cfg["baseline_date"])
    margin_d5_pct = round((margin_upto_credit.iloc[-1]/margin_upto_credit.iloc[-6]-1)*100, 2)
    comp = composite(pctl, u["U"], momentum_norm(margin_d5_pct), cfg["weights"])
    sh_dates, sh_scores, sh_excess = episode_scores(df, pctl_series, cfg)
    # 訊號 s1（自動）
    bandae_ma_pctl = pctl["bandae_amt"]; s1_ok = (bandae_ma_pctl is not None and bandae_ma_pctl < 50 and margin_d5_pct > -1)
    s1_status = "green" if s1_ok else ("amber" if (bandae_ma_pctl or 100) < 70 else "red")
    ds = _downsample(df, cfg["daily_from"])
    return {
      "generated": generated, "sample": False, "partial": partial, "pctl_source": "rolling",
      "data_from": df.index[0], "asof": asof, "asof_market": asof_market, "asof_credit": asof_credit, "asof_funds": asof_funds,
      "n_days_total": len(df), "daily_from": cfg["daily_from"],
      "config": {k: cfg[k] for k in ["baseline_date","pctl_window_days","weights","etf_enabled"]},
      "dates": list(ds.index),
      "series": {k: [None if pd.isna(x) else round(float(x),6) for x in ds[k]] if k in ds else [None]*len(ds) for k in _SERIES},
      "latest": {k: round(float(df[k].loc[asof_credit]),6) for k in
                 ["margin_total","margin_kospi","margin_kosdaq","deposit","margin_dep","margin_mcap",
                  "margin_val","misu","bandae_amt","bandae_ratio","kospi_idx","kosdaq_idx","turn_val","turn_heat"]},
      "latest_extra": {
        "kospi_dd": round(float(df["kospi_dd"].loc[asof_credit]),2),
        "kospi_hi52": round(float(df["kospi_idx"].loc[:asof_credit].tail(252).max()),2),
        "kospi_hi52_date": str(df["kospi_idx"].loc[:asof_credit].tail(252).idxmax()),
        "rv20": round(float(df["rv20"].loc[asof_credit]),1),
        "bandae_amt_ma": round(float(df["bandae_amt_ma"].loc[asof_credit]),2),
        "bandae_ratio_ma": round(float(df["bandae_ratio_ma"].loc[asof_credit]),2),
        "margin_d5_pct": margin_d5_pct,
        "bandae_peak": [round(float(df["bandae_amt"].loc[:asof_credit].max()),2), str(df["bandae_amt"].loc[:asof_credit].idxmax())],
        "deposit_peak": [round(float(df["deposit"].loc[:asof_credit].max()),6), str(df["deposit"].loc[:asof_credit].idxmax())],
        "pctl": pctl,
      },
      "unwind": u, "composite": comp,
      "score_history": {"dates": list(sh_dates), "score": sh_scores, "excess": sh_excess},
      "signals": {
        "s1": {"status": s1_status, "label": "技術性賣壓衰竭",
               "detail": f"斷頭金額{bandae_ma_days}日均百分位 {bandae_ma_pctl}｜融資5日 {margin_d5_pct}%"},
        "s2": {"status": flags["s2"]["status"], "label": "外部催化劑落地", "detail": flags["s2"]["detail"]},
        "s3": {"status": flags["s3"]["status"], "label": "監管干預力度", "detail": flags["s3"]["detail"]},
      },
      "etf": {"enabled": cfg["etf_enabled"], "note": flags["etf_note"]},
    }
