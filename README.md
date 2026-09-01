# Meta 廣告日預算設定

`set_daily_budget.py` 用 Meta Marketing API 把指定名稱的廣告活動日預算改成你要的金額。
預設是 **dry run**:只列出會改動的項目,確認後再加 `--apply` 才真的寫入。

## 準備

需要一組有 `ads_management` 權限的 access token,以及廣告帳號 ID:

```bash
export META_ACCESS_TOKEN='EAAB...'
export META_AD_ACCOUNT_ID='act_1234567890'
```

Token 可以在 [Graph API Explorer](https://developers.facebook.com/tools/explorer/) 產生,
廣告帳號 ID 在 Ads Manager 網址列或帳號總覽看得到。

只需要 Python 3,沒有其他套件相依。

## 用法

先看看會改到哪些東西:

```bash
python3 set_daily_budget.py --name 三井 --name 完作 --budget 1000
```

輸出範例:

```
Ad account act_1234567890 (TWD)

  adset   三井 / 廣告組合 1   ACTIVE       500 TWD -> 1000 TWD
  adset   完作 / 廣告組合 1   ACTIVE       800 TWD -> 1000 TWD

Dry run. Re-run with --apply to write these budgets.
```

確認沒問題再實際套用:

```bash
python3 set_daily_budget.py --name 三井 --name 完作 --budget 1000 --apply
```

## 行為說明

- `--name` 是**部分比對**(不分大小寫),所以 `--name 三井` 會對到所有名稱含「三井」的活動。
  執行結果會列出實際對到的名稱,套用前請先確認。
- 活動若開了 CBO(預算在活動層級),就改活動層級;否則改該活動底下每一個廣告組合。
- 多個廣告組合各自設 1000 時,整檔活動一天最多會花到 1000 × 組合數 —
  腳本會在下方額外提示合計金額。
- 金額用廣告帳號的幣別;TWD、JPY 這類沒有輔幣單位的幣別會直接送整數,
  USD 這類則自動換算成分。
- 活動或廣告組合若設的是**總預算(lifetime budget)**,不能直接改成日預算 —
  腳本會停下來並說明要先到 Ads Manager 清掉總預算。
