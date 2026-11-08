import io
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mieru.config import Settings
from mieru.main import create_app
from tests.product.upload_helpers import MUTATION_HEADERS, explain, kpi, upload_and_wait, upload_bytes, wait_until_settled


@pytest.fixture(scope="module")
def upload_app(test_settings: Settings) -> FastAPI:
    return create_app(
        test_settings.with_overrides(
            data_dir=test_settings.data_dir.parent / f"{test_settings.data_dir.name}-review-regressions",
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


def test_sparse_xlsx_is_rejected_before_iterating_rows(upload_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sales = workbook.active
    sales.append(["order_id", "amount"])
    sales.append(["S1", 100.00])
    sales.cell(row=1_000_000, column=16384, value="sparse sentinel")
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    def forbid_row_iteration(worksheet: Any, *args: Any, **kwargs: Any) -> Iterator[tuple[Any, ...]]:
        raise AssertionError("Sparse workbook dimensions must be rejected before row iteration")

    monkeypatch.setattr("openpyxl.worksheet._read_only.ReadOnlyWorksheet.iter_rows", forbid_row_iteration)
    response = upload_bytes(upload_client, "sparse-bomb.xlsx", buffer.getvalue())
    assert response.status_code == 202, response.text
    status = wait_until_settled(upload_client, response.json()["dataset_id"])
    assert status["dataset"]["status"] == "failed", status
    assert "too large" in status["dataset"]["error"].lower()


def test_order_total_returns_reverse_revenue_and_do_not_count_as_orders(upload_client: TestClient) -> None:
    content = b"""order_id,order_date,status,order_total
S1,2024-01-02,completed,100.00
R1,2024-01-03,returned,100.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "order-total-returns.csv", content)
    assert dashboard["dataset"]["revenue_basis"] == "order_total"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(100.00 - 100.00)
    assert kpi(dashboard, "orders")["value"] == 1


def test_explicit_line_total_is_never_promoted_to_order_total(upload_client: TestClient) -> None:
    content = b"""order_id,line_id,product_id,line_total
A,1,P1,100.00
A,2,P2,100.00
B,1,P3,40.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "explicit-line-total.csv", content)
    assert dashboard["dataset"]["revenue_basis"] == "line_amount"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(100.00 + 100.00 + 40.00)


def test_neutral_amount_with_one_multiline_order_keeps_lines_and_requests_clarification(upload_client: TestClient) -> None:
    content = b"""order_id,product_id,amount
A,P1,100.00
A,P2,100.00
B,P3,40.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "ambiguous-order-total.csv", content)
    assert dashboard["dataset"]["revenue_basis"] == "line_amount"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(100.00 + 100.00 + 40.00)
    assert any(item["kind"] == "ambiguous_role" and item["role"] == "order_total" for item in dashboard["clarifications"])


def test_discounted_returns_reverse_net_value_and_reconcile_the_bridge(upload_client: TestClient) -> None:
    content = b"""transaction_id,order_id,order_date,product,quantity,unit_price,discount,status
T1,O1,2024-01-01,Widget,1,100.00,10.00,completed
T2,O2,2024-01-05,Widget,1,100.00,10.00,returned
"""
    dataset_id, dashboard = ready_dashboard(upload_client, "discounted-returns.csv", content)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx((100.00 - 10.00) - (100.00 - 10.00))
    assert explain(upload_client, dataset_id, "returns_value")["value"] == pytest.approx(100.00 - 10.00)
    assert explain(upload_client, dataset_id, "gross_sales")["value"] == pytest.approx(100.00)
    assert explain(upload_client, dataset_id, "discounts_value")["value"] == pytest.approx(10.00)
    assert explain(upload_client, dataset_id, "return_rate")["value"] == pytest.approx((100.00 - 10.00) / (100.00 - 10.00))
    response = upload_client.get(f"/api/datasets/{dataset_id}/performance")
    assert response.status_code == 200, response.text
    bridge = response.json()["bridge"]
    assert bridge["available"] is True
    assert bridge["reconciles"] is True
    assert bridge["returns_value"] == pytest.approx(100.00 - 10.00)
    assert bridge["net_revenue"] == pytest.approx((100.00 - 10.00) - (100.00 - 10.00))


def test_money_in_excel_serial_range_uses_line_amount_instead_of_price_times_quantity(upload_client: TestClient) -> None:
    content = b"""order_id,order_date,quantity,unit_price,line_total
M1,2024-01-01,1,2.00,49000.00
M2,2024-01-02,2,3.00,31000.00
M3,2024-01-03,3,4.00,45500.00
M4,2024-01-04,4,5.00,27250.00
M5,2024-01-05,5,6.00,58000.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "money-not-excel-dates.csv", content)
    assert dashboard["dataset"]["revenue_basis"] == "line_amount"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(49000.00 + 31000.00 + 45500.00 + 27250.00 + 58000.00)


def test_product_concentration_is_skipped_for_mixed_currencies(upload_client: TestClient) -> None:
    rows = ["order_id,order_date,product,amount,currency", "FX0,2024-01-01,Product0,1000.00,USD"]
    rows.extend(f"FX{index},2024-01-{index + 1:02d},Product{index},1.00,EUR" for index in range(1, 10))
    dataset_id, dashboard = ready_dashboard(upload_client, "mixed-currency-products.csv", ("\n".join(rows) + "\n").encode("utf-8"))
    assert kpi(dashboard, "net_revenue")["status"] == "unavailable"
    assert kpi(dashboard, "net_revenue")["value"] is None
    response = upload_client.get(f"/api/datasets/{dataset_id}/insights")
    assert response.status_code == 200, response.text
    insights = response.json()
    assert all(card["insight_id"] != "product_concentration" for card in insights["cards"])
    assert "product_concentration" in {item["rule"] for item in insights["skipped"]}


def test_trend_revenue_includes_rows_without_an_order_id(upload_client: TestClient) -> None:
    rows = ["order_id,order_date,amount"]
    rows.extend(f"D{day},2024-01-{day:02d},10.00" for day in range(1, 10))
    rows.append(",2024-01-10,90.00")
    _dataset_id, dashboard = ready_dashboard(upload_client, "trend-missing-order-id.csv", ("\n".join(rows) + "\n").encode("utf-8"))
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(9 * 10.00 + 90.00)
    assert kpi(dashboard, "orders")["value"] == 9
    trend = dashboard["trend"]
    assert trend["available"] is True
    assert trend["granularity"] == "day"
    assert len(trend["points"]) == 9 + 1
    assert sum(point["revenue"] for point in trend["points"]) == pytest.approx(9 * 10.00 + 90.00)
    assert sum(point["orders"] for point in trend["points"]) == 9
    unidentified = next(point for point in trend["points"] if point["period"] == "2024-01-10")
    assert unidentified["revenue"] == pytest.approx(90.00)
    assert unidentified["orders"] == 0


def test_filtered_markdown_export_uses_the_same_scope_for_kpis_and_quality_impact(upload_client: TestClient) -> None:
    content = b"""order_id,order_date,amount
JAN,2024-01-15,100.00
FEB,2024-02-15,900.00
"""
    dataset_id, _dashboard = ready_dashboard(upload_client, "filtered-report.csv", content)
    response = upload_client.get(f"/api/datasets/{dataset_id}/export/report.md", params={"start": "2024-01-01", "end": "2024-01-31"})
    assert response.status_code == 200, response.text
    report = response.text
    key_metrics = report.split("## Key metrics\n", 1)[1].split("\n## ", 1)[0]
    quality_impact = report.split("## Data quality impact\n", 1)[1].split("\n## ", 1)[0]
    metric_line = next(line for line in key_metrics.splitlines() if line.startswith("| Net revenue |"))
    impact_line = next(line for line in quality_impact.splitlines() if line.startswith("| Net revenue |"))
    metric_cells = [cell.strip() for cell in metric_line.strip("|").split("|")]
    impact_cells = [cell.strip() for cell in impact_line.strip("|").split("|")]
    assert metric_cells[1] == f"{100.00:,.2f}"
    assert impact_cells[2] == f"{100.00:,.2f}"
    assert impact_cells[1] == f"{100.00:,.2f}"


def test_rejected_mapping_change_restores_mapping_and_ready_status(test_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(
        test_settings.with_overrides(
            data_dir=test_settings.data_dir.parent / f"{test_settings.data_dir.name}-review-regressions-mapping",
            max_datasets_per_session=500,
            uploads_per_ip_per_hour=5000,
            max_upload_bytes=2 * 1024 * 1024,
        )
    )
    content = b"order_id,order_date,amount\nA,2024-01-01,10.00\nB,2024-01-02,20.00\n"
    with TestClient(app) as client:
        dataset_id, _dashboard = ready_dashboard(client, "mapping-rollback.csv", content)
        store = app.state.dataset_store
        before = store.read_meta(dataset_id)
        assert before is not None
        previous_overrides = dict(before["mapping_overrides"])

        def reject_submission(task: Callable[[], None]) -> bool:
            return False

        monkeypatch.setattr(app.state.processing_pool, "try_submit", reject_submission)
        response = client.put(f"/api/datasets/{dataset_id}/mapping", json={"mapping": {"amount": "amount"}}, headers=MUTATION_HEADERS)
        assert response.status_code == 429, response.text
        after = store.read_meta(dataset_id)
        assert after is not None
        assert after["mapping_overrides"] == previous_overrides
        assert after["status"] == "ready"


def test_concurrent_policy_updates_preserve_both_changes_and_increment_version_twice(
    upload_app: FastAPI, upload_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"order_id,order_date,amount\nA,2024-01-01,10.00\nB,2024-01-02,20.00\n"
    dataset_id, _dashboard = ready_dashboard(upload_client, "concurrent-policies.csv", content)
    store = upload_app.state.dataset_store
    before = store.read_meta(dataset_id)
    assert before is not None
    initial_version = before["data_version"]
    start_requests = Barrier(2)
    snapshots_read = Barrier(2)
    original_get_owned = store.get_owned

    def get_owned_with_shared_snapshot(requested_id: str, session_token: str | None) -> dict[str, Any] | None:
        meta = original_get_owned(requested_id, session_token)
        if requested_id == dataset_id:
            snapshots_read.wait(timeout=10.0)
        return meta

    def update_policy(key: str, enabled: bool) -> None:
        start_requests.wait(timeout=10.0)
        response = upload_client.put(f"/api/datasets/{dataset_id}/policies", json={"policies": {key: enabled}}, headers=MUTATION_HEADERS)
        assert response.status_code == 200, response.text

    with monkeypatch.context() as patch:
        patch.setattr(store, "get_owned", get_owned_with_shared_snapshot)
        with ThreadPoolExecutor(max_workers=2) as executor:
            exclude_cancelled = executor.submit(update_policy, "exclude_cancelled", False)
            exclude_possible_duplicates = executor.submit(update_policy, "exclude_possible_duplicates", True)
            exclude_cancelled.result(timeout=30.0)
            exclude_possible_duplicates.result(timeout=30.0)
    after = store.read_meta(dataset_id)
    assert after is not None
    assert after["policies"]["exclude_cancelled"] is False
    assert after["policies"]["exclude_possible_duplicates"] is True
    assert after["data_version"] == initial_version + 2
    response = upload_client.get(f"/api/datasets/{dataset_id}")
    assert response.status_code == 200, response.text
    policies = response.json()["schema"]["policies"]
    assert policies["exclude_cancelled"] is False
    assert policies["exclude_possible_duplicates"] is True


def test_repeat_within_90_days_note_defines_a_later_calendar_day(upload_client: TestClient) -> None:
    rows = ["order_id,order_date,customer_id,amount"]
    rows.extend(f"FIRST{index:03d},2024-01-01,C{index:03d},10.00" for index in range(60))
    rows.extend(("SAME-DAY,2024-01-01,C000,10.00", "REPEAT,2024-01-02,C001,10.00", "END,2024-04-02,C002,10.00"))
    dataset_id, _dashboard = ready_dashboard(upload_client, "repeat-calendar-day.csv", ("\n".join(rows) + "\n").encode("utf-8"))
    response = upload_client.get(f"/api/datasets/{dataset_id}/customers")
    assert response.status_code == 200, response.text
    customers = response.json()
    assert customers["available"] is True, customers
    repeat = customers["repeat_within_horizon"]
    assert repeat is not None
    assert "later calendar day" in repeat["note"].lower()
    assert repeat["horizon_days"] == 90
    assert repeat["eligible_customers"] == 60
    assert repeat["repeat_customers"] == 1
    assert repeat["rate"] == pytest.approx(1 / 60)


def test_cohort_retention_censors_the_partial_final_month(upload_client: TestClient) -> None:
    rows = ["order_id,order_date,customer_id,amount"]
    rows.extend(f"FIRST{index:03d},2024-01-{index % 30 + 1:02d},C{index:03d},10.00" for index in range(60))
    rows.extend(("MARCH,2024-03-10,C000,10.00", "APRIL,2024-04-02,C001,10.00"))
    dataset_id, _dashboard = ready_dashboard(upload_client, "partial-final-month.csv", ("\n".join(rows) + "\n").encode("utf-8"))
    response = upload_client.get(f"/api/datasets/{dataset_id}/customers")
    assert response.status_code == 200, response.text
    customers = response.json()
    assert customers["available"] is True, customers
    assert customers["customers"] == 60
    assert customers["reference_date"] == "2024-04-02"
    january = next(row for row in customers["cohorts"]["rows"] if row["cohort"] == "2024-01")
    assert january["size"] == 60
    assert january["retention_pct"][0] == pytest.approx(100.0)
    assert january["retention_pct"][1] == pytest.approx(0.0)
    assert january["retention_pct"][2] == pytest.approx(100 * 1 / 60)
    assert january["retention_pct"][3] is None


def test_empty_week_counts_as_zero_in_complete_period_comparisons(upload_client: TestClient) -> None:
    assert date(2024, 1, 1).isoweekday() == 1
    assert date(2024, 4, 1).isoweekday() == 1
    assert date(2024, 4, 8).isoweekday() == 1
    assert date(2024, 4, 17).isoweekday() == 3
    assert (date(2024, 4, 17) - date(2024, 1, 1)).days == 31 + 29 + 31 + 16
    content = b"""order_id,order_date,amount
START,2024-01-01,100.00
BEFORE,2024-03-25,50.00
COMPLETE,2024-04-10,300.00
PARTIAL,2024-04-17,900.00
"""
    _dataset_id, dashboard = ready_dashboard(upload_client, "empty-complete-week.csv", content)
    trend = dashboard["trend"]
    assert trend["available"] is True
    assert trend["granularity"] == "week"
    points = {point["period"]: point for point in trend["points"]}
    empty_week = points["2024-04-01"]
    assert empty_week["period_end"] == "2024-04-07"
    assert empty_week["revenue"] == pytest.approx(0.0)
    assert empty_week["orders"] == 0
    assert empty_week["is_partial"] is False
    complete_week = points["2024-04-08"]
    assert complete_week["period_end"] == "2024-04-14"
    assert complete_week["revenue"] == pytest.approx(300.00)
    assert complete_week["orders"] == 1
    assert complete_week["is_partial"] is False
    assert points["2024-04-15"]["is_partial"] is True
    comparison = trend["comparison"]
    assert comparison["available"] is True
    assert comparison["current_period"] == "2024-04-08"
    assert comparison["previous_period"] == "2024-04-01"
    assert comparison["revenue_change"] is None
    assert comparison["orders_change"] is None
