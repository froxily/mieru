import sys
import time
from collections.abc import Callable
from typing import Any

from src.analysis import METRICS_PATH, run_analysis
from src.data import RawDataDownloadError, RawSchemaError, download_raw_files, verify_raw_schemas
from src.plotting import render_all_figures
from src.warehouse import DATABASE_PATH, WarehouseIntegrityError, build_warehouse


def run_stage(label: str, stage: Callable[[], Any]) -> Any:
    started_at = time.perf_counter()
    print(f"[run] {label} ...", flush=True)
    stage_result = stage()
    print(f"[run] {label} done in {time.perf_counter() - started_at:.1f}s", flush=True)
    return stage_result


def run_pipeline() -> dict[str, Any]:
    download_report = run_stage("1/5 download raw CSVs (cached files are reused)", download_raw_files)
    schema_report = run_stage("2/5 verify required raw columns", verify_raw_schemas)
    warehouse_report = run_stage("3/5 build DuckDB warehouse and execute sql/ marts", build_warehouse)
    pipeline_reports = {
        "downloads": download_report,
        "extra_source_columns_ignored": {
            file_name: report["extra_columns"] for file_name, report in schema_report.items() if report["extra_columns"]
        },
        **warehouse_report,
    }
    metrics = run_stage("4/5 run statistical tests and logistic regressions", lambda: run_analysis(pipeline_reports))
    figure_paths = run_stage("5/5 render publication figures", lambda: render_all_figures(metrics))
    print(f"[run] warehouse : {DATABASE_PATH}")
    print(f"[run] metrics   : {METRICS_PATH}")
    for figure_path in figure_paths:
        print(f"[run] figure    : {figure_path} ({figure_path.stat().st_size / 1024:,.0f} KB)")
    print(f"[run] HEADLINE  : {metrics['headline']['sentence']}")
    return metrics


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        run_pipeline()
    except (RawDataDownloadError, RawSchemaError, WarehouseIntegrityError) as error:
        print(f"[run] STOPPED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
