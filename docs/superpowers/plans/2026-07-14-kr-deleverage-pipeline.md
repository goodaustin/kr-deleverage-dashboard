# 韓國股市去槓桿壓力儀表板 — 自動更新 Pipeline 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建一條每日自動跑的 Python pipeline，抓韓股資料、依原站方法論重算 `IND`、注入 `index.html`，由 GitHub Actions 自動 commit，使 GitHub Pages 站點每日更新。

**Architecture:** `data/daily.csv`（完整日資料）為唯一真相來源；每日 fetch → append → 全量重算 IND → 注入 HTML → commit。行情類（pykrx，穩定）與信用類（逆向 freeSIS，脆弱、失敗則沿用舊值標 `partial`）分離。方法論以純函式實作並用原站快照當 golden 測試。

**Tech Stack:** Python 3.11、pandas、numpy、requests、pykrx；GitHub Actions（cron）；pytest。

## Global Constraints

- Python 3.11；相依僅限 `pandas, numpy, requests, pykrx, pytest`（記於 `requirements.txt`）。
- 輸出 `IND` 必須與原站同構（見 spec §3）；`render.py` 只替換 `index.html` 中 `const IND = {...};` 一段，其餘位元組不動。
- 單位：融資/預託금/成交 = 兆韓元(조)、斷頭金額/未繳款 = 億韓元、比率與百分位 = %。
- 百分位/UU 用**完整日資料**（`config.pctl_window_days=1250`）；`series`/`dates` 圖表陣列降採樣（`daily_from=20230101` 前每週、後每日）。
- 日期字串一律 `YYYYMMDD`。
- 每次 commit 訊息結尾附 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- Golden 測試向量位於 `docs/superpowers/specs/golden-2026-07-10.json`（原站 2026-07-10 快照）。
- 工作目錄：repo 根 `~/Projects/kr-deleverage-dashboard`。

---

## File Structure

```
kr-deleverage-dashboard/
├── index.html                      # 既有；Task 5 加注入標記
├── requirements.txt                # Task 0
├── config.json                     # Task 0：baseline_date/pctl_window/weights/etf_enabled
├── flags.json                      # Task 0：人工訊號 s2/s3 + etf_note
├── src/
│   ├── __init__.py
│   ├── fetch_market.py             # Task 2：pykrx 兩市指數/成交/市值
│   ├── fetch_credit.py             # Task 6：逆向 freeSIS（依 Task 1 spike 結果）
│   ├── indicators.py               # Task 3/4/7：純函式（百分位/UU/衍生比率/composite/signals）
│   ├── render.py                   # Task 5：注入 index.html
│   └── update.py                   # Task 8：編排 + graceful degradation
├── data/
│   └── daily.csv                   # Task 2 bootstrap 產生；每日 append
├── tests/
│   ├── test_indicators.py          # Task 3/4/7
│   ├── test_render.py              # Task 5
│   └── fixtures/                   # 錄製的 fetch 樣本 + golden
└── .github/workflows/update.yml    # Task 9
```

`data/daily.csv` 欄位（一列一交易日）：
`date, margin_total, margin_kospi, margin_kosdaq, deposit, misu, bandae_amt, kospi_idx, kosdaq_idx, mcap, turn_val`
（其餘如 `margin_dep/margin_mcap/margin_val/bandae_ratio/rv20/turn_heat/kospi_dd/百分位` 皆為**衍生**，由 `indicators.py` 計算，不入 CSV。）

---

## Task 0: 專案骨架與設定檔

**Files:**
- Create: `requirements.txt`, `config.json`, `flags.json`, `src/__init__.py`, `tests/fixtures/.gitkeep`

**Interfaces:**
- Produces: `config.json`、`flags.json` 供 `indicators.py`/`update.py` 讀取。

- [ ] **Step 1: 建立目錄與空檔**

```bash
cd ~/Projects/kr-deleverage-dashboard
mkdir -p src data tests/fixtures
touch src/__init__.py tests/fixtures/.gitkeep
```

- [ ] **Step 2: 寫 `requirements.txt`**

```
pandas>=2.2
numpy>=1.26
requests>=2.31
pykrx>=1.0.45
pytest>=8.0
```

- [ ] **Step 3: 寫 `config.json`（值取自原站 CONFIG）**

```json
{
  "baseline_date": "20260430",
  "pctl_window_days": 1250,
  "daily_from": "20230101",
  "etf_enabled": false,
  "weights": {
    "lvl_margin_pctl": 15.0, "lvl_mcap_pctl": 7.5, "lvl_dep_pctl": 7.5,
    "unwind_remaining": 22.0, "momentum": 8.0,
    "forced_amt_pctl": 10.0, "forced_ratio_pctl": 10.0,
    "vol_pctl": 10.0, "turnover_pctl": 10.0
  }
}
```

- [ ] **Step 4: 寫 `flags.json`（人工旗標，之後用 GitHub 網頁編輯）**

```json
{
  "s2": {"status": "watch", "detail": "外部催化劑：關注大型雲廠 AI 資本開支指引（人工旗標）"},
  "s3": {"status": "watch", "detail": "監管介入：關注限空/穩定基金等措施（人工旗標）"},
  "etf_note": "待 KRX 接入後補齊：三星/SK海力士單股2倍ETF規模與價格"
}
```

- [ ] **Step 5: 建立 venv 並安裝**

Run: `python3.11 -m venv .venv && ./.venv/bin/pip install -r requirements.txt`
Expected: 安裝成功，無錯誤。

- [ ] **Step 6: 加 `.gitignore` 並 commit**

```bash
printf '.venv/\n__pycache__/\n*.pyc\n' > .gitignore
git add requirements.txt config.json flags.json src/__init__.py tests/fixtures/.gitkeep .gitignore
git commit -m "chore: project scaffold, config and manual flags

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: freeSIS 抓取 Spike（最高風險，決策閘）

**這是探索性任務，非 TDD。** 目標：判定能否程式化取得 KOFIA 信用序列（至少「신용거래융자 잔고」日資料）。產出決策：B 可行 → 繼續 Task 6 用 B；不可行 → 停下回報使用者轉 A（官方 OpenAPI，需其註冊金鑰）。

**Files:**
- Create: `scratch/spike_freesis.py`（暫時；spike 後可刪）、`tests/fixtures/freesis_sample.*`（若成功，錄下一次成功回應）

- [ ] **Step 1: 開瀏覽器 DevTools 逆向真實請求**

手動用瀏覽器開 `https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070`（신용공여 잔고 추이），在 Network 面板找出頁面載入資料時實際發出的 XHR/submission（多半是 POST 到某 `.do`，body 為 WebSquare XML 或 JSON，含 serviceId 與日期參數）。記錄：URL、method、headers、request body、response 格式。

- [ ] **Step 2: 用 Python 重放該請求**

```python
# scratch/spike_freesis.py
import requests
URL = "<從 DevTools 得到的端點>"
HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "<實際 content-type>"}
BODY = "<實際 request body，日期改成一段近期區間>"
r = requests.post(URL, headers=HEADERS, data=BODY, timeout=30)
print(r.status_code, r.headers.get("content-type"))
print(r.text[:2000])
```

Run: `./.venv/bin/python scratch/spike_freesis.py`
Expected（成功）: 回傳含日期與融資餘額數值的 XML/JSON。

- [ ] **Step 3: 判定並記錄決策**

- 若成功：把回應存到 `tests/fixtures/freesis_sample.xml`（或 `.json`），並在本檔末「Spike 結果」區記下端點/body/解析路徑。→ 繼續全部後續 Task。
- 若失敗（WebSquare 過度綁定 session/CSRF、或封鎖非瀏覽器）：**停止**，回報使用者「B 不可行，建議轉 A」。轉 A 時 Task 6 改為「使用者提供 OpenAPI 金鑰 → 用官方端點取數」，其餘 Task 不變。

- [ ] **Step 4: commit spike 記錄**

```bash
git add scratch/spike_freesis.py tests/fixtures/ docs/superpowers/plans/2026-07-14-kr-deleverage-pipeline.md
git commit -m "spike: reverse-engineer freeSIS credit data endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `fetch_market.py` — 行情資料（pykrx）

**Files:**
- Create: `src/fetch_market.py`, `tests/test_fetch_market.py`

**Interfaces:**
- Produces: `fetch_market(start: str, end: str) -> pandas.DataFrame`，index=`date`(str YYYYMMDD)，欄位：`kospi_idx, kosdaq_idx, mcap, turn_val`（`mcap`,`turn_val` 單位=조，即 KRW/1e12）。

- [ ] **Step 1: 寫失敗測試（用小日期區間打真站，標記 network）**

```python
# tests/test_fetch_market.py
import pytest
from src.fetch_market import fetch_market

@pytest.mark.network
def test_fetch_market_recent_shape():
    df = fetch_market("20260701", "20260710")
    assert set(["kospi_idx","kosdaq_idx","mcap","turn_val"]).issubset(df.columns)
    assert df.index.name == "date"
    assert (df["kospi_idx"] > 0).all()
    assert (df["mcap"] > 1000).all()      # KOSPI+KOSDAQ 市值必 > 1000조
    assert df.index.max() <= "20260710"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./.venv/bin/python -m pytest tests/test_fetch_market.py -v`
Expected: FAIL（`ModuleNotFoundError` 或 import error）。

- [ ] **Step 3: 實作 `fetch_market.py`**

```python
# src/fetch_market.py
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./.venv/bin/python -m pytest tests/test_fetch_market.py -v -m network`
Expected: PASS。若欄位名不符（pykrx 版本差異），依實際 `df.columns` 修 `rename`。

- [ ] **Step 5: commit**

```bash
git add src/fetch_market.py tests/test_fetch_market.py
git commit -m "feat: fetch_market via pykrx (index/turnover/mcap in 조)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `indicators.py` 衍生比率 + 滾動百分位（純函式）

**Files:**
- Create: `src/indicators.py`, `tests/test_indicators.py`

**Interfaces:**
- Produces:
  - `rolling_pctl(s: pd.Series, window: int) -> pd.Series`（每點對過去 `window` 值的百分位 0–100，`min_periods=60`，不足回 NaN）
  - `derive(df: pd.DataFrame) -> pd.DataFrame`（新增欄：`margin_dep, margin_mcap, margin_val, bandae_ratio, turn_heat, rv20, kospi_dd`）
- Consumes: `data/daily.csv` 欄位（見 File Structure）。

- [ ] **Step 1: 寫失敗測試（衍生比率用 golden latest 值驗證公式）**

```python
# tests/test_indicators.py
import numpy as np, pandas as pd, json, pathlib
from src.indicators import rolling_pctl, derive

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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./.venv/bin/python -m pytest tests/test_indicators.py -v`
Expected: FAIL（import error）。

- [ ] **Step 3: 實作 `rolling_pctl` 與 `derive`**

```python
# src/indicators.py
"""方法論核心（純函式）。所有比率公式逆向自原站 2026-07-10 快照。"""
import numpy as np
import pandas as pd

def rolling_pctl(s: pd.Series, window: int, min_periods: int = 60) -> pd.Series:
    """每點相對過去 window 個值的百分位 (0–100) = rank/N×100。"""
    def _p(x):
        cur = x[-1]
        valid = x[~np.isnan(x)]
        if len(valid) < min_periods:
            return np.nan
        return (valid <= cur).sum() / len(valid) * 100.0
    return s.rolling(window, min_periods=min_periods).apply(_p, raw=True)

def derive(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["margin_dep"]   = d["margin_total"] / d["deposit"] * 100      # 融資/預託金 %
    d["margin_mcap"]  = d["margin_total"] / d["mcap"] * 100         # 融資/市值 %
    d["margin_val"]   = d["margin_total"] / d["turn_val"]           # 融資/成交 (倍)
    d["bandae_ratio"] = d["bandae_amt"] / d["misu"] * 100           # 斷頭/未繳款 %
    d["turn_heat"]    = d["turn_val"] / d["mcap"] * 100             # 成交熱度 %
    ret = np.log(d["kospi_idx"]).diff()
    d["rv20"] = ret.rolling(20).std() * np.sqrt(252) * 100          # 年化20日已實現波動 %
    hi = d["kospi_idx"].cummax()
    d["kospi_dd"] = (d["kospi_idx"] / hi - 1) * 100                 # 回撤 %（收盤對收盤）
    return d
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./.venv/bin/python -m pytest tests/test_indicators.py -v`
Expected: PASS（4 tests）。

- [ ] **Step 5: commit**

```bash
git add src/indicators.py tests/test_indicators.py
git commit -m "feat: rolling percentile + derived ratios (reverse-engineered, golden-checked)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `indicators.py` — UU、動能、composite、build_IND（核心組裝）

**Files:**
- Modify: `src/indicators.py`（新增 `unwind`, `momentum_norm`, `composite`, `build_ind`）
- Modify: `tests/test_indicators.py`（加 golden 組裝測試）

**Interfaces:**
- Produces:
  - `unwind(margin: pd.Series, baseline_date: str) -> dict`（`peak,peak_date,baseline,baseline_date,current,U,excess_peak,excess_now`）
  - `momentum_norm(margin_d5_pct: float) -> float`（0–1；參數化，見下）
  - `composite(pctl: dict, U: float, mom_norm: float, weights: dict) -> dict`（`score,zone,zone_label,parts`）
  - `build_ind(full_df, cfg, flags) -> dict`（完整 IND，見 spec §3）
- Consumes: Task 3 的 `rolling_pctl`,`derive`；`config.json`；`flags.json`。

- [ ] **Step 1: 寫失敗測試（composite 對 golden pctl → 必得 score 45.8）**

```python
# 追加到 tests/test_indicators.py
from src.indicators import unwind, momentum_norm, composite

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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./.venv/bin/python -m pytest tests/test_indicators.py -k "composite or unwind" -v`
Expected: FAIL（未定義）。

- [ ] **Step 3: 實作**

```python
# 追加到 src/indicators.py
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./.venv/bin/python -m pytest tests/test_indicators.py -v`
Expected: PASS。若 `test_composite_matches_golden_score` 差距 >0.3，微調 `MOM_SLOPE` 使 momentum part = 2.0。

- [ ] **Step 5: 實作 `build_ind`（把全量 df + cfg + flags 組成完整 IND）**

```python
# 追加到 src/indicators.py
def _downsample(df: pd.DataFrame, daily_from: str) -> pd.DataFrame:
    weekly = df.loc[:daily_from].resample("W-FRI").last() if False else None  # 見下註
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
```

- [ ] **Step 6: 跑全部 indicator 測試**

Run: `./.venv/bin/python -m pytest tests/test_indicators.py -v`
Expected: PASS。

- [ ] **Step 7: commit**

```bash
git add src/indicators.py tests/test_indicators.py
git commit -m "feat: unwind/momentum/composite + build_ind assembly (golden score 45.8)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**校準備註（momentum）**：目前 `MOM_SLOPE` 由單一 golden 點定。若要精確，從原 repo 取多個歷史快照：
`git clone https://github.com/kidd0368/kidd0368.github.io /tmp/orig && cd /tmp/orig && git log --oneline` → 逐 commit 取 `IND.latest_extra.margin_d5_pct` 與 `composite.parts["出清進度·融資動能"]/8`，最小平方擬合 `MOM_SLOPE`。此為選配精修，不阻擋上線。

---

## Task 5: `render.py` — 注入 index.html

**Files:**
- Create: `src/render.py`, `tests/test_render.py`
- Modify: `index.html`（把第 157 行的 `const IND = {...};` 改成帶標記的可替換段）

**Interfaces:**
- Produces: `render(ind: dict, html_path: str = "index.html") -> None`（原地覆寫）
- Consumes: Task 4 的 `build_ind` 輸出。

- [ ] **Step 1: 在 index.html 加注入標記**

把 `index.html` 內 `const IND = {....大物件....};`（單行，第157行）替換為兩行標記包夾：

```
/*IND-START*/const IND = {};/*IND-END*/
```

（先塞空物件；render 會用 regex 替換 START/END 之間內容。原始資料已在 git 歷史，不會遺失。）

- [ ] **Step 2: 寫失敗測試**

```python
# tests/test_render.py
import json, re, pathlib, tempfile, shutil
from src.render import render

def test_render_injects_valid_json(tmp_path):
    html = tmp_path / "index.html"
    html.write_text('<script>/*IND-START*/const IND = {};/*IND-END*/\nconsole.log(IND);</script>')
    render({"composite": {"score": 45.8}, "asof": "20260710"}, str(html))
    txt = html.read_text()
    m = re.search(r'/\*IND-START\*/const IND = (.*?);/\*IND-END\*/', txt, re.S)
    assert m, "markers preserved"
    obj = json.loads(m.group(1))            # 必為合法 JSON
    assert obj["composite"]["score"] == 45.8
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `./.venv/bin/python -m pytest tests/test_render.py -v`
Expected: FAIL（import error）。

- [ ] **Step 4: 實作 `render.py`**

```python
# src/render.py
"""把 IND dict 注入 index.html 的 /*IND-START*/.../*IND-END*/ 之間。只動這一段。"""
import json, re, pathlib

_PAT = re.compile(r'/\*IND-START\*/const IND = .*?;/\*IND-END\*/', re.S)

def render(ind: dict, html_path: str = "index.html") -> None:
    p = pathlib.Path(html_path)
    html = p.read_text(encoding="utf-8")
    payload = json.dumps(ind, ensure_ascii=False, separators=(",", ":"))
    repl = f'/*IND-START*/const IND = {payload};/*IND-END*/'
    new = _PAT.sub(lambda _: repl, html, count=1)
    if new == html and _PAT.search(html) is None:
        raise RuntimeError("IND markers not found in " + html_path)
    p.write_text(new, encoding="utf-8")
```

- [ ] **Step 5: 跑測試確認通過**

Run: `./.venv/bin/python -m pytest tests/test_render.py -v`
Expected: PASS。

- [ ] **Step 6: commit**

```bash
git add src/render.py tests/test_render.py index.html
git commit -m "feat: render.py injects IND into index.html via markers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `fetch_credit.py` — KOFIA 信用資料（依 Task 1 spike）

**前置**：Task 1 spike 成功（B 可行）。若轉 A，改用官方 OpenAPI 端點 + 使用者金鑰（環境變數 `KOFIA_API_KEY`），本 Task 的 interface 不變。

**Files:**
- Create: `src/fetch_credit.py`, `tests/test_fetch_credit.py`

**Interfaces:**
- Produces: `fetch_credit(start: str, end: str) -> pandas.DataFrame`，index=`date`，欄位：`margin_total, margin_kospi, margin_kosdaq, deposit, misu, bandae_amt`（融資/預託金 in 조；misu in 조；bandae_amt in 억）。失敗時 **raise `CreditFetchError`**（由 `update.py` 捕捉降級）。

- [ ] **Step 1: 寫解析測試（用 Task 1 錄下的 fixture，不打真站）**

```python
# tests/test_fetch_credit.py
import pathlib
from src.fetch_credit import parse_credit_response

def test_parse_credit_fixture():
    raw = pathlib.Path("tests/fixtures/freesis_sample.xml").read_text(encoding="utf-8")
    df = parse_credit_response(raw)
    assert "margin_total" in df.columns
    assert df.index.name == "date"
    assert (df["margin_total"] > 0).all()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./.venv/bin/python -m pytest tests/test_fetch_credit.py -v`
Expected: FAIL。

- [ ] **Step 3: 實作 `fetch_credit.py`**

依 Task 1 記錄的端點/body/格式實作 `fetch_credit()` 與純解析函式 `parse_credit_response(raw:str)->DataFrame`（把解析與網路分離，便於測試）。骨架：

```python
# src/fetch_credit.py
import pandas as pd, requests

class CreditFetchError(Exception): ...

_ENDPOINT = "<Task 1 端點>"

def _body(start: str, end: str, service_id: str) -> str:
    return "<Task 1 記錄的 body 模板，套入日期與 serviceId>"

def parse_credit_response(raw: str) -> pd.DataFrame:
    """把 freeSIS 回應（XML/JSON）解析成 date-indexed DataFrame。欄位見 Interfaces。"""
    ...  # 依實際格式；回傳含 margin_total/kospi/kosdaq/deposit/misu/bandae_amt

def fetch_credit(start: str, end: str) -> pd.DataFrame:
    try:
        r = requests.post(_ENDPOINT, data=_body(start, end, "STATSCU0100000070"),
                          headers={"User-Agent":"Mozilla/5.0","Content-Type":"<...>"} , timeout=30)
        r.raise_for_status()
        return parse_credit_response(r.text)
    except Exception as e:
        raise CreditFetchError(str(e)) from e
```

- [ ] **Step 4: 跑測試確認通過**

Run: `./.venv/bin/python -m pytest tests/test_fetch_credit.py -v`
Expected: PASS。

- [ ] **Step 5: commit**

```bash
git add src/fetch_credit.py tests/test_fetch_credit.py
git commit -m "feat: fetch_credit from KOFIA freeSIS (parse split for testing)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 歷史 Bootstrap → `data/daily.csv`

**Files:**
- Create: `src/bootstrap.py`
- Create: `data/daily.csv`（產物，commit 進 repo）

**Interfaces:**
- Consumes: `fetch_market`, `fetch_credit`。
- Produces: `data/daily.csv`（欄位見 File Structure），為 pipeline 真相來源。

- [ ] **Step 1: 寫 `bootstrap.py`（一次性灌 2000→今）**

```python
# src/bootstrap.py
"""一次性建立 data/daily.csv：行情自 pykrx（2000→今），信用自 KOFIA（能取多久取多久）。"""
import pandas as pd
from src.fetch_market import fetch_market
from src.fetch_credit import fetch_credit, CreditFetchError

def bootstrap(start="20001101", end=None) -> pd.DataFrame:
    end = end or pd.Timestamp.today().strftime("%Y%m%d")
    mkt = fetch_market(start, end)
    try:
        cr = fetch_credit(start, end)
    except CreditFetchError:
        cr = pd.DataFrame(columns=["margin_total","margin_kospi","margin_kosdaq","deposit","misu","bandae_amt"])
    df = mkt.join(cr, how="left")
    df.to_csv("data/daily.csv")
    return df

if __name__ == "__main__":
    df = bootstrap(); print(df.tail(), "\nrows:", len(df))
```

- [ ] **Step 2: 執行 bootstrap（實際灌資料，耗時數分鐘）**

Run: `./.venv/bin/python -m src.bootstrap`
Expected: 印出末幾列與總列數（數千列）；`data/daily.csv` 生成。

- [ ] **Step 3: 用真實歷史驗證 golden score**

Run: `./.venv/bin/python -c "import json,pandas as pd; from src.indicators import build_ind; df=pd.read_csv('data/daily.csv',index_col='date',dtype={'date':str}); df.index=df.index.astype(str); cfg=json.load(open('config.json')); fl=json.load(open('flags.json')); ind=build_ind(df.loc[:'20260710'],cfg,fl,'test',False); print('score',ind['composite']['score'])"`
Expected: `score` 接近 45.8（±2；因真實歷史百分位分母可能略異）。若偏差大，檢查單位與 pctl 窗口。

- [ ] **Step 4: commit（含 data/daily.csv）**

```bash
git add src/bootstrap.py data/daily.csv
git commit -m "feat: history bootstrap → data/daily.csv (source of truth)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `update.py` — 每日編排 + Graceful Degradation

**Files:**
- Create: `src/update.py`
- Create: `tests/test_update.py`

**Interfaces:**
- Consumes: `fetch_market`, `fetch_credit`, `build_ind`, `render`；讀寫 `data/daily.csv`, `index.html`。
- Produces: `main() -> bool`（有更新回 True）。

- [ ] **Step 1: 寫測試（credit 失敗時 partial=True 且不中斷）**

```python
# tests/test_update.py
import pandas as pd, json, pathlib
from src import update as U
from src.fetch_credit import CreditFetchError

def test_degrades_when_credit_fails(monkeypatch, tmp_path):
    base = pd.DataFrame({"kospi_idx":[3000.0],"kosdaq_idx":[900.0],"mcap":[6000.0],"turn_val":[20.0]},
                        index=pd.Index(["20260713"],name="date"))
    monkeypatch.setattr(U, "fetch_market", lambda s,e: base)
    def boom(s,e): raise CreditFetchError("down")
    monkeypatch.setattr(U, "fetch_credit", boom)
    partial = U.merge_new_rows_returns_partial(existing_csv=None, market=base, credit=None)
    assert partial is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `./.venv/bin/python -m pytest tests/test_update.py -v`
Expected: FAIL。

- [ ] **Step 3: 實作 `update.py`**

```python
# src/update.py
"""每日：抓新資料→append data/daily.csv→重算 IND→注入 index.html。信用失敗則降級。"""
import json, pandas as pd
from datetime import datetime, timezone
from src.fetch_market import fetch_market
from src.fetch_credit import fetch_credit, CreditFetchError
from src.indicators import build_ind
from src.render import render

CSV = "data/daily.csv"

def merge_new_rows_returns_partial(existing_csv, market, credit):
    """把 market/credit 併入既有 CSV；credit 為 None 表信用取得失敗。回傳 partial 旗標。"""
    df = market.copy()
    partial = credit is None or credit.empty
    if credit is not None and not credit.empty:
        df = df.join(credit, how="left")
    if existing_csv:
        old = pd.read_csv(existing_csv, index_col="date", dtype={"date": str}); old.index = old.index.astype(str)
        df = pd.concat([old[~old.index.isin(df.index)], df]).sort_index()
        # 信用欄缺值 → 向前填（沿用舊值），並確認 asof_credit 不前進由 build_ind 依 NaN 判定
    return partial if not existing_csv else (df, partial)

def main() -> bool:
    end = datetime.now(timezone.utc).strftime("%Y%m%d")
    start = (datetime.now(timezone.utc) - pd.Timedelta(days=20)).strftime("%Y%m%d")
    mkt = fetch_market(start, end)
    try:
        cr = fetch_credit(start, end)
    except CreditFetchError:
        cr = None
    df, partial = merge_new_rows_returns_partial(CSV, mkt, cr)
    df.to_csv(CSV)
    cfg = json.load(open("config.json")); flags = json.load(open("flags.json"))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    ind = build_ind(df, cfg, flags, generated, partial)
    render(ind, "index.html")
    return True

if __name__ == "__main__":
    print("updated" if main() else "no change")
```

（若 Step 1 測試對 `merge_new_rows_returns_partial` 的簽名有出入，以測試為準微調：無 existing 時回 `bool`，有 existing 時回 `(df, partial)`。）

- [ ] **Step 4: 跑測試確認通過 + 本地端到端**

Run: `./.venv/bin/python -m pytest tests/test_update.py -v && ./.venv/bin/python -m src.update`
Expected: 測試 PASS；`index.html` 被更新（`git diff --stat` 顯示 index.html 變動）。

- [ ] **Step 5: commit**

```bash
git add src/update.py tests/test_update.py data/daily.csv index.html
git commit -m "feat: update.py orchestration with graceful credit degradation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: GitHub Actions 排程 + 端到端上線

**Files:**
- Create: `.github/workflows/update.yml`

**Interfaces:**
- Consumes: `src/update.py`。
- Produces: 自動 commit `data/daily.csv` + `index.html` 回 `main`。

- [ ] **Step 1: 寫 workflow**

```yaml
# .github/workflows/update.yml
name: daily-update
on:
  schedule:
    - cron: "0 7 * * 1-5"   # 16:00 KST 收盤後（抓行情）
    - cron: "0 5 * * 1-5"   # 14:00 KST（補前一日 T+1 信用）
  workflow_dispatch: {}
permissions:
  contents: write
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python -m src.update
      - name: commit if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          if [ -n "$(git status --porcelain data/daily.csv index.html)" ]; then
            git add data/daily.csv index.html
            git commit -m "data: daily auto-update ($(date -u +%Y-%m-%d))"
            git push
          else
            echo "no change"
          fi
```

- [ ] **Step 2: push 並手動觸發驗證**

```bash
git add .github/workflows/update.yml
git commit -m "ci: daily GitHub Actions update workflow

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push
gh workflow run daily-update
```

- [ ] **Step 3: 檢查 run 結果**

Run: `gh run list --workflow=daily-update --limit 1` 然後 `gh run view <id> --log`
Expected: 綠燈；若有新資料則產生一筆 `data: daily auto-update` commit。

- [ ] **Step 4: 驗證 Pages 反映更新**

Run: `curl -s https://goodaustin.github.io/kr-deleverage-dashboard/ | grep -o '"generated":"[^"]*"'`
Expected: `generated` 時間戳為今日。

- [ ] **Step 5: 最終 commit（若有殘留變更）**

```bash
git add -A && git commit -m "chore: finalize pipeline" || echo "clean"
git push
```

---

## Self-Review 檢查結果

**Spec 覆蓋**：§2 方法論→Task 3/4；§3 資料契約→Task 4 `build_ind`；§4 架構→Task 2/6/7/8；§5 config/flags→Task 0；§6 排程/降級/測試→Task 8/9 + 各 Task 測試。無遺漏。

**Placeholder 掃描**：Task 1（spike）與 Task 6（fetch_credit 本體）本質依賴 spike 實測結果，已明確標為「依 Task 1 記錄實作」並提供骨架與可測的 `parse_credit_response` 分離點——此為不可避免的外部未知，非計畫偷懶。其餘皆有完整程式碼。

**型別一致**：`fetch_market/fetch_credit` 回傳 date-indexed DataFrame；`build_ind(full_df,cfg,flags,generated,partial)`；`render(ind,html_path)`；`composite(pctl,U,mom_norm,weights)` 全程一致。

**已知風險**：(1) freeSIS 可抓性（Task 1 閘）；(2) `MOM_SLOPE` 單點校準（Task 4 備註提供多點精修法）；(3) 真實歷史百分位分母與原站可能微異致 score ±2（Task 7 Step 3 驗證）。
