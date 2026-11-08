from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from mieru.schema.aliases import ROLE_LABELS, STATUS_TOKENS, TRUE_TOKENS
from mieru.schema.infer import InferenceResult
from mieru.schema.parsing import normalize_text
from mieru.schema.profile import ColumnProfile

TEXT_ROLES: tuple[str, ...] = ("order_id", "line_id", "customer_id", "product_id", "product_name")
CATEGORICAL_ROLES: tuple[str, ...] = ("category", "status", "channel", "region", "country", "city", "currency", "payment_method")
NUMERIC_ROLES: tuple[str, ...] = (
    "quantity", "unit_price", "amount", "order_total", "discount", "tax", "shipping", "unit_cost", "line_cost", "refund_amount",
)
ORDER_TOTAL_CONSTANCY_THRESHOLD: float = 0.98
MIN_ORDER_TOTAL_EVIDENCE: int = 2
LINE_LEVEL_TOKENS: tuple[str, ...] = ("line", "item", "明細", "商品別")
ORDER_LEVEL_TOKENS: tuple[str, ...] = ("order", "invoice", "basket", "cart", "receipt", "注文", "伝票")
RELATION_TOLERANCE_ABS: float = 0.011
RELATION_TOLERANCE_REL: float = 0.005
RELATION_MATCH_THRESHOLD: float = 0.9
OUTLIER_ROBUST_Z: float = 8.0
OUTLIER_MIN_ROWS: int = 20
MIN_DATE_PARSE_RATE: float = 0.8
ORDER_ID_COVERAGE: float = 0.9

CANONICAL_COLUMNS: tuple[str, ...] = (
    "_row_id", "order_id", "line_id", "order_ts", "customer_id", "product_id", "product_name", "product_key", "category",
    "status_raw", "status_norm", "channel", "region", "country", "city", "currency", "payment_method",
    "quantity", "unit_price", "line_amount", "order_total", "discount_value", "tax", "shipping", "cost_value", "refund_amount",
    "line_value", "signed_value", "net_value", "is_return",
    "is_blank", "is_ragged", "dup_reliable", "dup_possible", "key_conflict", "is_cancelled", "value_invalid",
    "order_total_conflict", "date_invalid", "quantity_invalid", "negative_unverified", "is_outlier", "text_normalized",
)


@dataclass
class Capability:
    available: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "reason": self.reason}


@dataclass
class CanonicalResult:
    frame: pd.DataFrame
    grain: str
    grain_explanation: str
    revenue_basis: str | None
    revenue_label: str
    value_is_net_of_discount: bool
    currency: str | None
    currency_status: str
    role_columns: dict[str, str]
    capabilities: dict[str, Capability]
    assumptions: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    relational_checks: dict[str, Any] = field(default_factory=dict)
    normalization_changes: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "grain": self.grain,
            "grain_explanation": self.grain_explanation,
            "revenue_basis": self.revenue_basis,
            "revenue_label": self.revenue_label,
            "value_is_net_of_discount": self.value_is_net_of_discount,
            "currency": self.currency,
            "currency_status": self.currency_status,
            "role_columns": self.role_columns,
            "capabilities": {key: value.to_dict() for key, value in self.capabilities.items()},
            "assumptions": self.assumptions,
            "decisions": self.decisions,
            "clarifications": self.clarifications,
            "relational_checks": self.relational_checks,
            "normalization_changes": self.normalization_changes,
        }


def clean_text_series(series: pd.Series) -> pd.Series:
    cleaned = series.map(lambda value: " ".join(normalized.split()) if isinstance(value, str) and (normalized := normalize_text(value)) else None)
    return cleaned.astype("object").where(cleaned.notna(), None)


def unify_case(series: pd.Series) -> tuple[pd.Series, int]:
    cleaned = clean_text_series(series)
    non_null = cleaned.dropna()
    if non_null.empty:
        return cleaned, 0
    counts = non_null.value_counts()
    canonical_by_key: dict[str, str] = {}
    for value in counts.index:
        canonical_by_key.setdefault(str(value).casefold(), str(value))
    unified = cleaned.map(lambda value: canonical_by_key.get(value.casefold(), value) if isinstance(value, str) else None)
    changed = int((series.notna() & (series.astype("object") != unified.astype("object"))).sum())
    return unified, changed


def normalize_status(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    for status, tokens in STATUS_TOKENS.items():
        if any(token in lowered for token in tokens):
            return status
    return "other"


def relation_matches(left: pd.Series, right: pd.Series) -> pd.Series:
    tolerance = np.maximum(RELATION_TOLERANCE_ABS, RELATION_TOLERANCE_REL * right.abs())
    return (left - right).abs() <= tolerance


def match_rate(left: pd.Series, right: pd.Series) -> float | None:
    both = left.notna() & right.notna()
    if both.sum() == 0:
        return None
    return float(relation_matches(left[both], right[both]).mean())


def row_signatures(raw: pd.DataFrame) -> pd.Series:
    filled = raw.astype("object").where(raw.notna(), "\u0000")
    return pd.util.hash_pandas_object(filled, index=False).astype("uint64")


def robust_outliers(values: pd.Series, eligible: pd.Series) -> pd.Series:
    flags = pd.Series(False, index=values.index)
    sample = values[eligible & values.notna()]
    if len(sample) < OUTLIER_MIN_ROWS:
        return flags
    median = float(sample.median())
    mad = float((sample - median).abs().median())
    if mad == 0:
        return flags
    robust_z = (values - median).abs() / (1.4826 * mad)
    return (robust_z > OUTLIER_ROBUST_Z) & eligible & values.notna()


def build_canonical(raw: pd.DataFrame, profiles: list[ColumnProfile], inference: InferenceResult, ragged_row_ids: list[int]) -> CanonicalResult:
    row_count = len(raw)
    index = raw.index
    assignments = dict(inference.assignments)
    role_columns = {role: profiles[column].name for role, column in assignments.items()}
    decisions: list[dict[str, Any]] = []
    assumptions: list[str] = []
    clarifications: list[dict[str, Any]] = list(inference.clarifications)
    normalization_changes: dict[str, int] = {}
    frame = pd.DataFrame(index=index)
    frame["_row_id"] = np.arange(1, row_count + 1, dtype="int64")

    def raw_column(role: str) -> pd.Series | None:
        column = assignments.get(role)
        return raw.iloc[:, column] if column is not None else None

    for role in TEXT_ROLES:
        series = raw_column(role)
        frame[role] = clean_text_series(series) if series is not None else None
    for role in CATEGORICAL_ROLES:
        series = raw_column(role)
        if series is None:
            frame[role] = None
            continue
        unified, changed = unify_case(series)
        frame[role] = unified
        if changed:
            normalization_changes[role] = changed
    numeric: dict[str, pd.Series] = {}
    for role in NUMERIC_ROLES:
        column = assignments.get(role)
        if column is not None and profiles[column].numeric is not None:
            numeric[role] = profiles[column].numeric.values.reindex(index)

    blank = raw.isna().all(axis=1)
    frame["is_blank"] = blank
    ragged = pd.Series(False, index=index)
    if ragged_row_ids:
        ragged.iloc[[row_id - 1 for row_id in ragged_row_ids if 0 < row_id <= row_count]] = True
    frame["is_ragged"] = ragged

    signatures = row_signatures(raw)
    exact_duplicate = signatures.duplicated(keep="first") & ~blank

    has_order = "order_id" in assignments and bool(frame.loc[~blank, "order_id"].notna().mean() >= ORDER_ID_COVERAGE)
    distinct_rows = ~exact_duplicate & ~blank
    if has_order:
        order_ids = frame.loc[distinct_rows, "order_id"].dropna()
        repeated_orders = order_ids.duplicated(keep=False)
        grain = "line" if repeated_orders.any() else "order"
        grain_explanation = (
            f"'{role_columns['order_id']}' repeats across rows ({int(order_ids[repeated_orders].nunique()):,} orders have several rows), "
            "so each row is treated as an order line."
            if grain == "line"
            else f"Each '{role_columns['order_id']}' appears on exactly one row, so each row is one order."
        )
    else:
        grain = "transaction"
        grain_explanation = "No order identifier was detected, so each row is treated as one transaction (orders = rows)."
    decisions.append({"step": "grain", "decision": grain, "detail": grain_explanation})

    if "amount" in assignments:
        amount_values = numeric.get("amount")
        resolved_role = "line_amount"
        if grain == "line" and amount_values is not None:
            multi_line = frame["order_id"].duplicated(keep=False) & distinct_rows & frame["order_id"].notna()
            groups = pd.DataFrame({"order_id": frame.loc[multi_line, "order_id"], "value": amount_values[multi_line]}).dropna()
            if not groups.empty:
                per_order_distinct = groups.groupby("order_id")["value"].nunique()
                product_variation = None
                if "product_id" in assignments or "product_name" in assignments:
                    product_column = "product_id" if "product_id" in assignments else "product_name"
                    product_variation = frame.loc[multi_line].groupby("order_id")[product_column].nunique()
                constancy = float((per_order_distinct == 1).mean())
                varying_products = product_variation is None or float((product_variation > 1).mean()) > 0.5
                amount_name = profiles[assignments["amount"]].normalized_name
                line_named = any(token in amount_name for token in LINE_LEVEL_TOKENS)
                order_named = any(token in amount_name for token in ORDER_LEVEL_TOKENS)
                evidence_orders = int(len(per_order_distinct)) if product_variation is None else int((product_variation > 1).sum())
                user_mapped = "amount" in inference.overridden_roles
                enough_evidence = order_named or evidence_orders >= MIN_ORDER_TOTAL_EVIDENCE
                if constancy >= ORDER_TOTAL_CONSTANCY_THRESHOLD and varying_products and not enough_evidence and not line_named and not user_mapped:
                    clarifications.append(
                        {
                            "kind": "ambiguous_role",
                            "role": "order_total",
                            "label": ROLE_LABELS["order_total"],
                            "columns": [role_columns["amount"]],
                            "message": f"'{role_columns['amount']}' has the same value on every line of the only multi-line order. It is treated as a line amount; "
                            "if it is really an order total, map it as Order total in Advanced mapping.",
                        }
                    )
                if constancy >= ORDER_TOTAL_CONSTANCY_THRESHOLD and varying_products and enough_evidence and not line_named and not user_mapped:
                    resolved_role = "order_total"
                    decisions.append(
                        {
                            "step": "amount_role",
                            "decision": "order_total",
                            "detail": f"'{role_columns['amount']}' is identical on every line of {constancy:.0%} of multi-line orders while products differ, "
                            "so it is an order-level total repeated on each line and is counted once per order.",
                        }
                    )
        if resolved_role == "line_amount":
            decisions.append({"step": "amount_role", "decision": "line_amount", "detail": f"'{role_columns['amount']}' varies within orders, so it is a line-level amount."})
        if resolved_role == "order_total" and "order_total" not in assignments:
            numeric["order_total"] = numeric.pop("amount")
            role_columns["order_total"] = role_columns.pop("amount")
        else:
            numeric["line_amount"] = numeric.pop("amount")
            role_columns["line_amount"] = role_columns.pop("amount")

    quantity = numeric.get("quantity")
    unit_price = numeric.get("unit_price")
    line_amount = numeric.get("line_amount")
    order_total = numeric.get("order_total")
    discount_raw = numeric.get("discount")
    frame["quantity"] = quantity if quantity is not None else np.nan
    frame["unit_price"] = unit_price if unit_price is not None else np.nan
    frame["line_amount"] = line_amount if line_amount is not None else np.nan
    frame["order_total"] = order_total if order_total is not None else np.nan
    frame["tax"] = numeric.get("tax", pd.Series(np.nan, index=index))
    frame["shipping"] = numeric.get("shipping", pd.Series(np.nan, index=index))
    frame["refund_amount"] = numeric.get("refund_amount", pd.Series(np.nan, index=index))

    relational_checks: dict[str, Any] = {}
    revenue_basis: str | None
    value_invalid: pd.Series
    if line_amount is not None:
        revenue_basis = "line_amount"
        line_value = line_amount.copy()
        value_invalid = line_value.isna()
        revenue_label = f"Sum of '{role_columns['line_amount']}'"
        if quantity is not None and unit_price is not None:
            relational_checks["amount_vs_quantity_x_price"] = match_rate(line_amount, quantity * unit_price)
    elif quantity is not None and unit_price is not None:
        revenue_basis = "quantity_x_unit_price"
        line_value = quantity * unit_price
        value_invalid = line_value.isna()
        revenue_label = f"'{role_columns['quantity']}' × '{role_columns['unit_price']}'"
        assumptions.append(f"Line revenue is derived as {revenue_label}; no separate amount column was found.")
    elif order_total is not None:
        revenue_basis = "order_total"
        line_value = pd.Series(np.nan, index=index)
        value_invalid = order_total.isna()
        revenue_label = f"'{role_columns['order_total']}' counted once per order"
        if grain == "line":
            assumptions.append(f"'{role_columns['order_total']}' repeats on each line of an order and is counted once per order to avoid double counting.")
    elif unit_price is not None:
        revenue_basis = "unit_price_one_unit_per_row"
        line_value = unit_price.copy()
        value_invalid = line_value.isna()
        revenue_label = f"Sum of '{role_columns['unit_price']}' (one unit per row)"
        assumptions.append(f"No quantity column was found, so each row is assumed to be one unit sold at '{role_columns['unit_price']}'.")
        clarifications.append(
            {
                "kind": "assumption",
                "role": "quantity",
                "label": ROLE_LABELS["quantity"],
                "columns": [],
                "message": "No quantity column was detected; revenue assumes one unit per row. Map a quantity column in Advanced mapping if one exists.",
            }
        )
    else:
        revenue_basis = None
        line_value = pd.Series(np.nan, index=index)
        value_invalid = pd.Series(False, index=index)
        revenue_label = "Not available"
    decisions.append({"step": "revenue_basis", "decision": revenue_basis or "unavailable", "detail": revenue_label})

    discount_value = pd.Series(np.nan, index=index)
    value_is_net = False
    if discount_raw is not None and revenue_basis in {"line_amount", "quantity_x_unit_price", "unit_price_one_unit_per_row"}:
        discount_profile = profiles[assignments["discount"]]
        looks_like_rate = discount_profile.percent_share > 0.5 or (
            discount_profile.numeric_max is not None and discount_profile.numeric_max <= 1.0 and discount_profile.integer_share < 0.5
            and any(token in discount_profile.normalized_name for token in ("rate", "pct", "percent"))
        )
        gross_reference = quantity * unit_price if (quantity is not None and unit_price is not None) else None
        if looks_like_rate:
            base = gross_reference if gross_reference is not None else line_value
            discount_value = (discount_raw.abs() * base).where(discount_raw.notna())
            decisions.append({"step": "discount", "decision": "rate", "detail": f"'{role_columns.get('discount', 'discount')}' is a rate; discount amount = rate × gross."})
        else:
            discount_value = discount_raw.abs()
        if revenue_basis == "line_amount" and gross_reference is not None:
            gross_rate = match_rate(line_amount, gross_reference)
            net_rate = match_rate(line_amount, gross_reference - discount_value.fillna(0))
            relational_checks["amount_is_gross_rate"] = gross_rate
            relational_checks["amount_is_net_rate"] = net_rate
            if net_rate is not None and net_rate >= RELATION_MATCH_THRESHOLD and (gross_rate is None or net_rate > gross_rate):
                value_is_net = True
                decisions.append({"step": "discount", "decision": "amount_is_net", "detail": f"Amount ≈ quantity × price − discount on {net_rate:.0%} of rows: discounts already deducted."})
            elif gross_rate is not None and gross_rate >= RELATION_MATCH_THRESHOLD:
                decisions.append({"step": "discount", "decision": "amount_is_gross", "detail": f"Amount ≈ quantity × price on {gross_rate:.0%} of rows: discounts are subtracted for net revenue."})
            else:
                value_is_net = True
                assumptions.append("The amount column could not be reconciled with quantity, price and discount; it is treated as the final line value and discounts are reported separately.")
        elif revenue_basis == "line_amount":
            value_is_net = True
            assumptions.append("Without quantity and unit price, the amount column is treated as the final line value; discounts are reported separately, not subtracted.")
        else:
            decisions.append({"step": "discount", "decision": "subtract", "detail": "Discounts are subtracted from quantity × price for net revenue."})
            if not looks_like_rate:
                assumptions.append(
                    f"Values in '{role_columns.get('discount', 'discount')}' are treated as discount amounts per line (not per unit) and subtracted from quantity × unit price."
                )
    frame["discount_value"] = discount_value

    status = frame["status"]
    status_norm = status.map(normalize_status)
    frame["status_raw"] = status
    frame["status_norm"] = status_norm
    frame = frame.drop(columns=["status"])
    is_cancelled = status_norm.eq("cancelled").fillna(False)
    return_flag_series = raw_column("return_flag")
    explicit_return = (
        clean_text_series(return_flag_series).map(lambda value: isinstance(value, str) and value.lower() in TRUE_TOKENS).astype(bool)
        if return_flag_series is not None
        else pd.Series(False, index=index)
    )
    negative_quantity = quantity.lt(0).fillna(False) if quantity is not None else pd.Series(False, index=index)
    is_return = (status_norm.eq("returned").fillna(False) | explicit_return | negative_quantity) & ~is_cancelled
    signed_value = line_value.where(~(is_return & line_value.gt(0)), -line_value.abs())
    discount_value = discount_value.abs()
    frame["discount_value"] = discount_value
    if value_is_net or discount_raw is None:
        net_value = signed_value.copy()
    else:
        discount_magnitude = discount_value.fillna(0)
        net_value = signed_value - discount_magnitude.where(~is_return, -discount_magnitude)
    if order_total is not None:
        order_total = order_total.where(~(is_return & order_total.gt(0)), -order_total.abs())
        frame["order_total"] = order_total
    negative_unverified = signed_value.lt(0).fillna(False) & ~is_return
    frame["line_value"] = line_value
    frame["signed_value"] = signed_value
    frame["net_value"] = net_value if revenue_basis != "order_total" else np.nan
    frame["is_return"] = is_return
    frame["is_cancelled"] = is_cancelled
    frame["negative_unverified"] = negative_unverified

    unit_cost = numeric.get("unit_cost")
    line_cost = numeric.get("line_cost")
    if line_cost is not None:
        cost_value = line_cost.copy()
    elif unit_cost is not None and quantity is not None:
        cost_value = unit_cost * quantity.abs()
    elif unit_cost is not None and revenue_basis == "unit_price_one_unit_per_row":
        cost_value = unit_cost.copy()
    else:
        cost_value = pd.Series(np.nan, index=index)
    if bool((is_return & cost_value.notna()).any()):
        cost_value = cost_value.where(~is_return, -cost_value.abs())
        assumptions.append("Returned items are assumed to go back to stock: their cost is reversed together with their revenue, so a sale that is fully returned adds no profit or loss.")
    frame["cost_value"] = cost_value

    date_column = assignments.get("order_date")
    date_rate = 0.0
    if date_column is not None and profiles[date_column].date is not None:
        dates = profiles[date_column].date.values.reindex(index)
        date_rate = profiles[date_column].date_rate
        frame["order_ts"] = dates
        source_present = raw.iloc[:, date_column].notna()
        frame["date_invalid"] = (dates.isna() & source_present) | ~source_present
    else:
        frame["order_ts"] = pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
        frame["date_invalid"] = False
    frame["quantity_invalid"] = frame["quantity"].isna() if quantity is not None else False

    reliable_key: pd.Series | None = None
    if "line_id" in assignments:
        reliable_key = frame["line_id"] if not has_order else frame["order_id"].fillna("") + "\u001f" + frame["line_id"].fillna("")
        reliable_key = reliable_key.where(frame["line_id"].notna())
        decisions.append({"step": "duplicates", "decision": "line_key", "detail": f"Rows are uniquely identified by '{role_columns['line_id']}'" + (" within each order." if has_order else ".")})
    elif grain == "order":
        reliable_key = frame["order_id"]
        decisions.append({"step": "duplicates", "decision": "order_key", "detail": f"Each order should appear once, so '{role_columns['order_id']}' identifies a row."})
    else:
        decisions.append(
            {
                "step": "duplicates",
                "decision": "no_reliable_key",
                "detail": "No reliable transaction identifier: identical rows may be genuine repeat purchases, so they are flagged but kept.",
            }
        )
    if reliable_key is not None:
        keyed = reliable_key.notna() & ~blank
        signature_groups = pd.DataFrame({"key": reliable_key[keyed], "signature": signatures[keyed]})
        dup_reliable = pd.Series(False, index=index)
        dup_reliable[keyed] = signature_groups.duplicated(subset=["key", "signature"], keep="first").to_numpy()
        conflicting_keys = signature_groups.groupby("key")["signature"].nunique()
        conflicting_keys = set(conflicting_keys[conflicting_keys > 1].index)
        key_conflict = reliable_key.isin(conflicting_keys) & keyed
    else:
        dup_reliable = pd.Series(False, index=index)
        key_conflict = pd.Series(False, index=index)
    frame["dup_reliable"] = dup_reliable
    frame["key_conflict"] = key_conflict
    frame["dup_possible"] = exact_duplicate & ~dup_reliable

    order_total_conflict = pd.Series(False, index=index)
    if order_total is not None and has_order:
        per_order = pd.DataFrame({"order_id": frame["order_id"], "total": order_total})[~frame["dup_reliable"] & ~blank].dropna()
        varying = per_order.groupby("order_id")["total"].nunique()
        conflict_orders = set(varying[varying > 1].index)
        order_total_conflict = frame["order_id"].isin(conflict_orders)
    frame["order_total_conflict"] = order_total_conflict
    frame["value_invalid"] = value_invalid if revenue_basis else False
    outlier_basis = signed_value if revenue_basis != "order_total" else order_total
    frame["is_outlier"] = robust_outliers(outlier_basis, ~blank & ~frame["dup_reliable"]) if outlier_basis is not None else False
    text_changed = pd.Series(False, index=index)
    for role in CATEGORICAL_ROLES:
        series = raw_column(role)
        if series is not None and role in frame.columns:
            text_changed |= series.notna() & (series.astype("object") != frame[role].astype("object"))
        if role == "status" and series is not None:
            text_changed |= series.notna() & (series.astype("object") != frame["status_raw"].astype("object"))
    frame["text_normalized"] = text_changed
    frame["product_key"] = frame["product_name"].where(frame["product_name"].notna(), frame["product_id"])

    currency_codes = set()
    if frame["currency"].notna().any():
        currency_codes = set(frame["currency"].dropna().str.upper().unique())
    for role in ("amount", "order_total", "unit_price"):
        column = assignments.get(role)
        if column is not None:
            currency_codes.update(profiles[column].currency_codes)
    if len(currency_codes) == 1:
        currency = next(iter(currency_codes))
        currency_status = "single"
    elif len(currency_codes) > 1:
        currency = None
        currency_status = "multiple"
        clarifications.append(
            {
                "kind": "multiple_currencies",
                "role": "currency",
                "label": "Currency",
                "columns": sorted(currency_codes),
                "message": f"The file mixes currencies ({', '.join(sorted(currency_codes))}); totals across currencies are not calculated.",
            }
        )
    else:
        currency = None
        currency_status = "unknown"
        if revenue_basis:
            assumptions.append("No currency was detected; amounts are shown without a currency symbol.")

    capabilities = {
        "revenue": Capability(revenue_basis is not None and currency_status != "multiple", None if revenue_basis else "No amount, price × quantity or order-total column was recognised."),
        "orders": Capability(True, None),
        "customers": Capability("customer_id" in assignments, None if "customer_id" in assignments else "No customer identifier column was recognised."),
        "units": Capability(quantity is not None, None if quantity is not None else "No quantity column was recognised."),
        "trend": Capability(
            date_column is not None and date_rate >= MIN_DATE_PARSE_RATE,
            None
            if date_column is not None and date_rate >= MIN_DATE_PARSE_RATE
            else ("No order-date column was recognised." if date_column is None else f"Only {date_rate:.0%} of dates could be interpreted."),
        ),
        "products": Capability("product_name" in assignments or "product_id" in assignments, None if ("product_name" in assignments or "product_id" in assignments) else "No product column was recognised."),
        "categories": Capability("category" in assignments, None if "category" in assignments else "No category column was recognised."),
        "regions": Capability(any(role in assignments for role in ("region", "country", "city")), None if any(role in assignments for role in ("region", "country", "city")) else "No geography column was recognised."),
        "channels": Capability("channel" in assignments, None if "channel" in assignments else "No sales-channel column was recognised."),
        "discounts": Capability(discount_raw is not None and revenue_basis != "order_total", None if discount_raw is not None else "No discount column was recognised."),
        "returns": Capability(bool(is_return.any()) or "refund_amount" in numeric, None if (bool(is_return.any()) or "refund_amount" in numeric) else "No returns, refunds or negative quantities were found."),
        "profit": Capability(
            bool(cost_value.notna().any()) and revenue_basis in {"line_amount", "quantity_x_unit_price", "unit_price_one_unit_per_row"},
            None if cost_value.notna().any() else "No cost column was recognised, so profit is not calculated (it is never estimated).",
        ),
    }
    if currency_status == "multiple":
        capabilities["revenue"] = Capability(False, "Multiple currencies were found; revenue totals across currencies are not calculated.")
    if revenue_basis == "order_total":
        capabilities["profit"] = Capability(False, "Revenue comes from order totals, so line-level cost cannot be matched for profit.")

    for column in CANONICAL_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    boolean_columns = (
        "is_return", "is_blank", "is_ragged", "dup_reliable", "dup_possible", "key_conflict", "is_cancelled", "value_invalid",
        "order_total_conflict", "date_invalid", "quantity_invalid", "negative_unverified", "is_outlier", "text_normalized",
    )
    for column in boolean_columns:
        frame[column] = pd.Series(frame[column], index=index).fillna(False).astype(bool)
    frame = frame[list(CANONICAL_COLUMNS)]
    return CanonicalResult(
        frame=frame,
        grain=grain,
        grain_explanation=grain_explanation,
        revenue_basis=revenue_basis,
        revenue_label=revenue_label,
        value_is_net_of_discount=value_is_net,
        currency=currency,
        currency_status=currency_status,
        role_columns=role_columns,
        capabilities=capabilities,
        assumptions=assumptions,
        decisions=decisions,
        clarifications=clarifications,
        relational_checks=relational_checks,
        normalization_changes=normalization_changes,
    )
