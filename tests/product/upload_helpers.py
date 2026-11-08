import time
from typing import Any

from fastapi.testclient import TestClient

MUTATION_HEADERS: dict[str, str] = {"X-MIERU-Request": "1"}
POLL_TIMEOUT_SECONDS: float = 60.0


def upload_bytes(client: TestClient, file_name: str, content: bytes) -> Any:
    return client.post("/api/datasets", files={"file": (file_name, content, "application/octet-stream")}, headers=MUTATION_HEADERS)


def wait_until_settled(client: TestClient, dataset_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        payload = client.get(f"/api/datasets/{dataset_id}").json()
        if payload["dataset"]["status"] in {"ready", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Dataset {dataset_id} did not finish processing in time")


def upload_and_wait(client: TestClient, file_name: str, content: bytes) -> dict[str, Any]:
    response = upload_bytes(client, file_name, content)
    assert response.status_code == 202, response.text
    return wait_until_settled(client, response.json()["dataset_id"])


def kpi(dashboard: dict[str, Any], metric_id: str) -> dict[str, Any]:
    return next(item for item in dashboard["kpis"] if item["metric_id"] == metric_id)


def explain(client: TestClient, dataset_id: str, metric_id: str) -> dict[str, Any]:
    response = client.get(f"/api/datasets/{dataset_id}/metrics/{metric_id}/explain")
    assert response.status_code == 200, response.text
    return response.json()
