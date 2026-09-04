# 完作｜高雄近期交屋生活圈投放

第一階段原則:**同樣的既有核准素材、不同的近期交屋生活圈**,用來驗證哪個生活圈真的有裝修需求。

這個資料夾是投放前的資料底座。目前**尚無任何完作素材、品牌檔、Meta 設定或建案情報**,
所有事實性資料都要先放進來,評分與分組才能執行。程式不會猜測任何缺少的欄位。

## 資料要放哪裡

| 內容 | 位置 | 格式 |
|---|---|---|
| 廣告圖片 / 影片 / 輪播 / Reel | `assets/` | 原始檔,檔名不要改 |
| 素材盤點表(表一) | `assets_inventory.csv` | 一列一素材,欄位已建好 |
| Logo、品牌色規範 | `brand/` | 原始檔 + 色碼說明 |
| 現有廣告文案 | `copy/` | 一檔一版本 |
| 現有 Meta 廣告設定 | `meta/` | 廣告管理員匯出的 CSV,或截圖 |
| 現有表單 | `forms/` | 表單題目匯出 |
| 網站 / 官方 LINE 導流方式 | `funnel.md` | 網址、LINE ID、目前流程 |
| 建案主檔 | `data/projects.csv` | 一列一建案 |
| 公開驗屋 / 交屋訊號 | `data/signals.csv` | 一列一則公開訊號 |

`assets_inventory.csv` 的 `approval_status` 只能填 `已核准`、`待確認`、`不可使用`、`待人工確認`。
只有 `已核准` 會進入第一階段。程式不會替任何素材判定核准狀態。

## 建案與訊號資料的規則

`data/signals.csv` 每一列都必須有:

- `source_url` — 原始公開網址(去重依據,同一則貼文只計一次)
- `post_date` — 貼文發布日期
- `event_date` — 實際事件日期(驗屋日、交屋日),與貼文日期分開記
- `checked_at` — 最後查核日期;超過 14 天程式會標記 `recheck_due`
- `confidence` — `high` / `medium` / `low`

**不得記錄**屋主姓名、電話、Email、社群帳號、私人社團成員、住戶群組名單或個人房產持有資料。
訊號只用來判斷生活圈的交屋時機與需求熱度。

## Meta Ads MCP(讓 Claude 直接讀寫廣告帳戶)

repo 根目錄的 `.mcp.json` 已設定 `meta-ads` 這個 MCP server(`meta-ads-mcp` 1.0.120,
37 個工具:讀取帳戶/活動/廣告組/廣告/洞察、建立與更新活動/廣告組/廣告、搜尋興趣與地理位置、
估算受眾規模)。它只從環境變數 `META_ACCESS_TOKEN` 拿授權,token 不會進到 repo。

啟用方式:

1. 到 claude.ai/code 的環境設定(Environment → Environment variables),新增
   `META_ACCESS_TOKEN` = 你的 Meta 長效 token(需要 `ads_read`;要改設定則需 `ads_management`)。
2. 用這個 repo 開一個**新的** session,啟動時同意載入 `.mcp.json` 裡的 `meta-ads` server。
3. 對 Claude 說「列出我的廣告帳戶」確認接通。

沒有設 `META_ACCESS_TOKEN` 時 server 仍會啟動,但每個工具都會回「未授權」。

## 執行

```bash
python3 wanzuo/scoring.py            # 讀 data/,輸出每個建案的評分與依據
python3 wanzuo/scoring.py --json     # 機器可讀輸出
python3 -m unittest discover -s wanzuo/tests
```

每個分數都附 `breakdown`,列出每一項加減分的來源,缺資料的項目標 `未查得`。
評分權重寫在 `scoring.py` 開頭,是**建議起點**,尚待人工確認。
