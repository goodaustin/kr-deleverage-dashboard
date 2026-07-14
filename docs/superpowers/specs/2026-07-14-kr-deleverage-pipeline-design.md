# 韓國股市去槓桿壓力儀表板 — 自動更新 Pipeline 設計

- **日期**: 2026-07-14
- **Repo**: `goodaustin/kr-deleverage-dashboard`（GitHub Pages: https://goodaustin.github.io/kr-deleverage-dashboard/）
- **狀態**: 設計已由使用者核准，待寫實作計畫

## 1. 背景與目標

`index.html` 目前是原站（`kidd0368.github.io`）的靜態快照，資料寫死在 JS 內的 `const IND = {...}`（截止 2026-07-10）不會更新。本專案要建一條每日自動更新的 pipeline：抓取韓股資料 → 依原站方法論重算指標 → 注入 `index.html` → 自動 commit，讓 GitHub Pages 站點每日刷新。

**忠實度決策**：採 graceful-degradation 混合方案。行情類指標（穩定來源）優先確保上線；信用類指標（KOFIA，脆弱）盡力取得，取不到時標 `partial:true` 並沿用舊值。

**信用資料源決策**：先走 **B（逆向抓取 freeSIS 2.0）**，我方全程實作、使用者免動手；若證實太脆弱，再轉 **A（官方 KOFIA OpenAPI，需使用者註冊金鑰）**。

## 2. 方法論（重建自原站，須逐項對齊）

指數 = 四大維度九分項加權，總分 0–100。權重（`config.weights`）：

| 維度 | 分項 (IND parts key) | 權重 | 資料依賴 |
|---|---|---|---|
| 槓桿水位 | 融資餘額5年百分位 `lvl_margin_pctl` | 15 | 信用 |
| | 融資/市值百分位 `lvl_mcap_pctl` | 7.5 | 信用+行情 |
| | 融資/預託金百分位 `lvl_dep_pctl` | 7.5 | 信用 |
| 出清進度 | 未出清比例 `unwind_remaining` | 22 | 信用 |
| | 融資5日動能 `momentum` | 8 | 信用 |
| 被動賣壓 | 斷頭金額百分位 `forced_amt_pctl` | 10 | 信用 |
| | 斷頭比率百分位 `forced_ratio_pctl` | 10 | 信用 |
| 市場應激 | 波動率百分位 `vol_pctl` | 10 | 行情 |
| | 成交熱度百分位 `turnover_pctl` | 10 | 行情 |

行情類僅佔 20% 權重；其餘 80% 依賴 KOFIA 信用數據——這是本站的核心，故 KOFIA 取得為關鍵風險。

**核心公式**：
- **滾動百分位**：每指標對過去 `pctl_window_days=1250` 交易日求 `rank/N×100`。
- **未出清比例 UU** = `(peak − current) / (peak − baseline)`，`baseline_date=20260430`（AI 行情起漲前），clamp [0,1]；`unwind_remaining` 分項 = `(1−UU)` 方向（剩越多分數越高）。
- **融資動能** `margin_d5_pct` = 融資餘額 5 交易日變化率。
- **波動率** `rv20` = KOSPI 20 日日報酬標準差 × √252（年化），近似 VKOSPI。
- **回撤** `kospi_dd` = 收盤對 52 週最高收盤（KOFIA 僅發布收盤指數，不取盤中）。
- **composite.score** = Σ(各分項標準化值 × 權重)；再依 score 落入 zone（如 `mid` / `45-70 中後期：去化進行中`）。

**訊號**：
- `s1`（自動）技術性賣壓衰竭 = 斷頭金額5日均百分位 < 50 且 融資5日跌幅 < 1% → green/amber(watch)/red。
- `s2`、`s3`（人工）外部催化、監管介入 → 由 `flags.json` 提供 `status` + `detail`。

## 3. 資料契約（IND 物件，比照原站 100% 欄位）

`compute_indicators.py` 須輸出與原站同構的 `IND` dict，`render.py` 依此注入。頂層鍵：

- 中繼: `generated, sample, partial, pctl_source("rolling"), data_from, asof, asof_market, asof_credit, asof_funds, n_days_total, daily_from`
- `config`: `baseline_date, pctl_window_days, weights{9}, etf_enabled`
- `dates`: list[str `YYYYMMDD`]（**降採樣**：`daily_from`(20230101) 前每週、之後每日；原站約 2011 點）
- `series`: 19 條與 `dates` 等長的陣列 — `margin_total, margin_kospi, margin_kosdaq, deposit, margin_dep, margin_mcap, margin_val, misu, bandae_amt, bandae_ratio, bandae_amt_ma, bandae_ratio_ma, kospi_idx, kosdaq_idx, kospi_dd, rv20, turn_val, turn_heat, pctl_margin_total`（早期缺值以 `null` 填）
- `latest`: 14 項當前值
- `latest_extra`: `kospi_dd, kospi_hi52, kospi_hi52_date, rv20, bandae_amt_ma, bandae_ratio_ma, margin_d5_pct, bandae_peak[val,date], deposit_peak[val,date], pctl{7}`
- `unwind`: `peak, peak_date, baseline, baseline_date, current, U, excess_peak, excess_now`
- `composite`: `score, zone, zone_label, parts{9 具中文鍵的加權貢獻}`
- `signals`: `s1/s2/s3 → {status,label,detail}`
- `etf`: `{enabled, note}`

**重要**：百分位/UU 以**完整日資料**（`n_days_total`≈6287）計算；`series`/`dates` 陣列另行降採樣以控檔案大小。單位比照原站：融資/預託金/成交 = 兆韓元(조)、斷頭金額 = 億韓元、比率/百分位 = %。

## 4. 架構與模組

真相來源 = `data/daily.csv`（完整日資料，每日 append，git 可追溯）。pipeline 每日 append 新列後**全量重算** IND。

| 檔案 | 職責 | 輸入 → 輸出 | 風險 |
|---|---|---|---|
| `fetch_market.py` | 兩市指數/成交/市值 | 日期範圍 → market DataFrame（`pykrx`） | 低 |
| `fetch_credit.py` | 융資/예託금/미수금/반대매매 | 日期範圍 → credit DataFrame（逆向 freeSIS） | **高**：失敗回空，不中斷 |
| `compute_indicators.py` | 方法論核心（純函式） | `daily.csv`+`config.json`+`flags.json` → `IND` dict | 中 |
| `render.py` | 注入 | `IND`+`index.html` → 覆寫 `index.html` 的 `const IND=` 段 | 低 |
| `update.py` | 編排 | — → 串起 fetch→compute→render | 低 |

資料流：`fetch_* → 更新 data/daily.csv → compute_indicators → IND → render → git commit data/daily.csv + index.html → Pages 更新`。

## 5. 設定與人工旗標（使用者用 GitHub 網頁編輯）

- `config.json`：`baseline_date, pctl_window_days, weights{9}, etf_enabled`（對應原站 CONFIG）。
- `flags.json`：`s2{status,detail}`、`s3{status,detail}`、`etf_note`。

## 6. 排程、錯誤處理、測試

- **排程**：GitHub Actions cron，週一~五兩班 — `07:00 UTC`(16:00 KST 收盤後) 抓行情、`05:00 UTC`(14:00 KST) 補前一日 T+1 信用。僅在檔案有變動時 commit（用 `GITHUB_TOKEN` 推回同 repo）。
- **錯誤處理**：任一 fetch 失敗 → 記 log、沿用 `daily.csv` 舊值、`partial:true`、對應 `asof_*` 不前進，pipeline 不整體中斷。freeSIS 連續失敗 → Actions run 標記失敗（GitHub 寄信通知），觸發「考慮轉 A」決策。
- **測試**：
  - `compute_indicators.py`：以固定小段歷史做單元測試，驗證 score/UU/百分位/動能數值與手算一致。
  - `render.py`：驗證注入後 HTML 合法且 `JSON.parse` 可解析 `IND`。
  - `fetch_*`：以錄製的樣本回應做解析測試（避免每次打真站）。
- **技術棧**：Python 3.11 + `pandas`、`numpy`、`requests`、`pykrx`。全部置於同一 repo。

## 7. 里程碑（實作計畫將據此展開）

1. **freeSIS 抓取 spike**（最高風險先驗證）：能否程式化取得至少一條信用序列（融資餘額日資料）。卡住即回報使用者決定轉 A。
2. `fetch_market.py` + 歷史 bootstrap → 建立 `data/daily.csv`。
3. `compute_indicators.py` + 單元測試（先以行情類分項對齊，信用類接上後補齊）。
4. `render.py` + `index.html` 加注入標記。
5. `fetch_credit.py` 整合（依 spike 結果）。
6. `update.py` + GitHub Actions 排程 + 首次端到端跑通。

## 8. 已知限制（沿用原站口徑）

- KOFIA 僅涵蓋場內信用融資，不含槓桿 ETF 內含槓桿、股票質押、場外配資。
- 信用數據 T+1 公布，`asof_credit` 通常較 `asof_market` 晚 1–2 交易日（圖上融資線尾端較短屬正常）。
- 波動率用 20 日已實現波動率替代 VKOSPI；回撤用收盤對收盤。
- 槓桿 ETF 面板（`etf.enabled`）暫不啟用（原站亦待 KRX 接入）。
