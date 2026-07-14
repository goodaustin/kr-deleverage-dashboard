import numpy as np, pandas as pd, json, pathlib
from src.indicators import rolling_pctl, derive
from src.indicators import unwind, momentum_norm, composite

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

def test_unwind_fully_unwound():
    # 融資: 基期35.71 → 峰值38.63 → 現值35.57 ⇒ U≈1.0
    idx = pd.to_datetime(["2026-04-30","2026-06-24","2026-07-10"]).strftime("%Y%m%d")
    m = pd.Series([35.71, 38.63, 35.57], index=idx)
    u = unwind(m, baseline_date="20260430")
    assert abs(u["U"] - 1.0) < 0.05
    assert u["peak_date"] == "20260624"
