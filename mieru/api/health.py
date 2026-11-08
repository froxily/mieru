from typing import Annotated, Any

from fastapi import APIRouter, Depends

from mieru import PRODUCT_NAME, PRODUCT_TAGLINE, __version__
from mieru.api.dependencies import get_olist_warehouse, get_settings
from mieru.config import Settings
from mieru.olist.warehouse import OlistDataUnavailableError, OlistWarehouse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def get_health(
    settings: Annotated[Settings, Depends(get_settings)],
    warehouse: Annotated[OlistWarehouse, Depends(get_olist_warehouse)],
) -> dict[str, Any]:
    try:
        warehouse.database_mtime()
        olist_status = "ready"
    except OlistDataUnavailableError:
        olist_status = "missing — run `python run.py`"
    return {
        "status": "ok",
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": __version__,
        "environment": settings.environment,
        "olist_demo": olist_status,
        "limits": {
            "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
            "max_upload_rows": settings.max_upload_rows,
            "dataset_ttl_minutes": settings.dataset_ttl_seconds // 60,
            "accepted_extensions": [".csv", ".tsv", ".txt", ".xlsx"],
        },
    }
