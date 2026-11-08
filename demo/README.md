# MIERU demo kit

Two copies of the same synthetic retail dataset (fictional company and customers, 2,400 rows, Jan 2024 – Jun 2025):

| File | What it shows |
|---|---|
| `mieru-demo-retail-orders.csv` | English headers, `¥1,234` text amounts, ISO dates |
| `mieru-demo-retail-orders-ja.xlsx` | Japanese headers (注文番号, 注文日, 単価, 値引き, 原価 …), a title row above the header, real Excel numbers and dates, a 通貨 (JPY) column and a second メモ sheet |

Both are also downloadable from the Upload page. Both produce **identical** results, which `tests/product/test_demo_samples.py` checks.
Regenerate them with `.venv\Scripts\python.exe demo\build_demo_workbook.py`.

## Expected numbers (verified 2026-10-27)
| KPI | Value |
|---|---|
| Net revenue | ¥31,727,330 |
| Orders · customers · units | 1,385 · 409 · 4,761 |
| Average order value | ¥22,924 |
| Gross profit | ¥15,421,930 (48.6% margin) |
| Revenue bridge | gross ¥32,371,860 − discounts ¥443,900 − returns ¥200,630 = net ¥31,727,330; − cost ¥16,305,400 = gross profit |
| Rows | 2,400 in → 2,361 contributing + 39 excluded (2 blank, 8 confirmed duplicates, 25 cancelled, 4 unreadable amounts) |
| Policy toggle | turning off "Exclude cancelled orders" adds ¥315,290 (net revenue ¥32,042,620) |

## Suggested 5-minute flow
1. Start: `.venv\Scripts\python.exe -m mieru`, then open http://localhost:8000 in a fresh browser window (the intro plays once per browser session; open a new window to see it again).
2. **Olist demo** (sidebar): Executive overview → Delivery & reviews (SLA simulator) → Research findings.
3. **Upload spreadsheet** → drop `mieru-demo-retail-orders-ja.xlsx`. Point out the processing steps and the "How MIERU interpreted this file" banner (Japanese columns mapped automatically, title row skipped).
4. Dashboard → click **ƒ** on *Net revenue* → the Metric Debugger shows the formula, SQL, source columns and 2,400 = 2,361 + 39.
5. **Performance** → revenue bridge, profitability, returns, discounts, concentration.
6. **Data quality** → toggle *Exclude cancelled orders* and watch the KPIs move by ¥315,290; toggle back.
7. **Customers** (RFM, cohorts), **Decision center**, then **Export** → Excel workbook or HTML report.
8. Optional: upload the English CSV to show the same answers from a differently formatted file.
