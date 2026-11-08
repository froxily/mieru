import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from typing import Annotated, Any, TypeAlias
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mieru.analytics.customers import build_upload_customers
from mieru.analytics.dashboard import build_dashboard, build_trend
from mieru.analytics.performance import build_performance
from mieru.forecast.engine import build_forecast
from mieru.datasets.processor import ProcessingPool, dataset_context_from_schema, file_sha256, open_dataset_connection, process_dataset
from mieru.datasets.store import AUDIT_FILE, SCHEMA_FILE, DatasetStore
from mieru.ingest.errors import UploadRejectedError
from mieru.ingest.readers import validate_extension, validate_magic_bytes
from mieru.insights.upload import build_upload_insights
from mieru.reports.exports import EXPORT_KINDS, build_html_report, build_markdown_report, build_workbook, iter_csv, report_sections
from mieru.metrics.upload import POLICY_DEFAULTS, UPLOAD_METRICS_BY_ID, Filters, compute_metric, metric_availability
from mieru.quality.explorer import build_quality
from mieru.schema.aliases import ROLE_KINDS, ROLE_LABELS
from mieru.security.session import SlidingWindowLimiter, client_address, current_session_token, ensure_session_token, require_mutation_header

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
UPLOAD_CHUNK_BYTES: int = 1 << 20
MAPPABLE_ROLES: tuple[str, ...] = tuple(role for role in ROLE_KINDS)


class PolicyUpdate(BaseModel):
    policies: dict[str, bool]


class MappingUpdate(BaseModel):
    mapping: dict[str, str | None]


def get_store(request: Request) -> DatasetStore:
    return request.app.state.dataset_store


def get_pool(request: Request) -> ProcessingPool:
    return request.app.state.processing_pool


def get_upload_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.upload_limiter


StoreDependency: TypeAlias = Annotated[DatasetStore, Depends(get_store)]


def public_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": meta["dataset_id"],
        "display_name": meta["display_name"],
        "status": meta["status"],
        "stage": meta["stage"],
        "error": meta.get("error"),
        "created_at": meta["created_at"],
        "expires_at": meta["expires_at"],
        "size_bytes": meta.get("size_bytes"),
        "data_version": meta.get("data_version", 1),
    }


def owned_meta(request: Request, store: DatasetStore, dataset_id: str) -> dict[str, Any]:
    meta = store.get_owned(dataset_id, current_session_token(request))
    if meta is None:
        raise HTTPException(status_code=404, detail="Dataset not found. It may have expired or belong to another session.")
    return meta


def ready_schema(store: DatasetStore, meta: dict[str, Any]) -> dict[str, Any]:
    if meta["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Dataset is not ready (status: {meta['status']}).")
    schema = store.read_json(meta["dataset_id"], SCHEMA_FILE)
    if schema is None:
        raise HTTPException(status_code=409, detail="Dataset analysis is not available yet.")
    return schema


def parse_filters(start: str | None, end: str | None, category: list[str] | None, region: list[str] | None, channel: list[str] | None) -> Filters:
    def parse_date(value: str | None) -> dt.date | None:
        if not value:
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=f"Invalid date {value!r}; use YYYY-MM-DD.") from error

    start_date, end_date = parse_date(start), parse_date(end)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="The start date must be on or before the end date.")
    return Filters(
        start=start_date,
        end=end_date,
        categories=tuple(sorted(set(category or [])))[:50],
        regions=tuple(sorted(set(region or [])))[:50],
        channels=tuple(sorted(set(channel or [])))[:50],
    )


def policies_key(policies: dict[str, bool]) -> str:
    return hashlib.sha1(json.dumps({**POLICY_DEFAULTS, **policies}, sort_keys=True).encode()).hexdigest()[:12]


@router.post("", status_code=202, dependencies=[Depends(require_mutation_header)])
async def upload_dataset(request: Request, response: Response, store: StoreDependency, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    settings = request.app.state.settings
    pool: ProcessingPool = get_pool(request)
    limiter: SlidingWindowLimiter = get_upload_limiter(request)
    try:
        extension = validate_extension(file.filename or "")
    except UploadRejectedError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error
    session_token = ensure_session_token(request, response)
    if len(store.list_owned(session_token)) >= settings.max_datasets_per_session:
        raise HTTPException(status_code=429, detail=f"This session already has {settings.max_datasets_per_session} active datasets. Delete one or wait for it to expire.")
    if not limiter.allow(client_address(request)):
        raise HTTPException(status_code=429, detail="Too many uploads from this address. Please try again later.")
    if pool.pending >= pool.capacity:
        raise HTTPException(status_code=429, detail="MIERU is busy processing other uploads. Please retry in a minute.")
    dataset_id, _directory = store.create(session_token, file.filename or "upload", extension)
    source_path = store.source_path(dataset_id, extension)
    written = 0
    try:
        with source_path.open("wb") as handle:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise UploadRejectedError(413, f"The file exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit.")
                handle.write(chunk)
        if written == 0:
            raise UploadRejectedError(422, "The file is empty.")
        validate_magic_bytes(source_path, extension)
    except UploadRejectedError as error:
        store.safe_remove(dataset_id)
        raise HTTPException(status_code=error.status_code, detail=error.message) from error
    finally:
        await file.close()
    store.update_meta(dataset_id, size_bytes=written, sha256=file_sha256(source_path))
    if not pool.try_submit(lambda: process_dataset(store, dataset_id)):
        store.safe_remove(dataset_id)
        raise HTTPException(status_code=429, detail="MIERU is busy processing other uploads. Please retry in a minute.")
    meta = store.read_meta(dataset_id) or {}
    return public_meta(meta)


@router.get("")
def list_datasets(request: Request, store: StoreDependency) -> dict[str, Any]:
    return {"datasets": [public_meta(meta) for meta in store.list_owned(current_session_token(request))]}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    payload: dict[str, Any] = {"dataset": public_meta(meta), "stages": ["uploaded", "decoding", "profiling", "mapping", "cleaning", "analytics", "ready"]}
    if meta["status"] == "ready":
        schema = store.read_json(dataset_id, SCHEMA_FILE) or {}
        canonical = schema.get("canonical", {})
        payload["schema"] = {
            "source": schema.get("source"),
            "grain": canonical.get("grain"),
            "grain_explanation": canonical.get("grain_explanation"),
            "revenue_basis": canonical.get("revenue_basis"),
            "revenue_label": canonical.get("revenue_label"),
            "currency": canonical.get("currency"),
            "currency_status": canonical.get("currency_status"),
            "capabilities": canonical.get("capabilities"),
            "assumptions": canonical.get("assumptions"),
            "clarifications": canonical.get("clarifications"),
            "role_columns": canonical.get("role_columns"),
            "assignments": schema.get("inference", {}).get("assignments"),
            "unmapped_columns": schema.get("inference", {}).get("unmapped_columns"),
            "columns": [column["name"] for column in schema.get("columns", [])],
            "role_options": [{"role": role, "label": ROLE_LABELS.get(role, role)} for role in MAPPABLE_ROLES],
            "policies": {**POLICY_DEFAULTS, **(meta.get("policies") or {})},
        }
    return payload


@router.get("/{dataset_id}/dashboard")
def get_dashboard(
    dataset_id: str,
    request: Request,
    store: StoreDependency,
    start: str | None = None,
    end: str | None = None,
    category: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    channel: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    filters = parse_filters(start, end, category, region, channel)
    policies = meta.get("policies") or {}
    cache_key = (dataset_id, meta.get("data_version"), "dashboard", filters.cache_key(), policies_key(policies))
    cached = store.cache.get(cache_key)
    if cached is not None:
        return cached
    context = dataset_context_from_schema(schema, policies)
    with open_dataset_connection(store, dataset_id) as connection:
        payload = build_dashboard(connection, context, filters)
    canonical = schema["canonical"]
    payload["dataset"] = {
        **public_meta(meta),
        "grain": canonical["grain"],
        "grain_explanation": canonical["grain_explanation"],
        "revenue_basis": canonical["revenue_basis"],
        "revenue_label": canonical["revenue_label"],
        "currency": canonical["currency"],
        "currency_status": canonical["currency_status"],
        "rows": schema["source"]["rows"],
        "columns": schema["source"]["columns"],
        "format": schema["source"]["format"],
        "orders_label": context.orders_label,
    }
    payload["capabilities"] = canonical["capabilities"]
    payload["assumptions"] = canonical["assumptions"]
    payload["clarifications"] = canonical["clarifications"]
    payload["role_columns"] = canonical["role_columns"]
    store.cache.put(cache_key, payload)
    return payload


@router.get("/{dataset_id}/quality")
def get_quality(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    policies = meta.get("policies") or {}
    cache_key = (dataset_id, meta.get("data_version"), "quality", policies_key(policies))
    cached = store.cache.get(cache_key)
    if cached is not None:
        return cached
    context = dataset_context_from_schema(schema, policies)
    audit = store.read_json(dataset_id, AUDIT_FILE) or []
    with open_dataset_connection(store, dataset_id) as connection:
        payload = build_quality(connection, context, schema["source"], schema["columns"], schema["inference"]["assignments"], audit)
    payload["canonical"] = {
        key: schema["canonical"][key]
        for key in ("grain", "grain_explanation", "revenue_basis", "revenue_label", "currency", "currency_status", "assumptions", "clarifications", "relational_checks", "normalization_changes", "decisions")
    }
    store.cache.put(cache_key, payload)
    return payload


@router.get("/{dataset_id}/insights")
def get_insights(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    policies = meta.get("policies") or {}
    cache_key = (dataset_id, meta.get("data_version"), "insights", policies_key(policies))
    cached = store.cache.get(cache_key)
    if cached is not None:
        return cached
    context = dataset_context_from_schema(schema, policies)
    with open_dataset_connection(store, dataset_id) as connection:
        payload = build_upload_insights(connection, context)
    payload["currency"] = context.currency
    store.cache.put(cache_key, payload)
    return payload


@router.get("/{dataset_id}/customers")
def get_customers(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    policies = meta.get("policies") or {}
    cache_key = (dataset_id, meta.get("data_version"), "customers", policies_key(policies))
    cached = store.cache.get(cache_key)
    if cached is not None:
        return cached
    context = dataset_context_from_schema(schema, policies)
    with open_dataset_connection(store, dataset_id) as connection:
        payload = build_upload_customers(connection, context)
    store.cache.put(cache_key, payload)
    return payload


@router.get("/{dataset_id}/performance")
def get_performance(
    dataset_id: str,
    request: Request,
    store: StoreDependency,
    start: str | None = None,
    end: str | None = None,
    category: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    channel: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    filters = parse_filters(start, end, category, region, channel)
    policies = meta.get("policies") or {}
    cache_key = (dataset_id, meta.get("data_version"), "performance", filters.cache_key(), policies_key(policies))
    cached = store.cache.get(cache_key)
    if cached is not None:
        return cached
    context = dataset_context_from_schema(schema, policies)
    with open_dataset_connection(store, dataset_id) as connection:
        payload = build_performance(connection, context, filters)
    store.cache.put(cache_key, payload)
    return payload


@router.get("/{dataset_id}/forecast")
def get_forecast(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    policies = meta.get("policies") or {}
    cache_key = (dataset_id, meta.get("data_version"), "forecast", policies_key(policies))
    cached = store.cache.get(cache_key)
    if cached is not None:
        return cached
    context = dataset_context_from_schema(schema, policies)
    with open_dataset_connection(store, dataset_id) as connection:
        trend = build_trend(connection, context, Filters())
    if not trend.get("available"):
        payload: dict[str, Any] = {"available": False, "reason": trend.get("reason") or "Forecasting needs a readable date column."}
    else:
        value_key = "revenue" if trend.get("revenue_available") else "orders"
        payload = build_forecast(trend["points"], trend["granularity"], value_key)
        payload["measure"] = "Net revenue" if value_key == "revenue" else context.orders_label
    payload["currency"] = context.currency
    store.cache.put(cache_key, payload)
    return payload


@router.get("/{dataset_id}/metrics")
def list_dataset_metrics(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    context = dataset_context_from_schema(schema, meta.get("policies") or {})
    metrics = []
    for metric_id, metric in UPLOAD_METRICS_BY_ID.items():
        available, reason = metric_availability(metric, context)
        metrics.append({"metric_id": metric_id, "label": metric.label, "unit": metric.unit, "available": available, "unavailable_reason": reason})
    return {"metrics": metrics}


@router.get("/{dataset_id}/metrics/{metric_id}/explain")
def explain_dataset_metric(
    dataset_id: str,
    metric_id: str,
    request: Request,
    store: StoreDependency,
    start: str | None = None,
    end: str | None = None,
    category: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    channel: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    metric = UPLOAD_METRICS_BY_ID.get(metric_id)
    if metric is None:
        raise HTTPException(status_code=404, detail="Unknown metric.")
    filters = parse_filters(start, end, category, region, channel)
    policies = meta.get("policies") or {}
    context = dataset_context_from_schema(schema, policies)
    with open_dataset_connection(store, dataset_id) as connection:
        explanation = compute_metric(connection, metric, context, filters).to_dict()
    explanation["context"]["column_mapping"] = schema["canonical"]["role_columns"]
    explanation["context"]["assumptions"] = schema["canonical"]["assumptions"]
    return explanation


def export_filename(display_name: str, kind: str) -> str:
    stem = display_name.rsplit(".", 1)[0] if "." in display_name else display_name
    safe_stem = "".join(char if char.isalnum() or char in "-_" else "-" for char in stem).strip("-") or "dataset"
    suffix = {"cleaned.csv": "cleaned.csv", "annotated.csv": "annotated.csv", "workbook.xlsx": "mieru.xlsx", "report.html": "report.html", "report.md": "report.md"}[kind]
    return f"{safe_stem}-{suffix}"


def content_disposition(file_name: str) -> str:
    ascii_name = file_name.encode("ascii", "ignore").decode("ascii") or "mieru-export"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name)}"


@router.get("/{dataset_id}/export/{kind}")
def export_dataset(
    dataset_id: str,
    kind: str,
    request: Request,
    store: StoreDependency,
    start: str | None = None,
    end: str | None = None,
    category: Annotated[list[str] | None, Query()] = None,
    region: Annotated[list[str] | None, Query()] = None,
    channel: Annotated[list[str] | None, Query()] = None,
) -> Response:
    if kind not in EXPORT_KINDS:
        raise HTTPException(status_code=404, detail="Unknown export type.")
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    filters = parse_filters(start, end, category, region, channel)
    policies = meta.get("policies") or {}
    context = dataset_context_from_schema(schema, policies)
    source_columns = [column["name"] for column in schema["columns"]]
    media_type, family = EXPORT_KINDS[kind]
    headers = {"Content-Disposition": content_disposition(export_filename(meta["display_name"], kind)), "Cache-Control": "no-store"}
    if family in {"cleaned", "annotated"}:

        def stream() -> Iterator[bytes]:
            with open_dataset_connection(store, dataset_id) as connection:
                yield from iter_csv(connection, context, filters, source_columns, only_contributing=family == "cleaned")

        return StreamingResponse(stream(), media_type=media_type, headers=headers)
    with open_dataset_connection(store, dataset_id) as connection:
        dashboard = build_dashboard(connection, context, filters)
        dashboard["dataset"] = {
            "grain": schema["canonical"]["grain"],
            "grain_explanation": schema["canonical"]["grain_explanation"],
            "revenue_label": schema["canonical"]["revenue_label"],
            "currency": schema["canonical"]["currency"],
            "rows": schema["source"]["rows"],
        }
        dashboard["assumptions"] = schema["canonical"]["assumptions"]
        dashboard["clarifications"] = schema["canonical"]["clarifications"]
        audit = store.read_json(dataset_id, AUDIT_FILE) or []
        quality = build_quality(connection, context, schema["source"], schema["columns"], schema["inference"]["assignments"], audit, filters)
        insights = build_upload_insights(connection, context, filters)
        performance = build_performance(connection, context, filters)
        if family == "workbook":
            content = build_workbook(connection, context, filters, source_columns, dashboard, quality, insights, meta["display_name"], performance)
            return Response(content=content, media_type=media_type, headers=headers)
    sections = report_sections(dashboard, quality, insights, filters, meta["display_name"], performance)
    body = build_html_report(sections) if kind == "report.html" else build_markdown_report(sections)
    return Response(content=body.encode("utf-8"), media_type=media_type, headers=headers)


@router.put("/{dataset_id}/policies", dependencies=[Depends(require_mutation_header)])
def update_policies(dataset_id: str, update: PolicyUpdate, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    ready_schema(store, meta)
    unknown = [key for key in update.policies if key not in POLICY_DEFAULTS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown policies: {unknown}")
    def merge_policies(current: dict[str, Any]) -> None:
        current["policies"] = {**(current.get("policies") or {}), **update.policies}
        current["data_version"] = int(current.get("data_version", 1)) + 1

    updated = store.mutate_meta(dataset_id, merge_policies) or meta
    store.cache.invalidate_dataset(dataset_id)
    return {"dataset": public_meta(updated), "policies": {**POLICY_DEFAULTS, **(updated.get("policies") or {})}}


@router.put("/{dataset_id}/mapping", status_code=202, dependencies=[Depends(require_mutation_header)])
def update_mapping(dataset_id: str, update: MappingUpdate, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    schema = ready_schema(store, meta)
    column_names = [column["name"] for column in schema["columns"]]
    overrides = dict(meta.get("mapping_overrides") or {})
    for role, column_name in update.mapping.items():
        if role not in ROLE_KINDS:
            raise HTTPException(status_code=422, detail=f"Unknown role {role!r}.")
        if column_name is None:
            overrides[role] = None
            continue
        if column_name not in column_names:
            raise HTTPException(status_code=422, detail=f"Unknown column {column_name!r}.")
        overrides[role] = column_names.index(column_name)
    pool: ProcessingPool = get_pool(request)
    previous_overrides = dict(meta.get("mapping_overrides") or {})
    updated = store.update_meta(dataset_id, mapping_overrides=overrides, status="queued", stage="mapping")
    store.cache.invalidate_dataset(dataset_id)
    if not pool.try_submit(lambda: process_dataset(store, dataset_id)):
        store.update_meta(dataset_id, status="ready", stage="ready", mapping_overrides=previous_overrides)
        raise HTTPException(status_code=429, detail="MIERU is busy; please retry the mapping change in a minute.")
    return {"dataset": public_meta(updated or meta)}


@router.delete("/{dataset_id}", dependencies=[Depends(require_mutation_header)])
def delete_dataset(dataset_id: str, request: Request, store: StoreDependency) -> dict[str, Any]:
    meta = owned_meta(request, store, dataset_id)
    if meta["status"] in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="The dataset is still processing; try again when it has finished.")
    removed = store.safe_remove(dataset_id)
    return {"deleted": removed, "dataset_id": dataset_id}
