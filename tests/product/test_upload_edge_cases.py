import io
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mieru.config import Settings
from mieru.main import create_app
from tests.product.upload_helpers import explain, kpi, upload_and_wait, upload_bytes

LINE_ITEM_HEADER = "transaction_id,order_id,order_date,customer_id,product,quantity,unit_price,order_total"
LINE_ITEM_ROWS = (
    "T1,A1,2024-01-05,C1,Widget,2,12.50,32.00",
    "T2,A1,2024-01-05,C1,Gadget,1,7.00,32.00",
    "T3,A2,2024-01-06,C2,Book,3,4.00,12.00",
    "T4,A3,2024-01-07,C1,Lamp,2,9.00,18.00",
)


@pytest.fixture(scope="module")
def upload_app(test_settings: Settings) -> FastAPI:
    return create_app(
        test_settings.with_overrides(
            data_dir=test_settings.data_dir.parent / f"{test_settings.data_dir.name}-upload-edge-cases",
            max_datasets_per_session=500,
            uploads_per_ip_per_hour=5000,
            max_upload_bytes=2 * 1024 * 1024,
        )
    )


@pytest.fixture(scope="module")
def upload_client(upload_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(upload_app) as client:
        yield client


def ready_dashboard(client: TestClient, file_name: str, content: bytes) -> tuple[str, dict[str, Any]]:
    status = upload_and_wait(client, file_name, content)
    assert status["dataset"]["status"] == "ready", status["dataset"].get("error")
    dataset_id = status["dataset"]["dataset_id"]
    dashboard = client.get(f"/api/datasets/{dataset_id}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    return dataset_id, dashboard.json()


def test_line_item_revenue_orders_customers_and_units_are_invariant_to_row_order(upload_client: TestClient) -> None:
    original = ("\n".join((LINE_ITEM_HEADER, *LINE_ITEM_ROWS)) + "\n").encode("utf-8")
    shuffled = (
        "\n".join((LINE_ITEM_HEADER, LINE_ITEM_ROWS[2], LINE_ITEM_ROWS[0], LINE_ITEM_ROWS[3], LINE_ITEM_ROWS[1])) + "\n"
    ).encode("utf-8")
    _original_id, original_dashboard = ready_dashboard(upload_client, "original-lines.csv", original)
    _shuffled_id, shuffled_dashboard = ready_dashboard(upload_client, "shuffled-lines.csv", shuffled)
    for dashboard in (original_dashboard, shuffled_dashboard):
        assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(2 * 12.50 + 7.00 + 3 * 4.00 + 2 * 9.00)
        assert kpi(dashboard, "orders")["value"] == 3
        assert kpi(dashboard, "customers")["value"] == 2
        assert kpi(dashboard, "units")["value"] == 2 + 1 + 3 + 2


def test_duplicating_every_identified_line_preserves_totals_and_reports_four_confirmed_duplicates(upload_client: TestClient) -> None:
    original = ("\n".join((LINE_ITEM_HEADER, *LINE_ITEM_ROWS)) + "\n").encode("utf-8")
    doubled = ("\n".join((LINE_ITEM_HEADER, *LINE_ITEM_ROWS, *LINE_ITEM_ROWS)) + "\n").encode("utf-8")
    _original_id, original_dashboard = ready_dashboard(upload_client, "identified-lines.csv", original)
    dataset_id, doubled_dashboard = ready_dashboard(upload_client, "doubled-lines.csv", doubled)
    for dashboard in (original_dashboard, doubled_dashboard):
        assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(2 * 12.50 + 7.00 + 3 * 4.00 + 2 * 9.00)
        assert kpi(dashboard, "orders")["value"] == 3
    response = upload_client.get(f"/api/datasets/{dataset_id}/quality")
    assert response.status_code == 200, response.text
    quality = response.json()
    issues = {issue["code"]: issue for issue in quality["issues"]}
    assert quality["summary"]["rows_in_file"] == 4 + 4
    assert issues["dup_reliable"]["rows"] == 4
    assert issues["dup_reliable"]["treatment"] == "excluded"
    assert "dup_possible" not in issues


def test_identical_rows_without_identifiers_are_flagged_as_possible_duplicates_and_kept(upload_client: TestClient) -> None:
    content = b"date,product,amount\n2024-06-01,Coffee,8.00\n2024-06-01,Coffee,8.00\n2024-06-02,Tea,6.00\n"
    dataset_id, _dashboard = ready_dashboard(upload_client, "possible-duplicates.csv", content)
    response = upload_client.get(f"/api/datasets/{dataset_id}/quality")
    assert response.status_code == 200, response.text
    quality = response.json()
    issues = {issue["code"]: issue for issue in quality["issues"]}
    assert quality["summary"]["rows_in_file"] == 3
    assert issues["dup_possible"]["rows"] == 1
    assert issues["dup_possible"]["treatment"] == "kept"
    assert "dup_reliable" not in issues
    policy = next(item for item in quality["policies"] if item["key"] == "exclude_possible_duplicates")
    assert policy["enabled"] is False


def test_split_payments_sum_every_payment_and_count_distinct_orders(upload_client: TestClient) -> None:
    content = b"""order_id,payment_type,payment_value
P1,credit_card,12.00
P1,voucher,5.00
P2,credit_card,8.00
P2,cash,3.00
P3,bank_transfer,9.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "split-payments.csv", content)
    assert kpi(dashboard, "orders")["value"] == 3
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(12.00 + 5.00 + 8.00 + 3.00 + 9.00)


def test_mixed_unambiguous_iso_japanese_and_slash_dates_all_appear_in_trend(upload_client: TestClient) -> None:
    content = """order_id,order_date,amount
D1,2024-01-05,10.00
D2,2024年1月6日,20.00
D3,2024/01/07,30.00
D4,25/01/2024,40.00
""".encode("utf-8")
    dataset_id, dashboard = ready_dashboard(upload_client, "mixed-dates.csv", content)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(10.00 + 20.00 + 30.00 + 40.00)
    assert dashboard["trend"]["available"] is True
    assert dashboard["trend"]["first_date"] == "2024-01-05"
    assert dashboard["trend"]["last_date"] == "2024-01-25"
    points = dashboard["trend"]["points"]
    assert len(points) == 25 - 5 + 1
    assert [(point["period"], point["revenue"], point["orders"]) for point in points if point["orders"]] == [
        ("2024-01-05", 10.00, 1),
        ("2024-01-06", 20.00, 1),
        ("2024-01-07", 30.00, 1),
        ("2024-01-25", 40.00, 1),
    ]
    assert all(point["revenue"] == 0.0 for point in points if not point["orders"])
    response = upload_client.get(f"/api/datasets/{dataset_id}/quality")
    assert response.status_code == 200, response.text
    assert "date_invalid" not in {issue["code"] for issue in response.json()["issues"]}


def test_xlsx_formulas_without_cached_values_are_missing_and_excluded_from_revenue(upload_client: TestClient) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sales = workbook.active
    sales.title = "Sales"
    sales.append(["order_id", "order_date", "amount"])
    sales.append(["F1", "2024-02-01", 10.00])
    sales.append(["F2", "2024-02-02", "=2*15"])
    sales.append(["F3", "2024-02-03", 7.50])
    sales.append(["F4", "2024-02-04", "=SUM(20,5)"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    dataset_id, dashboard = ready_dashboard(upload_client, "uncached-formulas.xlsx", buffer.getvalue())
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(10.00 + 7.50)
    assert kpi(dashboard, "orders")["value"] == 4
    counts = explain(upload_client, dataset_id, "net_revenue")["record_counts"]
    assert counts["input_records"] == 4
    assert counts["contributing_records"] == 2
    assert {item["reason"]: item["records"] for item in counts["excluded"]} == {"invalid_amount": 2}
    response = upload_client.get(f"/api/datasets/{dataset_id}/quality")
    assert response.status_code == 200, response.text
    issues = {issue["code"]: issue for issue in response.json()["issues"]}
    assert issues["value_invalid"]["rows"] == 2


def test_missing_date_column_preserves_kpis_and_disables_trend_with_reason(upload_client: TestClient) -> None:
    content = b"""order_id,customer_id,product,quantity,unit_price
N1,C1,Pen,2,3.00
N1,C1,Book,1,8.00
N2,C2,Lamp,3,5.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "no-dates.csv", content)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(2 * 3.00 + 8.00 + 3 * 5.00)
    assert kpi(dashboard, "orders")["value"] == 2
    assert kpi(dashboard, "customers")["value"] == 2
    assert kpi(dashboard, "units")["value"] == 2 + 1 + 3
    assert dashboard["trend"]["available"] is False
    assert isinstance(dashboard["trend"]["reason"], str)
    assert dashboard["trend"]["reason"].strip()


def test_rows_with_too_few_fields_are_counted_in_quality_without_crashing(upload_client: TestClient) -> None:
    content = b"order_id,order_date,amount\nR1,2024-03-01,10.00\nR2,2024-03-02\nR3,2024-03-03,30.00\n"
    dataset_id, dashboard = ready_dashboard(upload_client, "too-few-fields.csv", content)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(10.00 + 30.00)
    assert kpi(dashboard, "orders")["value"] == 3
    response = upload_client.get(f"/api/datasets/{dataset_id}/quality")
    assert response.status_code == 200, response.text
    quality = response.json()
    assert quality["summary"]["rows_in_file"] == 3
    issues = {issue["code"]: issue for issue in quality["issues"]}
    assert issues["is_ragged"]["rows"] == 1
    assert issues["is_ragged"]["treatment"] == "flagged"


def test_rows_with_too_many_fields_are_counted_in_quality_without_crashing(upload_client: TestClient) -> None:
    content = b"order_id,order_date,amount\nR1,2024-03-01,10.00\nR2,2024-03-02,20.00,unexpected\nR3,2024-03-03,30.00\n"
    dataset_id, dashboard = ready_dashboard(upload_client, "too-many-fields.csv", content)
    assert dashboard["dataset"]["columns"] == 3
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(10.00 + 20.00 + 30.00)
    assert kpi(dashboard, "orders")["value"] == 3
    response = upload_client.get(f"/api/datasets/{dataset_id}/quality")
    assert response.status_code == 200, response.text
    quality = response.json()
    assert quality["summary"]["rows_in_file"] == 3
    issues = {issue["code"]: issue for issue in quality["issues"]}
    assert issues["is_ragged"]["rows"] == 1
    assert issues["is_ragged"]["treatment"] == "flagged"


def test_third_consecutive_upload_exceeds_two_uploads_per_ip_per_hour(test_settings: Settings) -> None:
    app = create_app(
        test_settings.with_overrides(
            data_dir=test_settings.data_dir.parent / f"{test_settings.data_dir.name}-upload-rate-limit",
            max_datasets_per_session=500,
            uploads_per_ip_per_hour=2,
        )
    )
    content = b"order_id,amount\nL1,10.00\nL2,20.00\n"
    with TestClient(app) as client:
        first = upload_bytes(client, "first.csv", content)
        second = upload_bytes(client, "second.csv", content)
        third = upload_bytes(client, "third.csv", content)
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert third.status_code == 429, third.text
        assert third.json()["detail"] == "Too many uploads from this address. Please try again later."
