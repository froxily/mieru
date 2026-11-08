from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, HTTPException

from mieru.api.dependencies import get_olist_warehouse
from mieru.olist.metrics import OLIST_METRICS, OLIST_METRICS_BY_ID, explain_olist_metric
from mieru.olist.warehouse import OlistDataUnavailableError, OlistWarehouse

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
WarehouseDependency: TypeAlias = Annotated[OlistWarehouse, Depends(get_olist_warehouse)]


@router.get("/olist")
def list_olist_metrics() -> dict[str, Any]:
    return {
        "source": "olist",
        "metrics": [
            {**metric.definition.to_dict(), "available": metric.unavailable_reason is None, "unavailable_reason": metric.unavailable_reason}
            for metric in OLIST_METRICS
        ],
    }


@router.get("/olist/{metric_id}/explain")
def explain_olist(metric_id: str, warehouse: WarehouseDependency) -> dict[str, Any]:
    if metric_id not in OLIST_METRICS_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown metric.")
    try:
        return warehouse.cached_payload(f"explain:{metric_id}", lambda: explain_olist_metric(warehouse, metric_id).to_dict())
    except OlistDataUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
