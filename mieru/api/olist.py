from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from mieru.api.dependencies import cached_olist_payload, get_olist_warehouse
from mieru.analytics.customers import customer_intelligence
from mieru.forecast.engine import build_forecast
from mieru.olist.insights import build_olist_insights
from mieru.olist.markets import build_markets
from mieru.olist.service import RESEARCH_FIGURES, build_customers, build_delivery, build_overview, build_research, build_sellers
from mieru.olist.warehouse import OlistWarehouse

router = APIRouter(prefix="/api/olist", tags=["olist"])
OLIST_FORECAST_START: str = "2017-01-01"
WarehouseDependency: TypeAlias = Annotated[OlistWarehouse, Depends(get_olist_warehouse)]


@router.get("/overview")
def get_overview(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "overview", build_overview)


@router.get("/delivery")
def get_delivery(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "delivery", build_delivery)


@router.get("/customers")
def get_customers(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "customers", build_customers)


@router.get("/sellers")
def get_sellers(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "sellers", build_sellers)


@router.get("/markets")
def get_markets(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "markets", build_markets)


@router.get("/research")
def get_research(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "research", build_research)


@router.get("/insights")
def get_insights(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "insights", build_olist_insights)


def build_olist_forecast(warehouse: OlistWarehouse) -> dict[str, Any]:
    rows = warehouse.query_records(
        "SELECT strftime(purchase_month, '%Y-%m-%d') AS period, gmv AS revenue, is_partial FROM mart_olist_monthly ORDER BY purchase_month"
    )
    points = [row for row in rows if row["period"] >= OLIST_FORECAST_START]
    payload = build_forecast(points, "month", "revenue")
    payload["measure"] = "GMV"
    payload["currency"] = "BRL"
    payload.setdefault("notes", []).insert(0, "Months before 2017-01 (sparse launch period) are excluded.")
    return payload


def build_olist_customer_intelligence(warehouse: OlistWarehouse) -> dict[str, Any]:
    orders = warehouse.query_frame(
        "SELECT customer_unique_id AS customer_id, order_id AS order_key, order_purchase_timestamp AS order_date, order_gmv AS revenue "
        "FROM mart_order_fulfillment WHERE order_gmv IS NOT NULL"
    )
    payload = customer_intelligence(orders, "BRL", "delivered orders")
    if payload.get("available"):
        platform_gmv = warehouse.query_records("SELECT SUM(order_gmv) AS gmv FROM mart_order_fulfillment")[0]["gmv"]
        payload["reconciliation"] = {
            "segment_revenue_total": payload["revenue_total"],
            "dashboard_label": "Platform GMV (Overview)",
            "dashboard_total": platform_gmv,
            "difference": platform_gmv - payload["revenue_total"],
            "explanation": "Every delivered order with items belongs to exactly one customer_unique_id, so segment GMV must equal platform GMV.",
        }
    payload["scope_note"] = "Delivered orders, customers resolved on customer_unique_id; GMV = price + freight."
    payload["redaction_note"] = "Customer identifiers are truncated."
    return payload


@router.get("/customer-intelligence")
def get_customer_intelligence(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "customer-intelligence", build_olist_customer_intelligence)


@router.get("/forecast")
def get_forecast(warehouse: WarehouseDependency) -> dict[str, Any]:
    return cached_olist_payload(warehouse, "forecast", build_olist_forecast)


@router.get("/figures/{file_name}")
def get_figure(file_name: str, warehouse: WarehouseDependency) -> FileResponse:
    if file_name not in RESEARCH_FIGURES:
        raise HTTPException(status_code=404, detail="Unknown figure.")
    figure_path = warehouse.figure_path(file_name)
    if figure_path is None:
        raise HTTPException(status_code=404, detail="Figure not generated yet; run `python run.py`.")
    return FileResponse(figure_path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
