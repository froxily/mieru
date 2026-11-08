import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mieru.config import PROJECT_ROOT, Settings, load_settings
from mieru.main import create_app

TEST_DATA_ROOT: Path = PROJECT_ROOT / ".cache" / "test-var"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    import os

    previous_environment = os.environ.get("MIERU_ENV")
    os.environ["MIERU_ENV"] = "test"
    try:
        settings = load_settings()
    finally:
        if previous_environment is None:
            os.environ.pop("MIERU_ENV", None)
        else:
            os.environ["MIERU_ENV"] = previous_environment
    return settings.with_overrides(data_dir=TEST_DATA_ROOT / uuid.uuid4().hex)


@pytest.fixture(scope="session")
def app(test_settings: Settings) -> FastAPI:
    return create_app(test_settings)


@pytest.fixture(scope="session")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
