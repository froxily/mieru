from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mieru.config import PROJECT_ROOT, Settings
from mieru.main import create_app
from tests.product.upload_helpers import kpi, upload_and_wait

DEMO_DIR = PROJECT_ROOT / "demo"
SAMPLES_DIR = PROJECT_ROOT / "frontend" / "public" / "samples"
DEMO_CSV = DEMO_DIR / "mieru-demo-retail-orders.csv"
DEMO_XLSX = DEMO_DIR / "mieru-demo-retail-orders-ja.xlsx"
EXPECTED = {
    "net_revenue": 31_727_330.0,
    "orders": 1_385.0,
    "customers": 409.0,
    "units": 4_761.0,
    "gross_profit": 15_421_930.0,
    "returns_value": 200_630.0,
    "discounts_value": 443_900.0,
}
JAPANESE_ROLES = {
    "order_id": "注文番号",
    "line_id": "明細番号",
    "order_date": "注文日",
    "customer_id": "顧客ID",
    "product_name": "商品名",
    "category": "カテゴリ",
    "region": "都道府県",
    "channel": "販売チャネル",
    "quantity": "数量",
    "unit_price": "単価",
    "discount": "値引き",
    "unit_cost": "原価",
    "status": "ステータス",
    "currency": "通貨",
}


@pytest.fixture(scope="module")
def demo_client(test_settings: Settings) -> Iterator[TestClient]:
    app: FastAPI = create_app(test_settings.with_overrides(data_dir=test_settings.data_dir.parent / f"{test_settings.data_dir.name}-demo"))
    with TestClient(app) as client:
        yield client


def analysed(client: TestClient, path: Path) -> tuple[dict, dict]:
    status = upload_and_wait(client, path.name, path.read_bytes())
    assert status["dataset"]["status"] == "ready", status["dataset"].get("error")
    dashboard = client.get(f"/api/datasets/{status['dataset']['dataset_id']}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    return status, dashboard.json()


def test_demo_files_match_the_served_samples() -> None:
    assert DEMO_CSV.read_bytes() == (SAMPLES_DIR / "mieru-sample-retail-orders-synthetic.csv").read_bytes()
    assert DEMO_XLSX.read_bytes() == (SAMPLES_DIR / "mieru-sample-retail-orders-synthetic-ja.xlsx").read_bytes()


def test_demo_csv_and_japanese_workbook_give_identical_verified_kpis(demo_client: TestClient) -> None:
    csv_status, csv_dashboard = analysed(demo_client, DEMO_CSV)
    xlsx_status, xlsx_dashboard = analysed(demo_client, DEMO_XLSX)

    for metric_id, expected in EXPECTED.items():
        assert kpi(csv_dashboard, metric_id)["value"] == pytest.approx(expected), metric_id
        assert kpi(xlsx_dashboard, metric_id)["value"] == pytest.approx(expected), metric_id

    schema = xlsx_status["schema"]
    assert schema["role_columns"] == JAPANESE_ROLES
    assert schema["currency"] == "JPY"
    assert schema["clarifications"] == []
    assert csv_status["schema"]["clarifications"] == []
    assert schema["grain"] == csv_status["schema"]["grain"] == "line"
