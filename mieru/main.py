import logging
import tempfile
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mieru import PRODUCT_NAME, PRODUCT_TAGLINE, __version__
from mieru.api import datasets, health, metrics, olist
from mieru.config import Settings, load_settings
from mieru.datasets.processor import ProcessingPool
from mieru.datasets.store import DatasetStore
from mieru.olist.warehouse import OlistWarehouse
from mieru.security.limits import UploadBodyLimitMiddleware
from mieru.security.session import SlidingWindowLimiter
from mieru.web import install_security_headers, mount_frontend
from src.api import app as legacy_research_app

LOGGER = logging.getLogger("mieru")
MULTIPART_OVERHEAD_BYTES: int = 1024 * 1024
UPLOAD_WINDOW_SECONDS: int = 3600


def run_cleanup_loop(store: DatasetStore, interval_seconds: int, stop_event: threading.Event) -> None:
    while not stop_event.wait(interval_seconds):
        try:
            removed = store.cleanup_expired()
            if removed:
                LOGGER.info("Removed %d expired dataset(s)", removed)
        except OSError:
            LOGGER.exception("Dataset cleanup failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or load_settings()
    resolved_settings.data_dir.mkdir(parents=True, exist_ok=True)
    resolved_settings.temp_dir.mkdir(parents=True, exist_ok=True)
    (resolved_settings.temp_dir / "duckdb").mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(resolved_settings.temp_dir)
    olist_warehouse = OlistWarehouse(
        resolved_settings.olist_database_path,
        resolved_settings.research_outputs_dir,
        resolved_settings.research_baseline_dir,
    )
    dataset_store = DatasetStore(resolved_settings)
    @asynccontextmanager
    async def lifespan(running_app: FastAPI) -> AsyncGenerator[None]:
        processing_pool = ProcessingPool(resolved_settings.processing_workers, resolved_settings.processing_queue_limit)
        running_app.state.processing_pool = processing_pool
        stop_event = threading.Event()
        dataset_store.cleanup_expired()
        cleanup_thread = threading.Thread(
            target=run_cleanup_loop,
            args=(dataset_store, resolved_settings.cleanup_interval_seconds, stop_event),
            name="mieru-cleanup",
            daemon=True,
        )
        cleanup_thread.start()
        yield
        stop_event.set()
        processing_pool.shutdown()
        olist_warehouse.close()

    app = FastAPI(
        title=f"{PRODUCT_NAME} — {PRODUCT_TAGLINE}",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.olist_warehouse = olist_warehouse
    app.state.dataset_store = dataset_store
    app.state.upload_limiter = SlidingWindowLimiter(resolved_settings.uploads_per_ip_per_hour, UPLOAD_WINDOW_SECONDS)
    install_security_headers(app, enable_hsts=resolved_settings.is_production)
    app.add_middleware(UploadBodyLimitMiddleware, max_body_bytes=resolved_settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES)
    app.include_router(health.router)
    app.include_router(olist.router)
    app.include_router(metrics.router)
    app.include_router(datasets.router)
    app.mount("/api/olist/research", legacy_research_app)
    mount_frontend(app, resolved_settings.frontend_dist_dir)
    return app
