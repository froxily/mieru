import os
import secrets
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
MIN_SESSION_SECRET_BYTES: int = 32
VALID_ENVIRONMENTS: frozenset[str] = frozenset({"development", "production", "test"})
DEV_SECRET_FILE_NAME: str = "dev_session_secret"
PRIVATE_PROXY_NETWORKS: str = "127.0.0.1,10.0.0.0/8,100.64.0.0/10,172.16.0.0/12,192.168.0.0/16"


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    environment: str
    data_dir: Path
    olist_database_path: Path
    research_outputs_dir: Path
    research_baseline_dir: Path
    frontend_dist_dir: Path
    session_secret: bytes
    secure_cookies: bool
    max_upload_bytes: int
    max_upload_rows: int
    max_upload_columns: int
    dataset_ttl_seconds: int
    max_datasets_per_session: int
    uploads_per_ip_per_hour: int
    processing_workers: int
    processing_queue_limit: int
    cleanup_interval_seconds: int
    duckdb_memory_limit: str
    duckdb_threads: int
    host: str
    port: int
    forwarded_allow_ips: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def with_overrides(self, **overrides: object) -> "Settings":
        return replace(self, **overrides)


def read_int(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer, got {raw_value!r}") from error
    if value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}, got {value}")
    return value


def read_path(name: str, default: Path) -> Path:
    raw_value = os.environ.get(name)
    return Path(raw_value).expanduser().resolve() if raw_value else default


def resolve_session_secret(environment: str, data_dir: Path) -> bytes:
    configured_secret = os.environ.get("MIERU_SESSION_SECRET", "")
    if configured_secret:
        secret_bytes = configured_secret.encode("utf-8")
        if len(secret_bytes) < MIN_SESSION_SECRET_BYTES:
            raise ConfigurationError(f"MIERU_SESSION_SECRET must be at least {MIN_SESSION_SECRET_BYTES} bytes long.")
        return secret_bytes
    if environment == "production":
        raise ConfigurationError(
            "MIERU_SESSION_SECRET is required when MIERU_ENV=production (a persistent secret of at least "
            f"{MIN_SESSION_SECRET_BYTES} bytes, e.g. an Azure Container Apps secret)."
        )
    if environment == "test":
        return secrets.token_bytes(MIN_SESSION_SECRET_BYTES)
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_path = data_dir / DEV_SECRET_FILE_NAME
    if secret_path.exists():
        stored_secret = secret_path.read_text(encoding="utf-8").strip()
        if len(stored_secret) >= MIN_SESSION_SECRET_BYTES:
            return stored_secret.encode("utf-8")
    generated_secret = secrets.token_hex(MIN_SESSION_SECRET_BYTES)
    secret_path.write_text(generated_secret, encoding="utf-8")
    return generated_secret.encode("utf-8")


def load_settings() -> Settings:
    environment = os.environ.get("MIERU_ENV", "development").strip().lower()
    if environment not in VALID_ENVIRONMENTS:
        raise ConfigurationError(f"MIERU_ENV must be one of {sorted(VALID_ENVIRONMENTS)}, got {environment!r}")
    data_dir = read_path("MIERU_DATA_DIR", PROJECT_ROOT / "var")
    return Settings(
        environment=environment,
        data_dir=data_dir,
        olist_database_path=read_path("MIERU_OLIST_DATABASE", PROJECT_ROOT / "data" / "marketplace.duckdb"),
        research_outputs_dir=read_path("MIERU_RESEARCH_OUTPUTS", PROJECT_ROOT / "outputs"),
        research_baseline_dir=PROJECT_ROOT / "baselines" / "2026-10-15",
        frontend_dist_dir=read_path("MIERU_FRONTEND_DIST", PROJECT_ROOT / "frontend" / "dist"),
        session_secret=resolve_session_secret(environment, data_dir),
        secure_cookies=environment == "production",
        max_upload_bytes=read_int("MIERU_MAX_UPLOAD_MB", 50, minimum=1) * 1024 * 1024,
        max_upload_rows=read_int("MIERU_MAX_UPLOAD_ROWS", 1_000_000, minimum=1),
        max_upload_columns=read_int("MIERU_MAX_UPLOAD_COLUMNS", 300, minimum=1),
        dataset_ttl_seconds=read_int("MIERU_DATASET_TTL_MINUTES", 120, minimum=1) * 60,
        max_datasets_per_session=read_int("MIERU_MAX_DATASETS_PER_SESSION", 5, minimum=1),
        uploads_per_ip_per_hour=read_int("MIERU_UPLOADS_PER_IP_PER_HOUR", 30, minimum=1),
        processing_workers=read_int("MIERU_PROCESSING_WORKERS", 2, minimum=1),
        processing_queue_limit=read_int("MIERU_PROCESSING_QUEUE_LIMIT", 4, minimum=0),
        cleanup_interval_seconds=read_int("MIERU_CLEANUP_INTERVAL_SECONDS", 600, minimum=10),
        duckdb_memory_limit=os.environ.get("MIERU_DUCKDB_MEMORY_LIMIT", "1GB"),
        duckdb_threads=read_int("MIERU_DUCKDB_THREADS", 2, minimum=1),
        host=os.environ.get("MIERU_HOST", "127.0.0.1"),
        port=read_int("MIERU_PORT", 8000, minimum=1),
        forwarded_allow_ips=os.environ.get("MIERU_FORWARDED_ALLOW_IPS", PRIVATE_PROXY_NETWORKS) if environment == "production" else None,
    )
