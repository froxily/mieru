from dataclasses import asdict, dataclass, field
from typing import Any

VALID_KINDS: frozenset[str] = frozenset({"opportunity", "risk", "info", "quality"})
VALID_CONFIDENCE: frozenset[str] = frozenset({"high", "medium"})


@dataclass(frozen=True)
class Evidence:
    label: str
    value: float | None
    unit: str
    currency: str | None = None
    metric_id: str | None = None


@dataclass(frozen=True)
class InsightCard:
    insight_id: str
    kind: str
    confidence: str
    finding: str
    evidence: tuple[Evidence, ...]
    interpretation: str
    action: str
    limitations: tuple[str, ...]
    gates: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Unsupported insight kind {self.kind!r}")
        if self.confidence not in VALID_CONFIDENCE:
            raise ValueError(f"Unsupported confidence {self.confidence!r}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [asdict(item) for item in self.evidence]
        payload["limitations"] = list(self.limitations)
        payload["gates"] = list(self.gates)
        return payload


def skipped(rule: str, reason: str) -> dict[str, str]:
    return {"rule": rule, "reason": reason}
