from dataclasses import asdict, dataclass, field
from typing import Any

VALID_UNITS: frozenset[str] = frozenset({"currency", "count", "ratio", "score", "days", "index", "share"})


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    label: str
    description: str
    formula: str
    unit: str
    grain: str
    source: str
    source_columns: tuple[str, ...]
    transformations: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.unit not in VALID_UNITS:
            raise ValueError(f"Metric {self.metric_id} has unsupported unit {self.unit!r}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, tuple):
                payload[key] = list(value)
        return payload


@dataclass
class ExcludedRecords:
    reason: str
    label: str
    records: int

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "label": self.label, "records": self.records}


@dataclass
class RecordCounts:
    grain: str
    input_records: int
    contributing_records: int
    excluded: list[ExcludedRecords] = field(default_factory=list)
    overlapping_flags: list[ExcludedRecords] = field(default_factory=list)

    @property
    def excluded_total(self) -> int:
        return sum(item.records for item in self.excluded)

    @property
    def is_consistent(self) -> bool:
        return self.input_records == self.contributing_records + self.excluded_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "grain": self.grain,
            "input_records": self.input_records,
            "contributing_records": self.contributing_records,
            "excluded_total": self.excluded_total,
            "excluded": [item.to_dict() for item in self.excluded],
            "overlapping_flags": [item.to_dict() for item in self.overlapping_flags],
            "is_consistent": self.is_consistent,
        }


@dataclass
class MetricExplanation:
    definition: MetricDefinition
    status: str
    value: float | None
    sql: str
    record_counts: RecordCounts | None
    lineage: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None
    currency: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "definition": self.definition.to_dict(),
            "status": self.status,
            "value": self.value,
            "currency": self.currency,
            "sql": self.sql,
            "record_counts": self.record_counts.to_dict() if self.record_counts else None,
            "lineage": self.lineage,
            "unavailable_reason": self.unavailable_reason,
            "context": self.context,
        }


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if converted == converted and converted not in (float("inf"), float("-inf")) else None
