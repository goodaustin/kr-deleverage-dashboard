import numpy as np, pandas as pd, json, pathlib
from src.indicators import rolling_pctl, derive
from src.indicators import unwind, momentum_norm, composite, build_ind

GOLD = json.loads(pathlib.Path("docs/superpowers/specs/golden-2026-07-10.json").read_text())

def test_rolling_pctl_basic():
    s = pd.Series(range(100))            # 0..99
    p = rolling_pctl(s, window=100)
    assert abs(p.iloc[-1] - 99.0) < 1e-6  # 最後一點是最大 → ~99 百分位
    assert np.isnan(p.iloc[0])            # 不足 min_periods

def test_derive_ratios_match_golden():
    L = GOLD["latest"]
    row = pd.DataFrame([{
        "margin_total": L["margin_total"], "deposit": L["deposit"],
        "mcap": L["margin_total"]/L["margin_mcap"]*100,   # 由 golden 反推 mcap
        "turn_val": L["turn_val"], "misu": L["misu"], "bandae_amt": L["bandae_amt"],
        "kospi_idx": L["kospi_idx"],
    }])
    d = derive(row).iloc[0]
    assert abs(d["margin_dep"]  - L["margin_dep"])  < 0.1   # 33.7
    assert abs(d["margin_mcap"] - L["margin_mcap"]) < 0.05  # 0.54
    assert abs(d["margin_val"]  - L["margin_val"])  < 0.02  # 0.92
    assert abs(d["bandae_ratio"]- L["bandae_ratio"])< 0.1   # 5.7

def test_composite_matches_golden_score():
    L = GOLD["latest_extra"]; C = GOLD["config"]; U = GOLD["unwind"]["U"]
    comp = composite(pctl=L["pctl"], U=U,
                     mom_norm=momentum_norm(L["margin_d5_pct"]),
                     weights=C["weights"])
    assert abs(comp["score"] - GOLD["composite"]["score"]) < 0.3   # 45.8
    for k, v in GOLD["composite"]["parts"].items():
        assert abs(comp["parts"][k] - v) < 0.3, k

def test_composite_partial_excludes_missing():
    L = GOLD["latest_extra"]; C = GOLD["config"]; U = GOLD["unwind"]["U"]
    pctl = dict(L["pctl"])
    pctl["turn_heat"] = None
    pctl["margin_mcap"] = None
    comp = composite(pctl=pctl, U=U,
                     mom_norm=momentum_norm(L["margin_d5_pct"]),
                     weights=C["weights"])
    assert comp["parts"]["市場應激·成交熱度"] is None
    assert comp["parts"]["槓桿水位·融資/市值百分位"] is None
    # 其餘 7 個 part 應與 golden 完整版一致（不受影響）
    for k, v in GOLD["composite"]["parts"].items():
        if k in ("市場應激·成交熱度", "槓桿水位·融資/市值百分位"):
            continue
        assert abs(comp["parts"][k] - v) < 0.3, k
    # 注意：golden score 45.8 本身已是 round(sum(9個已各自四捨五入至小數2位的parts), 1)。
    # 若直接做 45.8 - 1.21 - 0.23 = 44.36 → round 成 44.4，是「雙重四捨五入」的誤差；
    # 正確做法（且與 composite() 實作一致）是對「7 個仍存在的 parts之精確值」直接加總後
    # 一次四捨五入至小數1位：14.43+3.12+0.0+2.0+9.82+5.22+9.74 = 44.33 → 44.3。
    assert comp["score"] == 44.3


def test_build_ind_partial_when_mcap_turnover_missing():
    idx = pd.date_range("2024-01-01", periods=120, freq="D").strftime("%Y%m%d")
    n = len(idx)
    rng = np.random.default_rng(42)
    margin_total = pd.Series(30 + rng.normal(0, 0.5, n).cumsum() * 0.05, index=idx)
    df = pd.DataFrame({
        "margin_total": margin_total,
        "margin_kospi": margin_total * 0.6,
        "margin_kosdaq": margin_total * 0.4,
        "deposit": pd.Series(80 + rng.normal(0, 0.3, n).cumsum() * 0.02, index=idx),
        "mcap": np.nan,       # 無免費資料來源 → NaN
        "turn_val": np.nan,   # 無免費資料來源 → NaN
        "misu": pd.Series(500 + rng.normal(0, 5, n), index=idx),
        "bandae_amt": pd.Series(100 + rng.normal(0, 10, n), index=idx),
        "kospi_idx": pd.Series(2500 + rng.normal(0, 20, n).cumsum() * 0.1, index=idx),
        "kosdaq_idx": pd.Series(800 + rng.normal(0, 10, n).cumsum() * 0.1, index=idx),
    }, index=idx)
    cfg = {
        "pctl_window_days": 60, "baseline_date": idx[0],
        "weights": GOLD["config"]["weights"], "etf_enabled": False,
        "daily_from": idx[-30],
    }
    flags = {
        "s2": {"status": "green", "detail": ""},
        "s3": {"status": "green", "detail": ""},
        "etf_note": "",
    }
    ind = build_ind(df, cfg, flags, generated="2026-07-14T00:00:00", partial=False)
    assert ind["partial"] is True
    assert ind["composite"]["parts"]["市場應激·成交熱度"] is None
    assert ind["composite"]["parts"]["槓桿水位·融資/市值百分位"] is None
    assert ind["latest_extra"]["pctl"]["turn_heat"] is None
    assert ind["latest_extra"]["pctl"]["margin_mcap"] is None
    # 20 個 top-level keys 仍在
    assert len(ind.keys()) == 20


def test_unwind_fully_unwound():
    # 融資: 基期35.71 → 峰值38.63 → 現值35.57 ⇒ U≈1.0
    idx = pd.to_datetime(["2026-04-30","2026-06-24","2026-07-10"]).strftime("%Y%m%d")
    m = pd.Series([35.71, 38.63, 35.57], index=idx)
    u = unwind(m, baseline_date="20260430")
    assert abs(u["U"] - 1.0) < 0.05
    assert u["peak_date"] == "20260624"


def test_unwind_baseline_holiday_resolves_to_next_trading_day():
    # 20260430 為假日缺值：index 只有 20260429 / 20260504 / 20260624 / 20260710。
    # baseline 應解析到「>= 20260430」的最早交易日 20260504，而非誤退回 iloc[0](20260429)。
    idx = ["20260429", "20260504", "20260624", "20260710"]
    m = pd.Series([35.00, 35.71, 38.63, 35.57], index=idx)
    u = unwind(m, baseline_date="20260430")
    assert u["baseline"] == round(35.71, 2)          # 值取自 20260504，非 20260429 的 35.00
    assert abs(u["U"] - 1.0) < 0.05
    assert u["peak_date"] == "20260624"
