import re
from dataclasses import asdict, dataclass, field
from typing import Any

from mieru.schema.aliases import FINANCIAL_ROLES, ROLE_ALIASES, ROLE_KINDS, ROLE_LABELS, STATUS_TOKENS
from mieru.schema.profile import ColumnProfile, normalize_column_name

ASSIGNMENT_THRESHOLD: float = 0.6
AMBIGUITY_MARGIN: float = 0.05
FINANCIAL_NAME_EVIDENCE: float = 0.7
VALUE_ONLY_DATE_CONFIDENCE: float = 0.61
CLEAN_NUMERIC_RATE: float = 0.9
PARTIAL_NUMERIC_RATE: float = 0.5
CJK_PATTERN = re.compile(r"[぀-ヿ㐀-鿿]")
NEGATIVE_TOKENS: dict[str, frozenset[str]] = {
    "order_id": frozenset({"date", "time", "status", "total", "amount", "value", "item", "line", "count", "qty"}),
    "line_id": frozenset({"date", "status", "amount"}),
    "customer_id": frozenset({"name", "city", "state", "zip", "country", "segment", "type", "since"}),
    "product_id": frozenset({"name", "description", "category", "price", "type"}),
    "product_name": frozenset({"id", "code", "sku", "category", "type", "line", "price", "count", "qty", "quantity", "weight", "length", "width", "height", "photos"}),
    "order_date": frozenset({"ship", "shipped", "shipping", "delivery", "delivered", "due", "estimated", "birth", "approved", "carrier", "review", "answer", "limit"}),
    "quantity": frozenset({"price", "amount", "value", "cost"}),
    "unit_price": frozenset({"total", "cost", "freight", "shipping", "tax"}),
    "amount": frozenset({"cost", "tax", "discount", "shipping", "freight", "profit", "margin", "refund", "rate", "percent", "pct", "count", "qty", "quantity", "unit"}),
    "order_total": frozenset({"cost", "tax", "discount"}),
    "discount": frozenset({"rate", "code", "name"}),
    "region": frozenset({"status", "order", "payment"}),
    "category": frozenset({"id", "code"}),
    "status": frozenset({"payment"}),
    "channel": frozenset({"id"}),
    "city": frozenset({"id"}),
    "country": frozenset({"id"}),
}


@dataclass
class RoleCandidate:
    role: str
    column_index: int
    column_name: str
    confidence: float
    name_score: float
    value_score: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class InferenceResult:
    assignments: dict[str, int]
    candidates: dict[str, list[RoleCandidate]]
    clarifications: list[dict[str, Any]]
    overridden_roles: list[str]

    def to_dict(self, profiles: list[ColumnProfile]) -> dict[str, Any]:
        return {
            "assignments": {
                role: {"column_index": index, "column_name": profiles[index].name, "label": ROLE_LABELS.get(role, role)}
                for role, index in self.assignments.items()
            },
            "candidates": {role: [asdict(candidate) for candidate in items[:3]] for role, items in self.candidates.items()},
            "clarifications": self.clarifications,
            "overridden_roles": self.overridden_roles,
            "unmapped_columns": [profile.name for profile in profiles if profile.index not in self.assignments.values()],
        }


def is_cjk(text: str) -> bool:
    return bool(CJK_PATTERN.search(text))


def contains_token_sequence(tokens: list[str], sequence: list[str]) -> bool:
    width = len(sequence)
    return any(tokens[start : start + width] == sequence for start in range(len(tokens) - width + 1))


def name_score(role: str, normalized_name: str) -> float:
    tokens = [token for token in normalized_name.split("_") if token]
    negatives = NEGATIVE_TOKENS.get(role, frozenset())
    best = 0.0
    for alias in ROLE_ALIASES.get(role, ()):
        alias_normalized = normalize_column_name(alias)
        if not alias_normalized:
            continue
        if normalized_name == alias_normalized:
            return 1.0
        if is_cjk(alias_normalized):
            if alias_normalized in normalized_name:
                best = max(best, 0.85)
            continue
        alias_tokens = alias_normalized.split("_")
        if len(alias_tokens) >= 2 and contains_token_sequence(tokens, alias_tokens):
            best = max(best, 0.8)
        elif len(alias_tokens) == 1 and alias_normalized in tokens:
            best = max(best, 0.7)
    if best > 0 and negatives.intersection(tokens):
        return 0.0
    return best


def has_negative_token(role: str, normalized_name: str) -> bool:
    return bool(NEGATIVE_TOKENS.get(role, frozenset()).intersection(token for token in normalized_name.split("_") if token))


def status_token_share(profile: ColumnProfile) -> float:
    all_tokens = [token for tokens in STATUS_TOKENS.values() for token in tokens]
    matched = sum(count for value, count in profile.top_values if any(token in value.lower() for token in all_tokens))
    total = sum(count for _value, count in profile.top_values)
    return matched / total if total else 0.0


def value_score(role: str, profile: ColumnProfile) -> float:
    kind = ROLE_KINDS[role]
    if profile.non_null == 0:
        return 0.0
    if kind == "date":
        return profile.date_rate if profile.date_rate >= 0.8 else 0.0
    if kind == "quantity":
        if profile.numeric_rate < PARTIAL_NUMERIC_RATE:
            return 0.0
        score = 0.6 + 0.4 * profile.integer_share
        if profile.numeric_median is not None and abs(profile.numeric_median) > 10_000:
            score *= 0.3
        return score if profile.numeric_rate >= CLEAN_NUMERIC_RATE else score * 0.75
    if kind == "money":
        if profile.numeric_rate < PARTIAL_NUMERIC_RATE:
            return 0.0
        if profile.date_rate >= 0.9 and not profile.date_excel_serial:
            return 0.0
        return 0.9 if profile.numeric_rate >= CLEAN_NUMERIC_RATE else 0.6
    if kind == "identifier":
        if profile.numeric_rate >= 0.9 and profile.integer_share < 0.9:
            return 0.0
        if profile.date_rate >= 0.9 and not profile.date_excel_serial:
            return 0.0
        return 0.9 if profile.distinct_ratio > 0.01 else 0.4
    if kind == "category":
        score = 0.9 if (profile.distinct <= 500 or profile.distinct_ratio < 0.3) else 0.4
        if profile.numeric_rate >= 0.9:
            score = 0.3
        if role == "status" and status_token_share(profile) >= 0.5:
            score = 1.0
        return score
    if kind == "text":
        return 0.9 if profile.numeric_rate < 0.5 and profile.mean_text_length >= 3 else 0.3
    if kind == "boolean":
        return 0.9 if profile.boolean_like else 0.0
    return 0.0


def score_candidates(profiles: list[ColumnProfile]) -> dict[str, list[RoleCandidate]]:
    candidates: dict[str, list[RoleCandidate]] = {role: [] for role in ROLE_KINDS}
    for profile in profiles:
        for role in ROLE_KINDS:
            name_component = name_score(role, profile.normalized_name)
            value_component = value_score(role, profile)
            if value_component == 0.0:
                continue
            evidence: list[str] = []
            if name_component > 0:
                confidence = 0.65 * name_component + 0.35 * value_component
                evidence.append(f"Column name matches {ROLE_LABELS.get(role, role).lower()} aliases ({name_component:.2f}).")
            elif role == "order_date" and profile.date_rate >= 0.95 and not profile.date_excel_serial and not has_negative_token(role, profile.normalized_name):
                confidence = VALUE_ONLY_DATE_CONFIDENCE
                evidence.append("Values parse as dates although the name is not a known alias.")
            elif role == "status" and status_token_share(profile) >= 0.6:
                confidence = 0.62
                evidence.append("Values look like order statuses (e.g. cancelled / delivered).")
            else:
                continue
            if role in FINANCIAL_ROLES and name_component < FINANCIAL_NAME_EVIDENCE:
                continue
            evidence.append(f"Value check {value_component:.2f} (numeric {profile.numeric_rate:.0%}, date {profile.date_rate:.0%}).")
            candidates[role].append(
                RoleCandidate(
                    role=role,
                    column_index=profile.index,
                    column_name=profile.name,
                    confidence=round(confidence, 4),
                    name_score=name_component,
                    value_score=value_component,
                    evidence=evidence,
                )
            )
    for items in candidates.values():
        items.sort(key=lambda candidate: (-candidate.confidence, candidate.column_index))
    return candidates


def infer_roles(profiles: list[ColumnProfile], overrides: dict[str, int | None] | None = None) -> InferenceResult:
    candidates = score_candidates(profiles)
    assignments: dict[str, int] = {}
    clarifications: list[dict[str, Any]] = []
    overridden_roles: list[str] = []
    used_columns: set[int] = set()
    blocked_roles: set[str] = set()
    for role, column_index in (overrides or {}).items():
        if role not in ROLE_KINDS:
            continue
        overridden_roles.append(role)
        blocked_roles.add(role)
        if column_index is not None and 0 <= column_index < len(profiles) and column_index not in used_columns:
            assignments[role] = column_index
            used_columns.add(column_index)
    for role, items in candidates.items():
        if role in blocked_roles:
            continue
        eligible = [candidate for candidate in items if candidate.confidence >= ASSIGNMENT_THRESHOLD]
        if len(eligible) >= 2 and eligible[0].confidence - eligible[1].confidence < AMBIGUITY_MARGIN:
            blocked_roles.add(role)
            clarifications.append(
                {
                    "kind": "ambiguous_role",
                    "role": role,
                    "label": ROLE_LABELS.get(role, role),
                    "columns": [candidate.column_name for candidate in eligible[:3]],
                    "message": f"Several columns could be the {ROLE_LABELS.get(role, role).lower()}: "
                    + ", ".join(f"'{candidate.column_name}'" for candidate in eligible[:3])
                    + ". MIERU did not guess; choose one in Advanced mapping.",
                }
            )
    ranked = sorted(
        (candidate for role, items in candidates.items() if role not in blocked_roles for candidate in items if candidate.confidence >= ASSIGNMENT_THRESHOLD),
        key=lambda candidate: (-candidate.confidence, candidate.column_index),
    )
    for candidate in ranked:
        if candidate.role in assignments or candidate.column_index in used_columns:
            continue
        assignments[candidate.role] = candidate.column_index
        used_columns.add(candidate.column_index)
    date_profiles = [profiles[index] for role, index in assignments.items() if role == "order_date"]
    if "order_date" not in assignments and "order_date" not in blocked_roles:
        date_profiles = [
            profile
            for profile in profiles
            if profile.date_ambiguous_day_month and name_score("order_date", profile.normalized_name) > 0 and profile.index not in used_columns
        ][:1]
    for profile in date_profiles:
        if profile.date_ambiguous_day_month:
            clarifications.append(
                {
                    "kind": "ambiguous_date_format",
                    "role": "order_date",
                    "label": ROLE_LABELS["order_date"],
                    "columns": [profile.name],
                    "message": f"Dates in '{profile.name}' could be day/month or month/day (no day above 12 was found), so those dates were not interpreted.",
                }
            )
    for role in ("quantity", "unit_price", "amount", "order_total", "discount", "unit_cost", "line_cost", "refund_amount", "tax", "shipping"):
        if role in assignments and profiles[assignments[role]].numeric_rate < CLEAN_NUMERIC_RATE:
            profile = profiles[assignments[role]]
            clarifications.append(
                {
                    "kind": "unreadable_values",
                    "role": role,
                    "label": ROLE_LABELS.get(role, role),
                    "columns": [profile.name],
                    "message": f"{1 - profile.numeric_rate:.0%} of values in '{profile.name}' are not readable numbers; those rows are excluded from "
                    "the affected metrics and listed in the Data Quality report.",
                }
            )
        if role in assignments and profiles[assignments[role]].numeric_ambiguous_convention:
            clarifications.append(
                {
                    "kind": "ambiguous_number_format",
                    "role": role,
                    "label": ROLE_LABELS.get(role, role),
                    "columns": [profiles[assignments[role]].name],
                    "message": f"Numbers in '{profiles[assignments[role]].name}' use separators that could mean thousands or decimals; read as dot-decimal.",
                }
            )
    return InferenceResult(assignments=assignments, candidates=candidates, clarifications=clarifications, overridden_roles=overridden_roles)
