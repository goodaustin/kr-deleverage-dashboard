# 資料源契約（reverse-engineered, verified 2026-07-14）

決策：信用+指數+波動率走免費源（~82.5% 權重，含去槓桿全核心）；成交額/市值暫缺，標 `partial`。

## A. KOFIA freeSIS — 信用數據（無需登入，日資料回溯到 2000-11-01，共 ~6449 筆）

- **Endpoint**: `POST https://freesis.kofia.or.kr/meta/getMetaDataList.do`
- **Headers**: `Content-Type: application/json`, `User-Agent: Mozilla/5.0`（無需 cookie/CSRF）
- **Body 模板**（`OBJ_NM` 選服務，`tmpV45/46` 起訖日 YYYYMMDD，`tmpV1:"D"` 日頻）:
  ```json
  {"dmSearch":{"tmpV40":"100000000","tmpV41":"1","tmpV1":"D","tmpV45":"<start>","tmpV46":"<end>","OBJ_NM":"<SERVICE>BO"}}
  ```
- **Response**: `{"unit":"","ds1":[{TMPV1..TMPVn}, ...],"dsmHeader":""}`；`ds1` 依日期新→舊排序，`TMPV1`=日期。

### 服務 1 — `OBJ_NM=STATSCU0100000070BO`（신용공여 잔고 = 融資餘額）
| 欄位 | 意義 | 原始單位 | 轉換 → daily.csv |
|---|---|---|---|
| TMPV1 | 日期 | YYYYMMDD | `date` |
| TMPV2 | 融資總額 | 億원 | `/1e4` → `margin_total`(조) |
| TMPV3 | 融資·유가증권(KOSPI) | 億원 | `/1e4` → `margin_kospi`(조) |
| TMPV4 | 融資·KOSDAQ | 億원 | `/1e4` → `margin_kosdaq`(조) |
| TMPV5~9 | 신용거래대주(融券)等 | — | 忽略 |
驗證：20260710 TMPV2=355740億=35.574조 = golden margin_total 35.573983 ✅

### 服務 2 — `OBJ_NM=STATSCU0100000060BO`（증시자금추이 = 股市資金）
| 欄位 | 意義 | 原始單位 | 轉換 → daily.csv |
|---|---|---|---|
| TMPV1 | 日期 | YYYYMMDD | `date` |
| TMPV2 | 투자자예탁금(預託金) | 億원 | `/1e4` → `deposit`(조) |
| TMPV3,4 | 예탁금 細項 | — | 忽略 |
| TMPV5 | 미수금(未繳款) | 億원 | `/1e4` → `misu`(조) |
| TMPV6 | 반대매매 금액(斷頭金額) | 億원 | 保留億 → `bandae_amt`(億) |
| TMPV7 | 반대매매 비중(斷頭比率) | % | 直接參考（derive 會自算，兩者應≈；API 為整數精度） |
驗證：20260710 → deposit 105.576조 ✅ / misu 1.4294조 ✅ / bandae_amt 816億 ✅ / bandae_ratio 5.7 ✅
注意：API 的億值為整數（bandae_amt 816 vs golden 816.13）——微小精度差，可接受。

## B. Yahoo Finance — 指數（無需登入，回溯到 ~1996）
- **Endpoint**: `GET https://query1.finance.yahoo.com/v8/finance/chart/<SYM>?period1=<epoch>&period2=<epoch>&interval=1d`，Header `User-Agent: Mozilla/5.0`
- `^KS11` → `kospi_idx`（`indicators.quote[0].close`，對 `timestamp`）；`^KQ11` → `kosdaq_idx`
- 取 `chart.result[0].timestamp`（epoch 秒，轉 KST 日期 YYYYMMDD）與對應 close；去除 null。

## C. 成交額/市值 — 暫缺（partial）
- `turn_val`、`mcap` 免費源無完整歷史 → daily.csv 該兩欄留空(NaN)。
- 影響：`turn_heat`(成交熱度,權重10)、`margin_mcap`(融資/市值,權重7.5)、`margin_val`(顯示) 無法算。
- **build_ind/composite 須容忍**：某分項的 pctl 為 None 時，該 part 不計入 score，並設 `IND.partial=true`；`latest_extra.pctl` 對應鍵給 `null`。可達分數上限約 82.5。
- 升級路徑：日後接 KRX(需登入 KRX_ID/KRX_PW，pykrx) 或 Naver 補這兩欄。

## daily.csv 欄位與單位（真相來源）
`date, margin_total(조), margin_kospi(조), margin_kosdaq(조), deposit(조), misu(조), bandae_amt(億), kospi_idx, kosdaq_idx, mcap(조,暫NaN), turn_val(조,暫NaN)`
衍生欄（indicators.derive，不入 csv）：margin_dep, margin_mcap, margin_val, bandae_ratio, turn_heat, rv20, kospi_dd。
