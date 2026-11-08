# MIERU (見える): metric definitions

This reference follows the implemented registries, SQL and rule functions. Ratios/shares are returned as fractions unless a field explicitly ends in `_pct`. See [architecture.md](architecture.md) for data flow, endpoints, isolation and test coverage.

## 1. Upload metric registry and row classification

Source: [`mieru/metrics/upload.py`](../mieru/metrics/upload.py): `UPLOAD_METRICS`, `value_expression`, `metric_availability`, `effective_scopes`, `scope_reasons`, `classified_cte`, `compute_metric`. IDs below are registry IDs; explanation definitions prefix them with `upload.`. All explanation record counts have grain `"source row"`.

In the table, **B** means the four policy-controlled base reasons: `blank_row`, `duplicate_reliable`, `duplicate_possible`, `cancelled`. Scope abbreviations refer to the exact scope mapping below. Requirements are the exact `UploadMetric.requires` entries; all must pass. SQL is the exact value expression, with context-dependent branches identified explicitly.

| ID | Label | Formula text from registry | SQL value expression | Unit | Scopes → applicable exclusions | Requirements |
|---|---|---|---|---|---|---|
| `net_revenue` | Net revenue | Σ net line value over contributing rows (or Σ order total once per order) | `SUM(order_value_once) FILTER (WHERE contributes)` for `order_total`; otherwise `SUM(net_value) FILTER (WHERE contributes)` | `currency` | `("revenue",)` → B + revenue | `("revenue",)` |
| `gross_sales` | Gross sales | Σ line value over contributing non-return rows | `SUM(signed_value) FILTER (WHERE contributes AND NOT is_return)` | `currency` | `("revenue",)` → B + revenue | `("revenue", "line_revenue")` |
| `returns_value` | Returns & credits | −Σ net line value over contributing return rows | `-SUM(net_value) FILTER (WHERE contributes AND is_return)` | `currency` | `("revenue",)` → B + revenue | `("revenue", "returns", "line_revenue")` |
| `discounts_value` | Discounts | Σ discount amount over contributing non-return rows | `SUM(discount_value) FILTER (WHERE contributes AND NOT is_return)` | `currency` | `("revenue",)` → B + revenue | `("revenue", "discounts")` |
| `orders` | Orders | COUNT(DISTINCT order_id) over contributing non-return rows | `COUNT(*) FILTER (WHERE contributes AND NOT is_return)` at transaction grain; otherwise `COUNT(DISTINCT order_id) FILTER (WHERE contributes AND NOT is_return)` | `count` | Registry `()`; effective `("order",)` outside transaction grain → B + order; transaction → B | `("orders",)` |
| `customers` | Customers | COUNT(DISTINCT customer_id) over contributing rows | `COUNT(DISTINCT customer_id) FILTER (WHERE contributes)` | `count` | `("customer",)` → B + customer | `("customers",)` |
| `units` | Units sold | Σ quantity over contributing non-return rows | `SUM(quantity) FILTER (WHERE contributes AND NOT is_return)` | `count` | `("quantity",)` → B + quantity | `("units",)` |
| `aov` | Average order value | Net revenue ÷ orders (same contributing rows) | Source template: `f"({revenue}) / NULLIF({orders}, 0)"`; all exact expansions below | `currency` | Registry `("revenue",)`; adds `"order"` outside transaction grain → B + revenue + order | `("revenue",)` |
| `gross_profit` | Gross profit | Σ (net line value − cost) over contributing rows with cost | `SUM(net_value - cost_value) FILTER (WHERE contributes)` | `currency` | `("revenue", "cost")` → B + revenue + cost | `("revenue", "profit")` |
| `gross_margin` | Gross margin | Gross profit ÷ net revenue (rows with cost) | `SUM(net_value - cost_value) FILTER (WHERE contributes) / NULLIF(SUM(net_value) FILTER (WHERE contributes), 0)` | `ratio` | `("revenue", "cost")` → B + revenue + cost | `("revenue", "profit")` |
| `return_rate` | Return rate | Returns & credits ÷ net sales before returns | `(-SUM(net_value) FILTER (WHERE contributes AND is_return)) / NULLIF(SUM(net_value) FILTER (WHERE contributes AND NOT is_return), 0)` | `ratio` | `("revenue",)` → B + revenue | `("revenue", "returns", "line_revenue")` |

The four `aov` SQL expansions combine `revenue_expression` and `orders_expression`:

```sql
-- Line revenue; order or line grain
(SUM(net_value) FILTER (WHERE contributes)) / NULLIF(COUNT(DISTINCT order_id) FILTER (WHERE contributes AND NOT is_return), 0)
-- Line revenue; transaction grain
(SUM(net_value) FILTER (WHERE contributes)) / NULLIF(COUNT(*) FILTER (WHERE contributes AND NOT is_return), 0)
-- Order-total revenue; order or line grain
(SUM(order_value_once) FILTER (WHERE contributes)) / NULLIF(COUNT(DISTINCT order_id) FILTER (WHERE contributes AND NOT is_return), 0)
-- Order-total revenue; transaction grain
(SUM(order_value_once) FILTER (WHERE contributes)) / NULLIF(COUNT(*) FILTER (WHERE contributes AND NOT is_return), 0)
```

`metric_definition` changes the displayed `orders` label to `Transactions` at transaction grain; the registry formula text remains as quoted. Counts of orders/customers/units use their own scopes and can include rows lacking a valid revenue amount. AOV's denominator uses the revenue-classified rows, so it can differ from the standalone orders KPI. Returns-only orders do not enter either sales-order denominator. `SUM` over no matching values and a zero-denominator division can return NULL; `as_float` preserves that as `None` rather than inventing zero.

### Exclusions and precedence

`classified_cte` filters first, then assigns exactly one primary reason through a `CASE` in this order. Conditions below are the source SQL conditions; the first four also require their policy parameter to be true.

| Order | Reason | Exact `EXCLUSION_LABELS` label | Condition / enabling scope |
|---:|---|---|---|
| 1 | `blank_row` | Blank rows | `is_blank`; `exclude_blank_rows` |
| 2 | `duplicate_reliable` | Confirmed duplicates (same transaction ID, identical content) | `dup_reliable`; `exclude_reliable_duplicates` |
| 3 | `duplicate_possible` | Possible duplicates (identical rows; excluded only if you opt in) | `dup_possible`; `exclude_possible_duplicates` |
| 4 | `cancelled` | Cancelled orders | `is_cancelled`; `exclude_cancelled` |
| 5 | `order_total_conflict` | Orders whose total differs between their lines | `order_total_conflict`; `"revenue"` scope and `revenue_basis == "order_total"` |
| 6 | `invalid_amount` | Missing or unreadable amount | `value_invalid`; `"revenue"` |
| 7 | `invalid_date` | Missing or unreadable date | `date_invalid`; `"date"` |
| 8 | `invalid_quantity` | Missing or unreadable quantity | `quantity_invalid`; `"quantity"` |
| 9 | `missing_customer` | No customer identifier | `customer_id IS NULL`; `"customer"` |
| 10 | `missing_order` | No order identifier | `order_id IS NULL`; `"order"` |
| 11 | `missing_cost` | No cost recorded | `cost_value IS NULL`; `"cost"` |

Base policies default to true except `exclude_possible_duplicates=False` (`POLICY_DEFAULTS`). Scope exclusions remain active even when all policies are off. `compute_metric` obtains value and classification counts in the same statement: `input_records = contributing_records + excluded_total`. Outside-filter rows are reported separately as `rows_outside_active_filters`.

`FLAG_LABELS` is a separate, overlapping set. Debugger flag counts apply only to contributing rows; they are not a second exclusion partition. The Quality Explorer's [`flag_counts`](../mieru/quality/explorer.py) instead counts whole-file issues, omitting blank rows from other issue counts.

| Flag | Exact `FLAG_LABELS` label |
|---|---|
| `dup_possible` | Possible duplicates (kept) |
| `key_conflict` | Same ID, conflicting values (kept) |
| `negative_unverified` | Negative amounts with unverified meaning (kept as recorded) |
| `is_outlier` | Statistical outliers (kept, flagged only) |
| `is_ragged` | Malformed rows (wrong number of fields) |
| `text_normalized` | Text values normalised (trim / case) |
| `is_return` | Returns / credits (netted) |

### Capabilities

Source: [`build_canonical`](../mieru/canonical/build.py). `DatasetContext.capability` returns the stored availability and reason. `line_revenue` is a special requirement checked in `metric_availability`: basis must be in `LINE_BASES = {"line_amount", "quantity_x_unit_price", "unit_price_one_unit_per_row"}`.

| Capability | Availability condition |
|---|---|
| `revenue` | Recognized revenue basis and `currency_status != "multiple"` |
| `orders` | Always available; transaction grain counts non-return contributing rows |
| `customers` | `customer_id` assigned |
| `units` | Parsed `quantity` series exists |
| `trend` | Assigned `order_date` and parse rate ≥ `MIN_DATE_PARSE_RATE = 0.8` |
| `products` | `product_name` or `product_id` assigned |
| `categories` | `category` assigned |
| `regions` | At least one of `region`, `country`, `city` assigned |
| `channels` | `channel` assigned |
| `discounts` | Parsed discount series exists and basis is not `order_total` |
| `returns` | Any row identified as a return, or parsed `refund_amount` role exists |
| `profit` | Any non-NULL `cost_value` and basis in `LINE_BASES`; explicitly disabled for `order_total` |

## 2. Revenue semantics

Source: [`mieru/canonical/build.py`](../mieru/canonical/build.py), [`mieru/schema/aliases.py`](../mieru/schema/aliases.py), [`mieru/schema/parsing.py`](../mieru/schema/parsing.py), [`classified_cte`](../mieru/metrics/upload.py).

### Grain and revenue basis

`ORDER_ID_COVERAGE = 0.9` measures nonblank order-ID coverage. When covered, distinct nonblank rows after ignoring exact duplicates determine `line` (order IDs repeat) or `order` (unique). Otherwise grain is `transaction`.

| Priority | `revenue_basis` | Canonical value and aggregation |
|---:|---|---|
| 1 | `line_amount` | `line_value = line_amount`; aggregate `net_value` |
| 2 | `quantity_x_unit_price` | `line_value = quantity * unit_price`; aggregate `net_value` |
| 3 | `order_total` | `line_value` / `net_value` are unavailable; aggregate `order_value_once` from `order_total` |
| 4 | `unit_price_one_unit_per_row` | `line_value = unit_price`; explicit one-unit-per-row assumption and quantity clarification |
| — | `None` | Revenue unavailable |

A generic mapped `amount` starts as a line amount. At line grain, promotion to order total requires `ORDER_TOTAL_CONSTANCY_THRESHOLD = 0.98` (share of multi-line orders whose non-NULL amount has one distinct value), product variation in more than half of relevant orders when product data exists, and enough evidence. Enough evidence means order-level naming or `MIN_ORDER_TOTAL_EVIDENCE = 2` evidence orders. Product variation is accepted when no product column is mapped. `LINE_LEVEL_TOKENS = ("line", "item", "明細", "商品別")` or a user-mapped `amount` prevents promotion. Insufficient evidence for an otherwise constant amount produces an `ambiguous_role` clarification while retaining line amounts. `ORDER_LEVEL_TOKENS = ("order", "invoice", "basket", "cart", "receipt", "注文", "伝票")` provides order-name evidence.

`order_total_conflict` marks orders with more than one distinct non-NULL total, ignoring reliable duplicates and blank rows for this check. In revenue scopes with an order-total basis, every such row is excluded. For nonconflicting orders, the classifier ranks rows by `_row_id` within `(order_id, contributes)` and selects the first contributing row's total. Filtering happens before ranking: "once per order" is within that query scope. A NULL `order_id` uses its own row total. Order-total financial values are not allocated to line-level product/category breakdowns, profitability or return/discount KPIs.

`tax`, `shipping` and `refund_amount` are stored separately. The revenue expressions do not separately add tax/shipping or subtract `refund_amount`; they use the selected amount/price/order-total basis.

### Discounts

Numeric parsing converts percent strings to fractions. A discount is treated as a rate when the profile's `percent_share > 0.5`, or when `numeric_max <= 1.0`, `integer_share < 0.5`, and its normalized name contains `rate`, `pct` or `percent`. Rate amount is initially `abs(discount_raw) * base`, where base is quantity × unit price when both exist, otherwise `line_value`; non-rate discounts use `abs(discount_raw)`. The final canonical `discount_value` is made absolute before net-value calculation.

For a line amount with quantity and unit price, relation checks compare `line_amount` with gross reference and gross reference minus discount. `relation_matches` allows `max(RELATION_TOLERANCE_ABS = 0.011, RELATION_TOLERANCE_REL = 0.005 * abs(reference))`. With `RELATION_MATCH_THRESHOLD = 0.9`:

| Evidence | Treatment |
|---|---|
| Net match ≥ 0.9 and better than gross match | `value_is_net_of_discount=True`; do not deduct again |
| Otherwise gross match ≥ 0.9 | Deduct discount to derive net value |
| Neither relation verified | Treat amount as final line value; report discounts separately and record assumption |
| Line amount without quantity/price pair | Treat amount as final; no second deduction |
| Derived quantity × price or one-unit-per-row price | Deduct the discount; amount discounts are per line, not per unit |

`gross_sales` sums `signed_value` on sale rows. If the source amount is already net, that stored value is still used; the performance bridge labels it "Sales after discounts" when recorded discounts exist but no deduction was applied. `discounts_value` reports recorded sales-row discounts irrespective of whether they were separately deducted.

### Returns, cancellations, costs and duplicates

`normalize_status` scans `STATUS_TOKENS` in order (`cancelled`, `returned`, `completed`, `pending`), using substring matches on lowercased text; unmatched text becomes `other`. Cancellation tokens include `cancel`, `void`, `キャンセル`, `取消`, `cancelado`, `anulado`; return tokens include `return`, `refund`, `返品`, `返金`, `devolvido`, `devuelto` (the complete tuples are in `aliases.py`).

A row becomes `is_return` if status normalizes to `returned`, an explicit mapped return flag belongs to `TRUE_TOKENS = {"true", "yes", "y", "1", "t", "はい", "sim", "si", "returned"}`, or quantity is negative, **and** the row is not cancelled. A positive return `line_value` becomes negative `signed_value`; already negative values remain negative. Positive order totals are likewise negated for return rows. An unmarked negative signed value is retained with `negative_unverified=True`.

When no discount is mapped or the amount is already net, `net_value = signed_value`. Otherwise subtract the discount on sales and add its magnitude back on returns: a 100 sale with a 10 discount contributes +90; its corresponding return contributes −90. `returns_value = -SUM(net_value)` on return rows. A refund column alone enables the returns capability but does not itself mark a row as a return or enter this arithmetic.

`cost_value` prefers `line_cost`; otherwise it uses `unit_cost * abs(quantity)`, or unit cost alone for the one-unit-per-row basis. Return costs become `-abs(cost_value)`. This records the assumption that returned goods go back into stock; a fully returned sale then cancels revenue and cost. Missing cost excludes a row only from cost-scoped measures.

`row_signatures` hashes raw cell content after filling nulls with `"\u0000"`. Reliable duplicate keys are `line_id` (combined with `order_id` when order coverage is sufficient), or `order_id` at order grain. Repeated key **and** signature marks only later copies `dup_reliable`. Same key with different signatures becomes `key_conflict` and is kept. Exact duplicate signatures not classed reliable become `dup_possible` and are kept by default. Blank rows do not become duplicates. Outliers use absolute robust z-score `abs(value - median) / (1.4826 * MAD) > OUTLIER_ROBUST_Z = 8.0`, require `OUTLIER_MIN_ROWS = 20` eligible values, and are flags only; zero MAD produces no outlier flags.

### Currency

`build_canonical` combines uppercase values from mapped `currency` with detected currency codes in mapped `amount`, `order_total`, `unit_price` profiles. One code gives `currency_status="single"`; none gives `"unknown"` and no currency symbol; multiple codes give `"multiple"`, a clarification and disabled revenue capability. There is no conversion step in these computations. [`CURRENCY_SYMBOL_CODES`](../mieru/schema/parsing.py) maps bare `$` to `USD` and `¥` / `円` to `JPY`.

## 3. Performance analytics

Source: [`mieru/analytics/performance.py`](../mieru/analytics/performance.py). `scoped_query` reuses `classified_cte`. Bridge, profitability, returns and discounts require available revenue and a basis in `LINE_BASES` (`line_revenue_gate`); their additional capability gates are `profit`, `returns` or `discounts` as applicable.

| Function | Definition and behavior |
|---|---|
| `build_bridge` | Revenue-scoped `gross_sales = SUM(signed_value)` on non-return rows; `discounts_deducted = SUM(signed_value - net_value)` on non-return rows; `returns_value = -SUM(net_value)` on return rows; `net_revenue = SUM(net_value)` on all contributors. Identity: **Gross sales − discounts deducted − returns & credits = net revenue**. Reconciles when absolute residual ≤ `VALUE_TOLERANCE = 0.005` + `1e-9 * abs(net_revenue)`. Optional discount/return steps require magnitude > 0.005. Cost and gross-profit steps appear only with profit capability, at least one contributing row and zero rows missing cost; partial coverage is reported instead |
| `build_profitability` | Scopes `("revenue", "cost")`; revenue/cost/profit sum only rows with cost; profit = net value − cost. Overall/group margin is profit ÷ revenue only when revenue > 0. Coverage reports rows with cost and their revenue share relative to revenue-only scope. `GROUP_LIMIT = 15`; lowest `LOWEST_MARGIN_LIMIT = 5` margins among groups with revenue share ≥ `MATERIAL_REVENUE_SHARE = 0.01`; loss-making means profit < −0.005 |
| `build_returns` | Value-based return rate = returned net value ÷ non-return net sales (after discounts, before returns), only when net sales > 0. Sale/return row counts are separate. Groups with fewer than `SMALL_SAMPLE_ROWS = 30` sales rows are marked `small_sample` |
| `build_discounts` | Non-return contributors: discounts = `SUM(COALESCE(discount_value, 0))`; list value = `SUM(net_value + COALESCE(discount_value, 0))`; discount rate = discounts ÷ list value when positive. Discounted rows have `discount_value > 0`; discounted-row share = discounted rows ÷ sales rows. `treatment="deducted"` when absolute sum of `signed_value - net_value` on sales exceeds 0.005, otherwise `"already_net"` |

Available group dimensions are `categories`, `products`, `channels`, `regions`; NULL labels become `"(not specified)"`. Profit, return and discount group tables return at most 15 rows. Discount monthly trends add date scope and require at least two month groups; the discounted/full-price margin split requires both groups and uses revenue/cost scopes on non-return rows. These descriptive comparisons do not estimate the incremental effect of promotions.

`build_concentration` supports line-level product revenue and customer revenue (including order-total basis for customers). Customer concentration adds customer scope; product NULLs form the unspecified group. `pareto_summary` removes items with net revenue ≤ 0, reporting `excluded_non_positive`, and requires `MIN_CONCENTRATION_ITEMS = 5` positive items. Items are sorted descending with stable ordering. The top-10% / top-20% shares use `max(1, ceil(fraction * item_count))` items; counts for 50%/80% use the first cumulative share reaching `share - 1e-12`. The descending Pareto curve begins at `(0,0)`, uses every item up to `PARETO_STEPS = 100`, otherwise 100 sampled steps. Top five product labels are returned; customer labels are not.

Gini calls [`src.analysis.lorenz_gini`](../src/analysis.py): sort ascending, prepend `(0,0)` to cumulative population/value shares, and calculate `1.0 - 2.0 * trapezoid_integral(cumulative_value_share, cumulative_population_share)`. The Gini and descending Pareto curve use the same positive-item set.

## 4. Customer intelligence

Source: [`mieru/analytics/customers.py`](../mieru/analytics/customers.py): `upload_customer_orders`, `customer_intelligence`, `percentile_scores`, `frequency_scores`, `assign_segment`, `build_upload_customers`. The upload builder requires `customers`, `trend` and `revenue` capabilities.

`upload_customer_orders` uses `("revenue", "date", "customer")` plus `"order"` outside transaction grain. It groups by `(customer_id, order_key)`, where `order_key` is `order_id` or string `_row_id` for transactions; order date is `MIN(order_ts)`, revenue sums `net_value` or `order_value_once`, and `is_sale = BOOL_OR(NOT is_return)`.

`customer_intelligence` drops missing customer/date, normalizes dates to calendar days and requires sale orders. It forms the customer population from sale orders; frequency is distinct sale `order_key`, first/last order are first/last sale dates, and monetary value sums all net order revenue (including returns) for those customers. Gates are `MIN_CUSTOMERS = 50` sale customers and `MIN_SPAN_DAYS = 60` between minimum/maximum clean order dates.

Recency is days from one day after the latest clean order date to the last sale. With `SCORE_BINS = 5`, monetary scores use `ceil(average_percentile_rank * 5)` clipped to 1–5; recency reverses the percentile as `1 - rank + 1 / n` before the same calculation. Frequency is 1 for single-purchase customers; repeaters (frequency ≥ 2) use `clip(ceil(average_percentile_rank * 4), 1, 4) + 1`. Ties share a score. Monetary is scored but does not determine segments: `assign_segment` uses R and F only, in this exact order.

| Priority | Predicate | Segment |
|---:|---|---|
| 1 | `recency_score >= 4 and frequency_score >= 4` | Champions |
| 2 | `frequency_score >= 4` | Loyal customers if `recency_score >= 3`, otherwise At risk |
| 3 | `recency_score == 5 and frequency_score <= 1` | New customers |
| 4 | `recency_score >= 4` | Potential loyalists |
| 5 | `recency_score <= 2 and frequency_score >= 3` | At risk |
| 6 | `recency_score <= 2` | Hibernating |
| 7 | Otherwise | Needs attention |

`REPEAT_HORIZON_DAYS = 90`: eligibility requires first sale date ≤ data end − 90 days. The repeat statistic is exposed only with at least 50 eligible customers. A repeat sale must be on a **later calendar day** than the first purchase and no later than first purchase + 90 days. The rate is distinct eligible repeaters ÷ eligible customers; same-day split orders do not count as a later visit. This differs from the Decision Center's uncensored `repeat_customers` rule.

Cohorts use first-sale calendar month, distinct sale customers active per month, and `MAX_COHORT_PERIODS = 12` (returned periods 0–12). `last_complete_month` is the data-end month only when the last clean date is that month's final calendar day; otherwise it is the previous month. For each cohort, `observable = min(12, max(0, last_complete_month - cohort))`. Periods above it are NULL, observable inactive cells are zero, and retention is `100 * active_customers / cohort_size`. The `max(0, ...)` keeps M0 observable even for the newest cohort.

Each customer has one segment, so segment customer counts and revenue sum to the customer population and its monetary total. Upload `reconciliation` returns `segment_revenue_total`, unfiltered dashboard `net_revenue`, and their `difference`. This is a diagnostic, not a universal equality: customer SQL requires dates/customer IDs and (outside transaction grain) order IDs, and customers with returns but no sale order are not in the RFM population. Top ten customers are ordered by monetary value and displayed as `Customer …` plus the final four ID characters.

For Olist, [`build_olist_customer_intelligence`](../mieru/api/olist.py) passes delivered orders with non-NULL `order_gmv`, `customer_unique_id` as customer ID, and GMV as monetary value to the same function. It compares segment revenue with platform `SUM(order_gmv)`.

## 5. Forecasting

Source: [`mieru/forecast/engine.py`](../mieru/forecast/engine.py). Upload [`get_forecast`](../mieru/api/datasets.py) uses unfiltered `build_trend`, choosing `revenue` when available and otherwise `orders`. [`build_olist_forecast`](../mieru/api/olist.py) uses monthly GMV from `mart_olist_monthly`, excludes dates before `OLIST_FORECAST_START = "2017-01-01"`, then calls the same engine.

`regularize` discards partial periods and NULL measures, creates a regular calendar from the first through last remaining period, and fills missing periods with zero, recording the count. Daily input is unavailable. History gates are `MONTHLY_MIN_PERIODS = 18`, `WEEKLY_MIN_PERIODS = 30`; total series sum must be positive. In [`choose_granularity`](../mieru/analytics/dashboard.py), upload spans ≤62 days are daily, ≤370 days weekly, otherwise monthly.

| Model ID | Exact `MODEL_LABELS` label | Implementation |
|---|---|---|
| `naive` | Naive (last value) | Repeat the most recent value |
| `seasonal_naive` | Seasonal naive (same period last year) | Value 12 months earlier (`MONTHLY_SEASON = 12`); unavailable for weekly series |
| `moving_average` | Moving average | Recursive mean of last 3 monthly or 4 weekly values (`MOVING_AVERAGE_WINDOW`) |
| `ridge` | Ridge regression (lags + trend + seasonality) | `StandardScaler` fitted to training features; `Ridge(alpha=1.0)` |
| `random_forest` | Random forest (lags + trend + seasonality) | Same scaled features; `RandomForestRegressor(n_estimators=100, max_depth=4, min_samples_leaf=2, random_state=42)` |

Regression features are `LAG_COUNT = 3` previous values, the numeric period index, and sine/cosine of calendar position: `(month - 1) / 12` or `(ISO week - 1) / 52`, multiplied by `2π`. `MIN_TRAINING_ROWS = 8` applies after dropping the first three lag positions. Forecasts are recursive and each predicted step is clipped with `max(0.0, value)` before reuse.

Holdout and horizon constants are monthly 6/6 and weekly 8/8 (`MONTHLY_HOLDOUT`, `MONTHLY_HORIZON`, `WEEKLY_HOLDOUT`, `WEEKLY_HORIZON`). With `HOLDOUT_SHARE = 0.35` and `MIN_TRAIN_PERIODS = {"month": 12, "week": 16}`, the exact sizing is:

```text
holdout = max(base_holdout,
              min(int(0.35 * n_periods), n_periods - MIN_TRAIN_PERIODS[granularity]))
```

`backtest` uses origins `range(total - holdout, total)`. At each origin, every model fits only earlier periods and predicts `min(horizon, total - origin)` steps. A model unavailable at any origin is removed from the returned model set. Errors are observed minus predicted, grouped by horizon. `summarize_errors` reports MAE/RMSE over all origin/horizon errors and one-step MAE. `skill_vs_naive = 1 - model_mae / naive_mae` when the naive MAE is nonzero. Selection minimizes `(mae, MODEL_COMPLEXITY[model])`, where complexity is naive 0, seasonal naive 1, moving average 2, Ridge 3, forest 4. The selected model is refitted on all history for the final path.

Intervals appear only if **every** forecast horizon has at least `MIN_INTERVAL_RESIDUALS = 20` selected-model backtest errors. At `INTERVAL_LEVEL = 0.8`, radius is `np.quantile(abs(errors_at_horizon), 0.8)`; bounds are `[max(0, prediction - radius), prediction + radius]`. Otherwise all bounds are NULL and the payload reports why. The code calls this an empirical, "split-conformal style" interval; it does not provide an unconditional coverage guarantee.

## 6. Decision Center rules

[`InsightCard`](../mieru/insights/cards.py) contains `finding`, `evidence`, `interpretation`, `action`, `limitations` and `gates`; allowed kinds are `opportunity`, `risk`, `info`, `quality`, and confidence is `high` or `medium`. Rule execution is deterministic.

### Upload rules

Source: [`mieru/insights/upload.py`](../mieru/insights/upload.py). `build_upload_insights` evaluates the functions below through the shared classifier/metric builders. `confidence_for(rows)` is high at `HIGH_CONFIDENCE_ROWS = 500`, otherwise medium. `line_revenue_ok` requires revenue capability and a basis other than `order_total`. Unless noted, numerical gates are inclusive; significance is strictly `< SIGNIFICANCE_LEVEL = 0.05`. Failed gates return `skipped(rule, reason)`.

| Rule ID / function | Capability and sample gates | Trigger / selection | Confidence |
|---|---|---|---|
| `revenue_trend` | Readable trend with revenue; ≥2 complete periods; each of last two has ≥`MIN_PERIOD_ORDERS = 30` orders/transactions; prior revenue nonzero | `abs((current - previous) / abs(previous)) >= TREND_CHANGE_THRESHOLD = 0.10`; latest complete pair only. Same-month-prior-year evidence added for monthly input when present/nonzero | `confidence_for(current orders + previous orders)` |
| `product_concentration` | Product capability and line revenue; ≥`MIN_PRODUCTS = 10` products with positive net revenue and non-NULL product key | Top `ceil(0.2 * product_count)` share ≥`PRODUCT_CONCENTRATION_THRESHOLD = 0.60` | `confidence_for(sum of positive-product line counts)` |
| `category_returns` | Returns/categories and line revenue; categories with ≥`MIN_CATEGORY_LINES = 30` sale lines; ≥`MIN_CATEGORY_RETURNS = 5` returns overall and in candidate; positive rest-of-category sales and returns | Candidate return-lines ÷ sale-lines ≥`RETURN_RATE_MULTIPLIER = 1.5` × overall line rate, and `two_proportion_tests(...)["chi2_p_value"] < 0.05` against all other categories. Choose highest passing rate | High if selected category sale lines ≥500 |
| `discount_impact` | Discounts and line revenue; computed discounts nonzero and positive list value | `discounts / list_value >= DISCOUNT_SHARE_THRESHOLD = 0.03`, where list value = `SUM(net_value + COALESCE(discount_value, 0))` on contributing sale rows (the same discount rate as the Performance page). If profit exists, append discounted/full-price margins only when both groups have ≥30 non-return cost-covered lines | Always medium |
| `low_margin_category` | Profit/categories and line revenue; ≥2 categories, summed category revenue >0; candidate share ≥`CATEGORY_MIN_REVENUE_SHARE = 0.05` and lines ≥30 | Choose lowest eligible profit/revenue margin; overall margin minus candidate margin ≥`MARGIN_GAP_THRESHOLD = 0.10` | `confidence_for(candidate lines)` |
| `customer_concentration` from `customer_concentration` | Customers/revenue and non-order-total basis; ≥`MIN_CUSTOMERS = 50` customer groups under revenue/customer/order scopes (order scope omitted for transactions) | Among positive-revenue customers, top `ceil(0.1 * positive_count)` share ≥`CUSTOMER_CONCENTRATION_THRESHOLD = 0.40` | `confidence_for(positive customer count)` |
| `repeat_customers` from `customer_concentration` | Same capability/sample gate as the preceding row | Always emits after the 50-customer gate; rate = share of customer groups with ≥2 sale orders/transactions. No 90-day eligibility gate | `confidence_for(all customer groups)` |
| `region_concentration` from `group_concentration` | Regions and line revenue; ≥3 non-NULL region groups; total region revenue >0 | Largest group's revenue share ≥`REGION_CONCENTRATION_THRESHOLD = 0.40` | Always medium |
| `channel_aov_gap` from `group_concentration` | Channels and line revenue; grain is not `transaction`; ≥2 non-NULL channels with ≥`MIN_GROUP_ORDERS = 30` sale orders each | Highest channel AOV ÷ lowest channel AOV ≥`CHANNEL_AOV_RATIO = 1.3`; lowest AOV must be positive (otherwise ratio 0). AOV here is channel net revenue ÷ sale orders | `confidence_for(sum of eligible channel orders)` |
| `data_quality` | Uses `net_revenue` if available, otherwise `orders`; input record count >0 | Excluded/input ≥`EXCLUSION_SHARE_THRESHOLD = 0.02`; largest primary reason reported; delta compares active policies with all `POLICY_DEFAULTS` keys set false | Always high |

The category-return rule uses **line counts** (returned lines ÷ sales lines, as required by its χ² test) and labels them that way; the value-based return rate is the `return_rate` KPI and the Performance page. The discount insight uses the same discount rate as the Performance page. Region/channel outcomes are evaluated only when their capability branches execute, so `rules_evaluated = len(outcomes)` need not be a constant ten. The API insights endpoint uses no dashboard filters; report exports can pass filters directly to `build_upload_insights`.

### Olist rules

Source: [`mieru/olist/insights.py`](../mieru/olist/insights.py). `build_olist_insights` builds these six cards from research JSON and marts, with `confidence="high"` and `skipped=[]`. Except state eligibility, displayed `gates` are evidence annotations rather than conditional trigger tests; no additional numerical firing threshold is imposed.

| Rule ID | Source and evidence / gate |
|---|---|
| `sla_breach_detractors` | `two_sample_tests.severe_detractor`; `logistic_models.model_1_severe_detractor` term `is_sla_breached`; `model_1_fixed_effects_robustness`; excess-event share and platform breach rate. Gate text uses Model 1 `n_obs` and `"HC0 robust standard errors"` |
| `promise_cliff` | `sla_threshold_discontinuity`: Day 0 vs Day +1 severe-detractor rates/jump and Day −1 vs Day 0 placebo jump/p-value; gate text includes the two day sample sizes |
| `seller_concentration` | `seller_concentration`: sellers for 80% GMV, Gini, top-tier GMV share/count, breach rates for `"Top 10% Sellers"` and `"Bottom 50% Long-Tail"`; gate text reports `tier_sla_breach_independence_test.p_value` |
| `retention_structural` | `platform_kpis` single/repeat purchase and fixed-180-day rates; `model_2c_repeat_within_180d_after_delivery` breach odds ratio/p-value and `n_obs`; no significance filter controls emission |
| `state_breach_hotspot` | `mart_olist_state`: select highest breach rate among states with `delivered_orders >= MIN_STATE_ORDERS = 500`; also report highest-GMV state. This builder assumes an eligible state exists |
| `payment_mix` | Largest `payment_value` row of `mart_olist_payments`, its `payment_value_share` and `mean_installments`; gate text is `"All payment records of delivered orders"` |

`OBSERVATIONAL_CAVEAT` is `"Observational data: this is an adjusted association, not a randomised causal estimate."` The delivery card carries that caveat; the local promise comparison and retention cards also expose their observational/censoring limitations. The existence of a card is not a fresh hypothesis-test pass.

## 7. Olist metrics and market scorecards

### `OLIST_METRICS`

Source: [`mieru/olist/metrics.py`](../mieru/olist/metrics.py), [`sql/01_mart_order_fulfillment.sql`](../sql/01_mart_order_fulfillment.sql), [`sql/03_mart_seller_pareto.sql`](../sql/03_mart_seller_pareto.sql). `OLIST_CURRENCY = "BRL"`. `mart_order_fulfillment` inner-joins customers and requires `order_status='delivered'` with non-NULL purchase, delivered-customer and estimated-delivery timestamps. Items and reviews are pre-aggregated by `order_id` before joins; the person identifier is `customer_unique_id`.

| Metric ID | Label / unit | Definition / executed value expression | Definition grain; explanation record grain / exclusions |
|---|---|---|---|
| `olist.gmv` | GMV / `currency` | `SUM(order_gmv)`; order GMV = sum of item `price + freight_value` | Order; delivered order; NULL GMV excluded as `no_items` |
| `olist.product_sales` | Product sales / `currency` | `SUM(items_price)`; item prices without freight | Order; delivered order; NULL `items_price` → `no_items` |
| `olist.freight` | Freight charged / `currency` | `SUM(freight_value)` on order aggregates | Order; delivered order; NULL freight → `no_items` |
| `olist.payment_value` | Payments received / `currency` | `SUM(payment_value)` from `raw_order_payments` inner-joined to delivered orders; includes vouchers | Payment record; payment record; NULL values → `missing_value`; context includes delivered orders without payment and GMV for reconciliation |
| `olist.delivered_orders` | Delivered orders / `count` | `COUNT(*)` from `mart_order_fulfillment` | Order; delivered order; all mart rows contribute |
| `olist.customers` | Unique customers / `count` | `COUNT(DISTINCT customer_unique_id)` | Customer; delivered order; NULL customer IDs → `no_customer` |
| `olist.aov` | Average order value / `currency` | `AVG(order_gmv)` (registry formula `SUM(order_gmv) / COUNT(order_gmv)`) | Order; delivered order; NULL GMV → `no_items` |
| `olist.sla_breach_rate` | SLA breach rate / `ratio` | `AVG(CAST(is_sla_breached AS DOUBLE))`; `sla_delay_days = DATE_DIFF('day', CAST(estimated AS DATE), CAST(delivered AS DATE))`, breach iff >0 | Order; delivered order |
| `olist.mean_review_score` | Mean review score / `score` | `AVG(review_score)`; average source review score per order first, then average across reviewed orders | Order; delivered order; NULL review → `no_review` |
| `olist.severe_detractor_rate` | Severe detractor rate / `ratio` | `AVG(CAST(is_severe_detractor AS DOUBLE))`; order mean review ≤2.0, NULL for unreviewed | Order; delivered order; NULL outcome → `no_review` |
| `olist.repeat_purchase_rate` | Repeat purchase rate / `ratio` | `AVG(CAST(is_repeat_buyer AS DOUBLE)) FILTER (WHERE customer_order_seq = 1)`; repeat means customer has ≥2 delivered orders | Customer; delivered order; sequence >1 → `later_orders` |
| `olist.median_delivery_days` | Median delivery time / `days` | `MEDIAN(actual_delivery_days)`; whole-day purchase-to-delivery difference after DATE casts | Order; delivered order |
| `olist.active_sellers` | Active sellers / `count` | `COUNT(*)` from `mart_seller_pareto` | Seller; seller |
| `olist.seller_gmv_gini` | Seller GMV Gini / `index` | SQL value placeholder NULL; `seller_gini_from_mart` applies `src.analysis.lorenz_gini` to `mart_seller_pareto.seller_gmv` | Seller; seller |
| `olist.seller_share_for_80pct_gmv` | Sellers generating 80% of GMV / `share` | `CAST(MIN(seller_rank) FILTER (WHERE cumulative_gmv_share >= 0.8 - 1e-12) AS DOUBLE) / COUNT(*)` | Seller; seller |
| `olist.gross_profit` | Gross profit / `currency` | Unavailable; registry formula `"Not computable"`, no SQL | Order; no count object; no product-cost or commission columns |

The SLA source columns are `order_estimated_delivery_date` and `order_delivered_customer_date`; purchase-to-delivery uses `order_purchase_timestamp`. `customer_order_seq` sorts by purchase timestamp then order ID. The uncensored repeat metric includes any later order before data end, including same-day split baskets. The separate mart field `is_repeat_within_180d_after_delivery` is NULL below 180 days of post-delivery follow-up, otherwise indicates a subsequent purchase after delivery within 180 days; it is not the upload 90-day first-purchase definition.

`explain_olist_metric` returns metric-specific exclusions plus `PIPELINE_FUNNEL_SQL` context: raw orders, non-delivered orders and delivered orders missing required dates. This upstream context is separate from the metric's mart-level record counts. Seller metrics use seller counts; payment metrics use payment-record counts. GMV is price plus freight, not commission revenue or profit; payment value is a separate measure, so it is not substituted for GMV.

Seller outcomes in `mart_seller_pareto` are first collapsed to `(seller_id, order_id)`; an order involving multiple sellers contributes once to each seller. Ranking is descending seller GMV then ascending seller ID. Tiers are rank/count ≤0.10 (`Top 10% Sellers`), ≤0.50 (`Middle 40% Sellers`), otherwise `Bottom 50% Long-Tail`.

### Market scorecards

Source: [`mieru/olist/markets.py`](../mieru/olist/markets.py), [`sql/05_mart_olist_category.sql`](../sql/05_mart_olist_category.sql), [`sql/06_mart_olist_state.sql`](../sql/06_mart_olist_state.sql), [`src.analysis.proportion_summary`](../src/analysis.py).

| Scorecard | Financial grain and measures | Outcome grain / rate denominators | Reliability |
|---|---|---|---|
| Categories (`build_category_scorecard`) | Item grain: GMV = price + freight, product sales = price, freight = freight value; `freight_share = freight / gmv`, `average_item_price = AVG(price)`, GMV share and rank | Each order counted once per category. SLA events / `outcome_orders`; severe detractors / `reviewed_orders`; mean review and mean delivery are category/order weighted | `MIN_CATEGORY_ORDERS = 200`; `reliable = orders >= 200`. Best/worst review rankings use reliable categories with non-NULL mean review, returning three each |
| States (`build_state_scorecard`) | Delivered-order grain: GMV, GMV share, distinct `customer_unique_id`, AOV, median actual/promised days and distance; `mean_freight_ratio = AVG(freight_ratio)` | Customer state of delivered order. SLA events / `outcome_orders`; severe detractors / `reviewed_orders` | `MIN_STATE_ORDERS = 500`; `reliable = delivered_orders >= 500` |

Missing/blank category names become `uncategorized`. Category GMV sums across items to platform GMV; category **order** counts can overlap across categories. State GMV/orders are additive; distinct customers across states need not be. `rate_interval` calls `proportion_summary(events, trials)`, which uses `proportion_confint(..., alpha=ALPHA, method="wilson")` with `ALPHA = 0.05`: 95% Wilson intervals. It converts percentage fields to fractions and clamps interval ends to contain the returned rate. Zero trials yields NULL rate and bounds.

The code specifies two Spearman associations in advance, rather than searching combinations:

| Scorecard | X | Y | Population |
|---|---|---|---|
| Categories | `sla_breach_rate` | `mean_review_score` | Reliable categories with mean review present |
| States | `median_delivery_days` | `mean_review_score` | Reliable states |

`spearman` drops missing pairs and requires at least five usable groups, then returns `scipy.stats.spearmanr` statistic/p-value and `n_groups`. Both payloads carry the caveat `"A cross-sectional association between groups, not evidence that one causes the other."` Low-volume groups remain visible but are excluded from these associations and category review rankings.
