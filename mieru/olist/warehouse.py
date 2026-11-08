import json
import threading
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

REQUIRED_TABLES: tuple[str, ...] = (
    "mart_order_fulfillment",
    "mart_cohort_retention",
    "mart_seller_pareto",
    "mart_olist_monthly",
    "mart_olist_category",
    "mart_olist_state",
    "mart_olist_payments",
)


class OlistDataUnavailableError(RuntimeError):
    pass


class OlistWarehouse:
    def __init__(self, database_path: Path, outputs_dir: Path, baseline_dir: Path) -> None:
        self.database_path = database_path
        self.outputs_dir = outputs_dir
        self.baseline_dir = baseline_dir
        self._lock = threading.Lock()
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._opened_mtime: float | None = None
        self._payload_cache: dict[tuple[str, float], Any] = {}

    def database_mtime(self) -> float:
        if not self.database_path.exists():
            raise OlistDataUnavailableError(
                f"Olist warehouse not found at {self.database_path}. Run `python run.py` to build it."
            )
        return self.database_path.stat().st_mtime

    def _connection_for_current_file(self) -> duckdb.DuckDBPyConnection:
        current_mtime = self.database_mtime()
        with self._lock:
            if self._connection is None or self._opened_mtime != current_mtime:
                if self._connection is not None:
                    self._connection.close()
                self._payload_cache.clear()
                connection = duckdb.connect(str(self.database_path), read_only=True)
                existing_tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
                missing_tables = [table for table in REQUIRED_TABLES if table not in existing_tables]
                if missing_tables:
                    connection.close()
                    raise OlistDataUnavailableError(
                        f"Olist warehouse is missing {missing_tables}. Run `python run.py` to rebuild the marts."
                    )
                self._connection = connection
                self._opened_mtime = current_mtime
            return self._connection

    def query_frame(self, sql: str, parameters: list[Any] | None = None) -> pd.DataFrame:
        cursor = self._connection_for_current_file().cursor()
        try:
            return cursor.execute(sql, parameters or []).df()
        finally:
            cursor.close()

    def query_records(self, sql: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        cursor = self._connection_for_current_file().cursor()
        try:
            result = cursor.execute(sql, parameters or [])
            column_names = [column[0] for column in result.description]
            return [dict(zip(column_names, row)) for row in result.fetchall()]
        finally:
            cursor.close()

    def query_one(self, sql: str, parameters: list[Any] | None = None) -> dict[str, Any]:
        records = self.query_records(sql, parameters)
        return records[0] if records else {}

    def cached_payload(self, key: str, builder: Any) -> Any:
        cache_key = (key, self.database_mtime())
        if cache_key not in self._payload_cache:
            self._connection_for_current_file()
            self._payload_cache[cache_key] = builder()
        return self._payload_cache[cache_key]

    def research_metrics_path(self) -> Path:
        current_path = self.outputs_dir / "metrics_summary.json"
        return current_path if current_path.exists() else self.baseline_dir / "metrics_summary.json"

    def research_metrics(self) -> dict[str, Any]:
        metrics_path = self.research_metrics_path()
        if not metrics_path.exists():
            raise OlistDataUnavailableError("metrics_summary.json not found. Run `python run.py` to generate it.")
        return json.loads(metrics_path.read_text(encoding="utf-8"))

    def figure_path(self, file_name: str) -> Path | None:
        for directory in (self.outputs_dir, self.baseline_dir):
            candidate = directory / file_name
            if candidate.is_file():
                return candidate
        return None

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
