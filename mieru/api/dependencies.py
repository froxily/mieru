from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request

from mieru.config import Settings
from mieru.olist.warehouse import OlistDataUnavailableError, OlistWarehouse


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_olist_warehouse(request: Request) -> OlistWarehouse:
    return request.app.state.olist_warehouse


def cached_olist_payload(warehouse: OlistWarehouse, key: str, builder: Callable[[OlistWarehouse], Any]) -> Any:
    try:
        return warehouse.cached_payload(key, lambda: builder(warehouse))
    except OlistDataUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
