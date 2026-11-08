import datetime as dt
import hashlib
import logging
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import duckdb
import pandas as pd

from mieru.analytics.dashboard import build_dashboard, region_column
from mieru.canonical.build import CanonicalResult, build_canonical
from mieru.config import Settings
from mieru.datasets.store import AUDIT_FILE, SCHEMA_FILE, DatasetStore
from mieru.ingest.errors import UploadRejectedError
from mieru.ingest.readers import RawTable, read_upload
from mieru.metrics.upload import POLICY_DEFAULTS, DatasetContext, Filters
from mieru.schema.infer import InferenceResult, infer_roles
from mieru.schema.profile import ColumnProfile, profile_table

LOGGER = logging.getLogger("mieru.processing")
STAGES: tuple[str, ...] = ("uploaded", "decoding", "profiling", "mapping", "cleaning", "analytics", "ready")
VARCHAR_COLUMNS: tuple[str, ...] = (
    "order_id", "line_id", "customer_id", "product_id", "product_name", "product_key", "category", "status_raw", "status_norm",
    "channel", "region", "country", "city", "currency", "payment_method",
)
DOUBLE_COLUMNS: tuple[str, ...] = (
    "quantity", "unit_price", "line_amount", "order_total", "discount_value", "tax", "shipping", "cost_value", "refund_amount",
    "line_value", "signed_value", "net_value",
)
BOOLEAN_COLUMNS: tuple[str, ...] = (
    "is_return", "is_blank", "is_ragged", "dup_reliable", "dup_possible", "key_conflict", "is_cancelled", "value_invalid",
    "order_total_conflict", "date_invalid", "quantity_invalid", "negative_unverified", "is_outlier", "text_normalized",
)


class ProcessingPool:
    def __init__(self, workers: int, queue_limit: int) -> None:
        self.capacity = workers + queue_limit
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mieru-processing")
        self._pending = 0
        self._lock = threading.Lock()

    def try_submit(self, task: Callable[[], None]) -> bool:
        with self._lock:
            if self._pending >= self.capacity:
                return False
            self._pending += 1

        def run() -> None:
            try:
                task()
            finally:
                with self._lock:
                    self._pending -= 1

        self._executor.submit(run)
        return True

    @property
    def pending(self) -> int:
        with self._lock:
            return self._pending

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def configure_connection(connection: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    connection.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
    connection.execute(f"SET threads = {int(settings.duckdb_threads)}")
    connection.execute(f"SET temp_directory = '{(settings.temp_dir / 'duckdb').as_posix()}'")


def open_dataset_connection(store: DatasetStore, dataset_id: str, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(store.database_path(dataset_id)), read_only=read_only)
    configure_connection(connection, store.settings)
    return connection


def file_sha256(path: Any) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_entry(step: str, title: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"step": step, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "title": title, "detail": detail, **extra}


def write_tables(connection: duckdb.DuckDBPyConnection, raw: pd.DataFrame, canonical: CanonicalResult) -> None:
    source_frame = raw.copy()
    source_frame.insert(0, "_row_id", range(1, len(source_frame) + 1))
    connection.register("source_frame", source_frame)
    casts = ", ".join(['CAST("_row_id" AS BIGINT) AS _row_id'] + [f'CAST("{column}" AS VARCHAR) AS "{column}"' for column in raw.columns])
    connection.execute(f"CREATE OR REPLACE TABLE src_rows AS SELECT {casts} FROM source_frame")
    connection.unregister("source_frame")
    canonical_frame = canonical.frame.copy()
    canonical_frame["order_ts"] = pd.to_datetime(canonical_frame["order_ts"], errors="coerce").astype("datetime64[ns]")
    for column in VARCHAR_COLUMNS:
        canonical_frame[column] = canonical_frame[column].astype("object").where(canonical_frame[column].notna(), None)
    connection.register("canonical_frame", canonical_frame)
    select_parts = ['CAST("_row_id" AS BIGINT) AS _row_id', 'CAST("order_ts" AS TIMESTAMP) AS order_ts']
    select_parts += [f'CAST("{column}" AS VARCHAR) AS {column}' for column in VARCHAR_COLUMNS]
    select_parts += [f'CAST("{column}" AS DOUBLE) AS {column}' for column in DOUBLE_COLUMNS]
    select_parts += [f'CAST("{column}" AS BOOLEAN) AS {column}' for column in BOOLEAN_COLUMNS]
    connection.execute(f"CREATE OR REPLACE TABLE canon_lines AS SELECT {', '.join(select_parts)} FROM canonical_frame ORDER BY _row_id")
    connection.unregister("canonical_frame")


def source_summary(raw_table: RawTable, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "display_name": meta.get("display_name"),
        "format": raw_table.source_format,
        "size_bytes": meta.get("size_bytes"),
        "sha256": meta.get("sha256"),
        "encoding": raw_table.encoding,
        "delimiter": {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}.get(raw_table.delimiter or "", raw_table.delimiter),
        "sheet_name": raw_table.sheet_name,
        "sheet_names": raw_table.sheet_names,
        "header_row_number": raw_table.header_row_number,
        "skipped_leading_rows": raw_table.skipped_leading_rows,
        "synthesized_header": raw_table.synthesized_header,
        "rows": len(raw_table.rows),
        "columns": len(raw_table.columns),
        "ragged_rows": len(raw_table.ragged_row_ids),
        "notes": raw_table.notes,
    }


def dataset_context_from_schema(schema: dict[str, Any], policies: dict[str, bool]) -> DatasetContext:
    canonical = schema["canonical"]
    return DatasetContext(
        grain=canonical["grain"],
        revenue_basis=canonical["revenue_basis"],
        currency=canonical["currency"],
        capabilities=canonical["capabilities"],
        role_columns=canonical["role_columns"],
        policies={**POLICY_DEFAULTS, **policies},
        region_column=region_column(canonical["role_columns"]),
    )


def process_dataset(store: DatasetStore, dataset_id: str) -> None:
    meta = store.read_meta(dataset_id)
    if meta is None:
        return
    extension = meta["extension"]
    audit: list[dict[str, Any]] = []

    def stage(name: str) -> None:
        store.update_meta(dataset_id, status="processing", stage=name)

    try:
        source_path = store.source_path(dataset_id, extension)
        stage("decoding")
        raw_table = read_upload(source_path, extension, store.settings.max_upload_rows, store.settings.max_upload_columns)
        audit.append(
            audit_entry(
                "received",
                "File received and kept unchanged",
                f"{meta.get('display_name')} · {int(meta.get('size_bytes') or 0):,} bytes · SHA-256 {str(meta.get('sha256'))[:16]}…",
            )
        )
        decode_detail = (
            f"{raw_table.source_format.upper()} · encoding {raw_table.encoding or 'n/a'} · delimiter {raw_table.delimiter!r}"
            if raw_table.source_format == "csv"
            else f"Worksheet '{raw_table.sheet_name}' of {len(raw_table.sheet_names)}"
        )
        audit.append(audit_entry("decoded", "Decoded and parsed", decode_detail, rows=len(raw_table.rows), columns=len(raw_table.columns)))
        if raw_table.skipped_leading_rows:
            audit.append(audit_entry("header", "Header detected", f"Skipped {raw_table.skipped_leading_rows} title row(s); header on row {raw_table.header_row_number}."))
        if raw_table.synthesized_header:
            audit.append(audit_entry("header", "No header row found", "Generic column names were generated."))
        column_keys = [f"c{index:03d}" for index in range(len(raw_table.columns))]
        raw = pd.DataFrame(raw_table.rows, columns=column_keys, dtype="object")
        stage("profiling")
        profiles: list[ColumnProfile] = profile_table(raw, raw_table.columns)
        stage("mapping")
        overrides = {role: (int(index) if index is not None else None) for role, index in (meta.get("mapping_overrides") or {}).items()}
        inference: InferenceResult = infer_roles(profiles, overrides)
        inference_payload = inference.to_dict(profiles)
        mapped = ", ".join(f"{entry['label']} ← '{entry['column_name']}'" for entry in inference_payload["assignments"].values())
        audit.append(audit_entry("mapping", "Column roles detected", mapped or "No columns could be mapped.", overridden=inference.overridden_roles))
        stage("cleaning")
        canonical = build_canonical(raw, profiles, inference, raw_table.ragged_row_ids)
        for decision in canonical.decisions:
            audit.append(audit_entry(f"decision:{decision['step']}", decision["step"].replace("_", " ").capitalize(), decision["detail"]))
        database_path = store.database_path(dataset_id)
        with duckdb.connect(str(database_path)) as connection:
            configure_connection(connection, store.settings)
            write_tables(connection, raw, canonical)
            connection.execute("CHECKPOINT")
        stage("analytics")
        schema = {
            "source": source_summary(raw_table, meta),
            "columns": [profile.to_dict() for profile in profiles],
            "inference": inference_payload,
            "canonical": canonical.summary(),
        }
        context = dataset_context_from_schema(schema, meta.get("policies") or {})
        with open_dataset_connection(store, dataset_id) as connection:
            build_dashboard(connection, context, Filters())
        audit.append(audit_entry("ready", "Analytics generated", "Dashboards, quality report and metric explanations are ready."))
        store.write_json(dataset_id, SCHEMA_FILE, schema)
        store.write_json(dataset_id, AUDIT_FILE, audit)
        current = store.read_meta(dataset_id) or meta
        store.update_meta(dataset_id, status="ready", stage="ready", error=None, data_version=int(current.get("data_version", 1)) + 1)
        store.cache.invalidate_dataset(dataset_id)
    except UploadRejectedError as error:
        store.update_meta(dataset_id, status="failed", stage="failed", error=error.message)
    except Exception:
        LOGGER.error("Processing failed for dataset %s\n%s", dataset_id, traceback.format_exc())
        store.update_meta(
            dataset_id,
            status="failed",
            stage="failed",
            error="MIERU could not process this file. It may be malformed or use a layout that is not supported yet.",
        )
