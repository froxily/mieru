import datetime as dt
import hmac
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mieru.config import Settings
from mieru.security.session import owner_fingerprint

DATASET_MARKER_FILE: str = ".mieru-dataset"
META_FILE: str = "meta.json"
SCHEMA_FILE: str = "schema.json"
AUDIT_FILE: str = "audit.json"
DATABASE_FILE: str = "dataset.duckdb"
DATASET_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DISPLAY_NAME_PATTERN = re.compile(r"[^\w\-. ()぀-ヿ㐀-鿿]+")
MAX_DISPLAY_NAME: int = 80
PAYLOAD_CACHE_SIZE: int = 256
FILE_RETRY_ATTEMPTS: int = 25
FILE_RETRY_DELAY_SECONDS: float = 0.01


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def sanitize_display_name(file_name: str) -> str:
    base = Path(file_name or "upload").name
    cleaned = DISPLAY_NAME_PATTERN.sub("_", base).strip(" ._") or "upload"
    return cleaned[:MAX_DISPLAY_NAME]


class PayloadCache:
    def __init__(self, max_entries: int = PAYLOAD_CACHE_SIZE) -> None:
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[Any, ...]) -> Any | None:
        with self._lock:
            if key not in self._entries:
                return None
            self._entries.move_to_end(key)
            return self._entries[key]

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def invalidate_dataset(self, dataset_id: str) -> None:
        with self._lock:
            for key in [key for key in self._entries if key and key[0] == dataset_id]:
                del self._entries[key]


class DatasetStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.datasets_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.cache = PayloadCache()

    def directory(self, dataset_id: str) -> Path | None:
        if not DATASET_ID_PATTERN.match(dataset_id or ""):
            return None
        candidate = (self.root / dataset_id).resolve()
        if candidate.parent != self.root:
            return None
        return candidate

    def create(self, session_token: str, file_name: str, extension: str) -> tuple[str, Path]:
        dataset_id = uuid.uuid4().hex
        directory = self.root / dataset_id
        directory.mkdir(parents=False, exist_ok=False)
        (directory / DATASET_MARKER_FILE).write_text("MIERU dataset directory (safe to delete after expiry)\n", encoding="utf-8")
        now = utc_now()
        meta = {
            "dataset_id": dataset_id,
            "owner": owner_fingerprint(session_token),
            "display_name": sanitize_display_name(file_name),
            "extension": extension,
            "status": "queued",
            "stage": "uploaded",
            "error": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": (now + dt.timedelta(seconds=self.settings.dataset_ttl_seconds)).isoformat(),
            "policies": {},
            "mapping_overrides": {},
            "data_version": 1,
            "size_bytes": 0,
            "sha256": None,
        }
        self.write_meta(dataset_id, meta)
        return dataset_id, directory

    def source_path(self, dataset_id: str, extension: str) -> Path:
        directory = self.directory(dataset_id)
        if directory is None:
            raise ValueError("Invalid dataset id")
        return directory / f"source{extension}"

    def database_path(self, dataset_id: str) -> Path:
        directory = self.directory(dataset_id)
        if directory is None:
            raise ValueError("Invalid dataset id")
        return directory / DATABASE_FILE

    def read_json(self, dataset_id: str, file_name: str) -> Any | None:
        directory = self.directory(dataset_id)
        if directory is None:
            return None
        path = directory / file_name
        for attempt in range(FILE_RETRY_ATTEMPTS):
            if not path.is_file():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except PermissionError:
                time.sleep(FILE_RETRY_DELAY_SECONDS * (attempt + 1))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def write_json(self, dataset_id: str, file_name: str, payload: Any) -> None:
        directory = self.directory(dataset_id)
        if directory is None:
            raise ValueError("Invalid dataset id")
        temporary = directory / f".{file_name}.{threading.get_ident()}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        for attempt in range(FILE_RETRY_ATTEMPTS):
            try:
                os.replace(temporary, directory / file_name)
                return
            except PermissionError:
                if attempt == FILE_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(FILE_RETRY_DELAY_SECONDS * (attempt + 1))

    def read_meta(self, dataset_id: str) -> dict[str, Any] | None:
        return self.read_json(dataset_id, META_FILE)

    def write_meta(self, dataset_id: str, meta: dict[str, Any]) -> None:
        self.write_json(dataset_id, META_FILE, meta)

    def update_meta(self, dataset_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            meta = self.read_meta(dataset_id)
            if meta is None:
                return None
            meta.update(fields)
            meta["updated_at"] = utc_now().isoformat()
            self.write_meta(dataset_id, meta)
            return meta

    def mutate_meta(self, dataset_id: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any] | None:
        with self._lock:
            meta = self.read_meta(dataset_id)
            if meta is None:
                return None
            mutate(meta)
            meta["updated_at"] = utc_now().isoformat()
            self.write_meta(dataset_id, meta)
            return meta

    @staticmethod
    def is_expired(meta: dict[str, Any], now: dt.datetime | None = None) -> bool:
        try:
            expires_at = dt.datetime.fromisoformat(meta["expires_at"])
        except (KeyError, ValueError, TypeError):
            return True
        return expires_at <= (now or utc_now())

    def get_owned(self, dataset_id: str, session_token: str | None) -> dict[str, Any] | None:
        if not session_token:
            return None
        meta = self.read_meta(dataset_id)
        if meta is None or self.is_expired(meta):
            return None
        if not hmac.compare_digest(str(meta.get("owner", "")), owner_fingerprint(session_token)):
            return None
        return meta

    def list_owned(self, session_token: str | None) -> list[dict[str, Any]]:
        if not session_token:
            return []
        fingerprint = owner_fingerprint(session_token)
        owned = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not DATASET_ID_PATTERN.match(directory.name):
                continue
            meta = self.read_meta(directory.name)
            if meta and not self.is_expired(meta) and hmac.compare_digest(str(meta.get("owner", "")), fingerprint):
                owned.append(meta)
        return sorted(owned, key=lambda item: item.get("created_at", ""), reverse=True)

    def safe_remove(self, dataset_id: str) -> bool:
        directory = self.directory(dataset_id)
        if directory is None or not directory.is_dir():
            return False
        if not (directory / DATASET_MARKER_FILE).is_file():
            return False
        if directory.parent != self.root or directory.is_symlink():
            return False
        shutil.rmtree(directory)
        self.cache.invalidate_dataset(dataset_id)
        return True

    def cleanup_expired(self, now: dt.datetime | None = None) -> int:
        removed = 0
        moment = now or utc_now()
        for directory in list(self.root.iterdir()):
            if not directory.is_dir() or directory.is_symlink() or not DATASET_ID_PATTERN.match(directory.name):
                continue
            if not (directory / DATASET_MARKER_FILE).is_file():
                continue
            meta = self.read_meta(directory.name)
            if meta is None:
                age_seconds = moment.timestamp() - (directory / DATASET_MARKER_FILE).stat().st_mtime
                if age_seconds < 2 * self.settings.dataset_ttl_seconds:
                    continue
            elif not self.is_expired(meta, moment):
                continue
            if self.safe_remove(directory.name):
                removed += 1
        return removed
