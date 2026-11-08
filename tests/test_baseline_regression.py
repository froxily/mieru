import json
import math
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
BASELINE_METRICS_PATH: Path = PROJECT_ROOT / "baselines" / "2026-10-15" / "metrics_summary.json"
CURRENT_METRICS_PATH: Path = PROJECT_ROOT / "outputs" / "metrics_summary.json"
VOLATILE_PATHS: frozenset[str] = frozenset(
    {
        "metadata.generated_at_utc",
        "data_integrity.downloads",
    }
)
RELATIVE_TOLERANCE: float = 1e-9


def collect_differences(baseline: Any, current: Any, path: str, differences: list[str]) -> None:
    if path in VOLATILE_PATHS:
        return
    if isinstance(baseline, dict):
        if not isinstance(current, dict):
            differences.append(f"{path}: expected object, found {type(current).__name__}")
            return
        for key, baseline_value in baseline.items():
            child_path = f"{path}.{key}" if path else key
            if key not in current:
                differences.append(f"{child_path}: missing from current metrics")
                continue
            collect_differences(baseline_value, current[key], child_path, differences)
        return
    if isinstance(baseline, list):
        if not isinstance(current, list) or len(current) != len(baseline):
            differences.append(f"{path}: list length changed")
            return
        for index, (baseline_item, current_item) in enumerate(zip(baseline, current)):
            collect_differences(baseline_item, current_item, f"{path}[{index}]", differences)
        return
    if isinstance(baseline, float) and isinstance(current, (int, float)) and not isinstance(current, bool):
        if not math.isclose(baseline, float(current), rel_tol=RELATIVE_TOLERANCE, abs_tol=1e-12):
            differences.append(f"{path}: {baseline!r} -> {current!r}")
        return
    if baseline != current:
        differences.append(f"{path}: {baseline!r} -> {current!r}")


@pytest.mark.skipif(not CURRENT_METRICS_PATH.exists(), reason="run `python run.py` to generate outputs/metrics_summary.json")
def test_regenerated_research_metrics_match_verified_baseline() -> None:
    baseline = json.loads(BASELINE_METRICS_PATH.read_text(encoding="utf-8"))
    current = json.loads(CURRENT_METRICS_PATH.read_text(encoding="utf-8"))
    differences: list[str] = []
    collect_differences(baseline, current, "", differences)
    assert not differences, "Research outputs drifted from the 2026-10-15 baseline:\n" + "\n".join(differences[:50])


def test_baseline_snapshot_is_complete() -> None:
    manifest = json.loads((BASELINE_METRICS_PATH.parent / "MANIFEST.json").read_text(encoding="utf-8"))
    for file_name in manifest["files"]:
        assert (BASELINE_METRICS_PATH.parent / file_name).exists()
    assert manifest["headline"].startswith("Missing the promised delivery SLA date multiplies the odds")
