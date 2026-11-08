import io
import math
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mieru.config import Settings
from mieru.main import create_app
from tests.product.upload_helpers import MUTATION_HEADERS, explain, kpi, upload_and_wait, upload_bytes, wait_until_settled

LINE_ITEMS_WITH_REPEATED_TOTAL = b"""order_id,order_date,customer_id,product,category,quantity,unit_price,order_total
A1,2024-01-05,C1,Widget,Tools,2,10.00,35.00
A1,2024-01-05,C1,Gadget,Toys,1,15.00,35.00
A2,2024-01-20,C2,Widget,Tools,1,10.00,10.00
A3,2024-02-03,C1,Gizmo,Toys,3,5.00,15.00
"""

ORDER_TOTAL_ONLY = b"""invoice_no,date,sku,product_name,amount
INV-1,2024-03-01,S1,Alpha,100.00
INV-1,2024-03-01,S2,Beta,100.00
INV-2,2024-03-02,S1,Alpha,40.00
INV-3,2024-03-05,S3,Gamma,60.00
INV-3,2024-03-05,S1,Alpha,60.00
INV-3,2024-03-05,S2,Beta,60.00
"""

QUALITY_CASES = b"""transaction_id,order_id,timestamp,customer,item,qty,price,status
T1,O1,2024-05-01 10:00,U1,Pen,2,1.50,completed
T2,O1,2024-05-01 10:00,U1,Book,1,12.00,completed
T2,O1,2024-05-01 10:00,U1,Book,1,12.00,completed
T3,O2,2024-05-02 11:00,U2,Pen,5,1.50,cancelled
T4,O3,2024-05-03 12:00,U3,Lamp,1,30.00,completed
T5,O4,2024-05-04 09:30,U3,Lamp,-1,30.00,returned
,,,,,,,
T6,O5,2024-05-05 15:00,U4,Desk,1,abc,completed
"""

JAPANESE_CP932 = """注文番号,注文日,顧客ID,商品名,カテゴリ,数量,単価
1001,2024/04/01,K01,緑茶,飲料,2,"1,200"
1002,2024/04/02,K02,せんべい,菓子,1,450
1003,2024/04/02,K01,緑茶,飲料,1,"1,200"
""".encode("cp932")

EUROPEAN_SEMICOLON = """order_id;date;product;quantity;price
E1;31/01/2024;Chair;2;1.234,50
E2;15/02/2024;Table;1;899,99
E3;01/03/2024;Chair;1;1.234,50
""".encode("utf-8")

POSSIBLE_DUPLICATES = b"""date,product,amount
2024-06-01,Coffee,4.50
2024-06-01,Coffee,4.50
2024-06-02,Tea,3.00
"""

AMBIGUOUS_DATES = b"""order_id,date,amount
X1,01/02/2024,10
X2,03/04/2024,20
X3,05/06/2024,30
"""

MULTI_CURRENCY = b"""order_id,date,amount,currency
M1,2024-01-01,100,USD
M2,2024-01-02,200,EUR
"""


@pytest.fixture(scope="module")
def upload_app(test_settings: Settings) -> FastAPI:
    return create_app(
        test_settings.with_overrides(
            data_dir=test_settings.data_dir.parent / f"{test_settings.data_dir.name}-uploads",
            max_datasets_per_session=500,
            uploads_per_ip_per_hour=5000,
            max_upload_bytes=2 * 1024 * 1024,
        )
    )


@pytest.fixture(scope="module")
def upload_client(upload_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(upload_app) as client:
        yield client


def ready_dashboard(client: TestClient, file_name: str, content: bytes) -> tuple[str, dict]:
    status = upload_and_wait(client, file_name, content)
    assert status["dataset"]["status"] == "ready", status["dataset"].get("error")
    dataset_id = status["dataset"]["dataset_id"]
    dashboard = client.get(f"/api/datasets/{dataset_id}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    return dataset_id, dashboard.json()


def test_line_items_with_repeated_order_total_are_not_double_counted(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "orders.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
    assert dashboard["dataset"]["grain"] == "line"
    assert dashboard["dataset"]["revenue_basis"] == "quantity_x_unit_price"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(60.0)
    assert kpi(dashboard, "orders")["value"] == 3
    assert kpi(dashboard, "customers")["value"] == 2
    assert kpi(dashboard, "units")["value"] == 7
    assert kpi(dashboard, "aov")["value"] == pytest.approx(20.0)
    category_total = sum(row["revenue"] for row in dashboard["breakdowns"]["categories"]["rows"])
    assert category_total == pytest.approx(60.0)
    trend_total = sum(point["revenue"] for point in dashboard["trend"]["points"])
    assert trend_total == pytest.approx(60.0)
    explanation = explain(upload_client, dataset_id, "net_revenue")
    assert explanation["value"] == pytest.approx(60.0)
    assert explanation["record_counts"]["is_consistent"] is True


def test_order_total_repeated_on_lines_is_counted_once_per_order(upload_client: TestClient) -> None:
    _dataset_id, dashboard = ready_dashboard(upload_client, "invoices.csv", ORDER_TOTAL_ONLY)
    assert dashboard["dataset"]["grain"] == "line"
    assert dashboard["dataset"]["revenue_basis"] == "order_total"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(200.0)
    assert kpi(dashboard, "orders")["value"] == 3
    assert kpi(dashboard, "aov")["value"] == pytest.approx(200.0 / 3)
    assert dashboard["breakdowns"]["products"]["revenue_shown"] is False


def test_quality_policies_exclusions_and_sign_semantics(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "transactions.csv", QUALITY_CASES)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(15.0)
    assert kpi(dashboard, "returns_value")["value"] == pytest.approx(30.0)
    assert kpi(dashboard, "orders")["value"] == 3
    assert kpi(dashboard, "customers")["value"] == 3
    assert kpi(dashboard, "units")["value"] == 5
    assert kpi(dashboard, "aov")["value"] == pytest.approx(7.5)
    revenue = explain(upload_client, dataset_id, "net_revenue")
    counts = revenue["record_counts"]
    excluded = {item["reason"]: item["records"] for item in counts["excluded"]}
    assert counts["input_records"] == 8
    assert counts["contributing_records"] == 4
    assert excluded == {"blank_row": 1, "duplicate_reliable": 1, "cancelled": 1, "invalid_amount": 1}
    assert counts["input_records"] == counts["contributing_records"] + sum(excluded.values())
    quality = upload_client.get(f"/api/datasets/{dataset_id}/quality").json()
    impact = {row["metric_id"]: row for row in quality["impact"]}
    assert impact["net_revenue"]["without_policies"] == pytest.approx(34.5)
    assert impact["net_revenue"]["with_policies"] == pytest.approx(15.0)
    issue_codes = {issue["code"] for issue in quality["issues"]}
    assert {"is_blank", "dup_reliable", "is_cancelled", "value_invalid", "is_return"} <= issue_codes
    response = upload_client.put(f"/api/datasets/{dataset_id}/policies", json={"policies": {"exclude_cancelled": False}}, headers=MUTATION_HEADERS)
    assert response.status_code == 200
    toggled = upload_client.get(f"/api/datasets/{dataset_id}/dashboard").json()
    assert kpi(toggled, "net_revenue")["value"] == pytest.approx(22.5)
    upload_client.put(f"/api/datasets/{dataset_id}/policies", json={"policies": {"exclude_cancelled": True}}, headers=MUTATION_HEADERS)
    restored = upload_client.get(f"/api/datasets/{dataset_id}/dashboard").json()
    assert kpi(restored, "net_revenue")["value"] == pytest.approx(15.0)


def test_possible_duplicates_are_kept_by_default_and_reversible(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "cafe.csv", POSSIBLE_DUPLICATES)
    assert dashboard["dataset"]["grain"] == "transaction"
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(12.0)
    assert kpi(dashboard, "orders")["value"] == 3
    upload_client.put(f"/api/datasets/{dataset_id}/policies", json={"policies": {"exclude_possible_duplicates": True}}, headers=MUTATION_HEADERS)
    deduplicated = upload_client.get(f"/api/datasets/{dataset_id}/dashboard").json()
    assert kpi(deduplicated, "net_revenue")["value"] == pytest.approx(7.5)
    upload_client.put(f"/api/datasets/{dataset_id}/policies", json={"policies": {"exclude_possible_duplicates": False}}, headers=MUTATION_HEADERS)
    assert kpi(upload_client.get(f"/api/datasets/{dataset_id}/dashboard").json(), "net_revenue")["value"] == pytest.approx(12.0)


def test_japanese_cp932_file_is_decoded_and_mapped(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "売上.csv", JAPANESE_CP932)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(4050.0)
    assert kpi(dashboard, "orders")["value"] == 3
    assert kpi(dashboard, "customers")["value"] == 2
    assert kpi(dashboard, "units")["value"] == 4
    schema = upload_client.get(f"/api/datasets/{dataset_id}").json()["schema"]
    assert schema["source"]["encoding"] in {"cp932", "shift_jis", "shift_jis_2004", "shift_jisx0213"}
    assert schema["role_columns"]["category"] == "カテゴリ"


def test_european_number_and_day_first_date_conventions(upload_client: TestClient) -> None:
    _dataset_id, dashboard = ready_dashboard(upload_client, "eu.csv", EUROPEAN_SEMICOLON)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(4603.49)
    assert dashboard["trend"]["available"] is True
    assert dashboard["trend"]["first_date"] == "2024-01-31"


def test_ambiguous_day_month_dates_disable_trends_with_explanation(upload_client: TestClient) -> None:
    _dataset_id, dashboard = ready_dashboard(upload_client, "ambiguous.csv", AMBIGUOUS_DATES)
    assert dashboard["trend"]["available"] is False
    assert any(item["kind"] == "ambiguous_date_format" for item in dashboard["clarifications"])
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(60.0)


def test_multiple_currencies_disable_revenue_totals(upload_client: TestClient) -> None:
    _dataset_id, dashboard = ready_dashboard(upload_client, "fx.csv", MULTI_CURRENCY)
    revenue = kpi(dashboard, "net_revenue")
    assert revenue["status"] == "unavailable"
    assert "currencies" in revenue["unavailable_reason"]


def test_xlsx_with_title_rows_and_several_sheets(upload_client: TestClient) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    notes = workbook.active
    notes.title = "Notes"
    notes["A1"] = "Exported from the shop system"
    sales = workbook.create_sheet("Sales")
    sales.append(["Monthly sales export"])
    sales.append([])
    sales.append(["Order ID", "Order Date", "Product", "Qty", "Unit Price"])
    sales.append(["S-1", "2024-07-01", "Bag", 2, 25.0])
    sales.append(["S-2", "2024-07-02", "Hat", 1, 15.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    dataset_id, dashboard = ready_dashboard(upload_client, "export.xlsx", buffer.getvalue())
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(65.5)
    schema = upload_client.get(f"/api/datasets/{dataset_id}").json()["schema"]
    assert schema["source"]["sheet_name"] == "Sales"
    assert schema["source"]["skipped_leading_rows"] == 2


@pytest.mark.parametrize(
    ("file_name", "content", "status"),
    [
        ("data.xls", b"anything", 415),
        ("macro.xlsm", b"PK\x03\x04", 415),
        ("data.pdf", b"%PDF-1.4", 415),
        ("fake.xlsx", b"order_id,amount\n1,2\n", 422),
        ("empty.csv", b"", 422),
        ("binary.csv", b"\x00\x01\x02\x03" * 100, 422),
    ],
)
def test_invalid_files_are_rejected_gracefully(upload_client: TestClient, file_name: str, content: bytes, status: int) -> None:
    response = upload_bytes(upload_client, file_name, content)
    assert response.status_code == status
    assert response.json()["detail"]


def test_header_only_file_fails_with_explanation(upload_client: TestClient) -> None:
    result = upload_and_wait(upload_client, "header.csv", b"order_id,amount\n")
    assert result["dataset"]["status"] == "failed"
    assert "no data rows" in result["dataset"]["error"]


def test_oversize_upload_is_rejected(upload_client: TestClient) -> None:
    content = b"order_id,amount\n" + b"1,2\n" * (3 * 1024 * 1024 // 4)
    assert upload_bytes(upload_client, "big.csv", content).status_code == 413


def test_mutations_require_csrf_header(upload_client: TestClient) -> None:
    response = upload_client.post("/api/datasets", files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")})
    assert response.status_code == 403


def test_datasets_are_isolated_between_sessions(upload_app: FastAPI, upload_client: TestClient) -> None:
    owner, stranger = TestClient(upload_app), TestClient(upload_app)
    if True:
        status = upload_and_wait(owner, "private.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
        dataset_id = status["dataset"]["dataset_id"]
        assert owner.get(f"/api/datasets/{dataset_id}/dashboard").status_code == 200
        for path in ("", "/dashboard", "/quality", "/metrics/net_revenue/explain"):
            assert stranger.get(f"/api/datasets/{dataset_id}{path}").status_code == 404
        assert stranger.put(f"/api/datasets/{dataset_id}/policies", json={"policies": {}}, headers=MUTATION_HEADERS).status_code == 404
        assert stranger.delete(f"/api/datasets/{dataset_id}", headers=MUTATION_HEADERS).status_code == 404
        assert all(item["dataset_id"] != dataset_id for item in stranger.get("/api/datasets").json()["datasets"])
        forged = TestClient(upload_app, cookies={"mieru_session": "forged-token.invalid-signature"})
        assert forged.get(f"/api/datasets/{dataset_id}").status_code == 404
        assert owner.get(f"/api/datasets/{dataset_id}").status_code == 200


def test_expired_datasets_are_hidden_and_cleanup_is_scoped(upload_app: FastAPI, upload_client: TestClient) -> None:
    import datetime as dt

    store = upload_app.state.dataset_store
    client = TestClient(upload_app)
    if True:
        status = upload_and_wait(client, "soon-expired.csv", POSSIBLE_DUPLICATES)
        dataset_id = status["dataset"]["dataset_id"]
        unrelated = store.root / "not-a-dataset"
        unrelated.mkdir(exist_ok=True)
        (unrelated / "keep.txt").write_text("must survive cleanup", encoding="utf-8")
        unmarked = store.root / ("f" * 32)
        unmarked.mkdir(exist_ok=True)
        (unmarked / "keep.txt").write_text("no marker, must survive", encoding="utf-8")
        store.update_meta(dataset_id, expires_at=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat())
        assert client.get(f"/api/datasets/{dataset_id}").status_code == 404
        removed = store.cleanup_expired()
        assert removed >= 1
        assert not (store.root / dataset_id).exists()
        assert (unrelated / "keep.txt").exists()
        assert (unmarked / "keep.txt").exists()


def test_every_metric_explanation_reconciles_for_quality_fixture(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "transactions-again.csv", QUALITY_CASES)
    metrics = upload_client.get(f"/api/datasets/{dataset_id}/metrics").json()["metrics"]
    for metric in metrics:
        explanation = explain(upload_client, dataset_id, metric["metric_id"])
        if not metric["available"]:
            assert explanation["status"] == "unavailable"
            continue
        counts = explanation["record_counts"]
        assert counts["is_consistent"], metric["metric_id"]
        dashboard_kpi = next((item for item in dashboard["kpis"] if item["metric_id"] == metric["metric_id"]), None)
        if dashboard_kpi is not None and dashboard_kpi["value"] is not None:
            assert math.isclose(dashboard_kpi["value"], explanation["value"], rel_tol=1e-12)


def test_mapping_override_reprocesses_dataset(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "remap.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
    assert kpi(dashboard, "customers")["value"] == 2
    response = upload_client.put(f"/api/datasets/{dataset_id}/mapping", json={"mapping": {"customer_id": None}}, headers=MUTATION_HEADERS)
    assert response.status_code == 202
    settled = wait_until_settled(upload_client, dataset_id)
    assert settled["dataset"]["status"] == "ready"
    remapped = upload_client.get(f"/api/datasets/{dataset_id}/dashboard").json()
    assert kpi(remapped, "customers")["status"] == "unavailable"
    assert kpi(remapped, "net_revenue")["value"] == pytest.approx(60.0)


def test_deadline_like_dates_are_not_mistaken_for_order_dates(upload_client: TestClient) -> None:
    content = b"order_id,shipping_limit_date,price\nA,2024-01-02 10:00:00,10\nB,2024-01-03 11:00:00,20\n"
    dataset_id, dashboard = ready_dashboard(upload_client, "items.csv", content)
    assert dashboard["trend"]["available"] is False
    schema = upload_client.get(f"/api/datasets/{dataset_id}").json()["schema"]
    assert "order_date" not in schema["role_columns"]


def build_returns_fixture() -> bytes:
    lines = ["order_id,order_date,customer_id,category,quantity,unit_price"]
    plan = {"Apparel": (100, 20), "Books": (100, 2), "Garden": (100, 3)}
    counter = 0
    for category, (sales, returns) in plan.items():
        for index in range(sales):
            counter += 1
            lines.append(f"S{counter},2024-03-{(index % 28) + 1:02d},C{counter % 70},{category},1,10.00")
        for index in range(returns):
            counter += 1
            lines.append(f"R{counter},2024-03-{(index % 28) + 1:02d},C{counter % 70},{category},-1,10.00")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_insights_fire_only_when_evidence_gates_pass(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "returns.csv", build_returns_fixture())
    insights = upload_client.get(f"/api/datasets/{dataset_id}/insights").json()
    cards = {card["insight_id"]: card for card in insights["cards"]}
    assert "category_returns" in cards
    returns_card = cards["category_returns"]
    assert "'Apparel'" in returns_card["finding"]
    rate = next(item["value"] for item in returns_card["evidence"] if item["label"] == "Returned lines ÷ sales lines")
    assert rate == pytest.approx(20 / 100)
    for card in insights["cards"]:
        assert card["finding"] and card["interpretation"] and card["action"] and card["limitations"]
    skipped = {item["rule"]: item["reason"] for item in insights["skipped"]}
    assert "product_concentration" in skipped
    small_id, _ = ready_dashboard(upload_client, "small.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
    small = upload_client.get(f"/api/datasets/{small_id}/insights").json()
    assert small["cards"] == [] or all(card["insight_id"] != "customer_concentration" for card in small["cards"])
    assert any(item["rule"] == "customer_concentration" and "Fewer than" in item["reason"] for item in small["skipped"])


HOSTILE_TEXT = b"""order_id,order_date,product,category,quantity,unit_price
H1,2024-08-01,=HYPERLINK("http://evil.example"),Tools,1,10.00
H2,2024-08-02,<script>alert(1)</script>,Toys,2,5.00
H3,2024-08-03,@SUM(A1:A2),Tools,1,7.50
"""


def test_cleaned_and_annotated_csv_exports_reconcile(upload_client: TestClient) -> None:
    import csv as csv_module

    dataset_id, dashboard = ready_dashboard(upload_client, "export-me.csv", QUALITY_CASES)
    cleaned = upload_client.get(f"/api/datasets/{dataset_id}/export/cleaned.csv")
    assert cleaned.status_code == 200
    assert "attachment" in cleaned.headers["content-disposition"]
    text = cleaned.content.decode("utf-8-sig")
    rows = list(csv_module.DictReader(io.StringIO(text)))
    assert len(rows) == 4
    assert {"transaction_id", "mieru_exclusion_reason", "mieru_net_value"} <= set(rows[0])
    assert sum(float(row["mieru_net_value"]) for row in rows) == pytest.approx(kpi(dashboard, "net_revenue")["value"])
    annotated = list(csv_module.DictReader(io.StringIO(upload_client.get(f"/api/datasets/{dataset_id}/export/annotated.csv").content.decode("utf-8-sig"))))
    assert len(annotated) == 8
    assert sum(1 for row in annotated if row["mieru_status"] == "excluded") == 4
    assert any(row["mieru_exclusion_reason"] == "Cancelled orders" for row in annotated)


def test_exports_neutralize_formulas_and_escape_html(upload_client: TestClient) -> None:
    from openpyxl import load_workbook

    dataset_id, _dashboard = ready_dashboard(upload_client, "hostile.csv", HOSTILE_TEXT)
    text = upload_client.get(f"/api/datasets/{dataset_id}/export/cleaned.csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "'@SUM" in text
    workbook = load_workbook(io.BytesIO(upload_client.get(f"/api/datasets/{dataset_id}/export/workbook.xlsx").content))
    assert {"Summary", "Cleaned data", "Quality issues", "Exclusions", "KPI impact", "Audit trail", "Column profiles", "Insights"} <= set(workbook.sheetnames)
    data = workbook["Cleaned data"]
    cell_values = [cell.value for row in data.iter_rows() for cell in row]
    assert any(isinstance(value, str) and value.startswith("'=HYPERLINK") for value in cell_values)
    assert all(cell.data_type != "f" for row in data.iter_rows() for cell in row)
    report = upload_client.get(f"/api/datasets/{dataset_id}/export/report.html").text
    assert "<script>alert(1)</script>" not in report
    markdown = upload_client.get(f"/api/datasets/{dataset_id}/export/report.md")
    assert markdown.status_code == 200 and markdown.text.startswith("# MIERU report")
    assert upload_client.get(f"/api/datasets/{dataset_id}/export/secrets.txt").status_code == 404


def test_exports_respect_active_filters(upload_client: TestClient) -> None:
    import csv as csv_module

    dataset_id, _dashboard = ready_dashboard(upload_client, "filtered.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
    response = upload_client.get(f"/api/datasets/{dataset_id}/export/cleaned.csv", params={"category": "Toys"})
    rows = list(csv_module.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert {row["category"] for row in rows} == {"Toys"}
    assert sum(float(row["mieru_net_value"]) for row in rows) == pytest.approx(30.0)


def test_dataset_forecast_endpoint_gates_short_history(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "short-history.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
    forecast = upload_client.get(f"/api/datasets/{dataset_id}/forecast").json()
    assert forecast["available"] is False
    assert forecast["reason"]


def test_dataset_forecast_runs_on_sample_file(upload_client: TestClient) -> None:
    from pathlib import Path

    sample = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "mieru-sample-retail-orders-synthetic.csv"
    dataset_id, _dashboard = ready_dashboard(upload_client, "sample.csv", sample.read_bytes())
    forecast = upload_client.get(f"/api/datasets/{dataset_id}/forecast").json()
    assert forecast["available"] is True
    assert forecast["granularity"] == "month"
    assert len(forecast["forecast"]) == 6
    assert forecast["measure"] == "Net revenue"


def build_customer_fixture() -> bytes:
    import datetime as dt

    lines = ["order_id,order_date,customer_id,quantity,unit_price,status"]
    start = dt.date(2024, 1, 1)
    for index in range(120):
        customer = f"C{index % 60:03d}"
        day = start + dt.timedelta(days=(index * 3) % 200)
        lines.append(f"O{index:04d},{day.isoformat()},{customer},1,{10 + index % 7}.00,completed")
    lines.append("O9001,2024-03-01,C000,-1,10.00,returned")
    lines.append("O9002,,C001,1,77.00,completed")
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_customer_intelligence_reconciles_to_net_revenue(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "customers.csv", build_customer_fixture())
    payload = upload_client.get(f"/api/datasets/{dataset_id}/customers").json()
    assert payload["available"] is True
    assert payload["customers"] == 60
    assert sum(segment["customers"] for segment in payload["segments"]) == 60
    reconciliation = payload["reconciliation"]
    assert reconciliation["dashboard_total"] == pytest.approx(kpi(dashboard, "net_revenue")["value"])
    assert reconciliation["difference"] == pytest.approx(77.0)
    assert payload["cohorts"]["rows"][0]["retention_pct"][0] == pytest.approx(100.0)
    repeat = payload["repeat_within_horizon"]
    assert repeat is None or (repeat["eligible_customers"] >= 50 and 0 <= repeat["rate"] <= 1)


def test_customer_intelligence_requires_enough_customers(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "few-customers.csv", LINE_ITEMS_WITH_REPEATED_TOTAL)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/customers").json()
    assert payload["available"] is False
    assert "at least 50" in payload["reason"]


PERFORMANCE_FIXTURE = b"""order_id,order_date,customer_id,product,category,channel,quantity,unit_price,discount,unit_cost,status
P1,2024-01-03,C1,Alpha,Tools,web,2,50.00,10.00,20.00,completed
P1,2024-01-03,C1,Beta,Toys,web,1,30.00,0.00,10.00,completed
P2,2024-01-10,C2,Alpha,Tools,store,1,50.00,0.00,20.00,completed
P3,2024-01-15,C3,Gamma,Toys,store,4,10.00,4.00,6.00,completed
P4,2024-02-01,C2,Alpha,Tools,web,1,50.00,0.00,20.00,returned
P5,2024-02-05,C4,Delta,Garden,web,1,200.00,0.00,250.00,completed
P6,2024-02-07,C5,Beta,Toys,store,2,30.00,6.00,10.00,completed
P7,2024-02-09,C1,Alpha,Tools,web,1,50.00,0.00,20.00,cancelled
P8,2024-02-10,C6,Epsilon,Garden,store,1,20.00,0.00,8.00,completed
"""


def group(payload: dict, section: str, dimension: str, label: str) -> dict:
    return next(row for row in payload[section]["groups"][dimension]["rows"] if row["label"] == label)


def test_revenue_bridge_reconciles_to_dashboard_kpis(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "performance.csv", PERFORMANCE_FIXTURE)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/performance").json()
    bridge = payload["bridge"]
    assert bridge["available"] is True and bridge["reconciles"] is True
    assert [(step["label"], step["value"]) for step in bridge["steps"]] == [
        ("Gross sales", pytest.approx(100 + 30 + 50 + 40 + 200 + 60 + 20)),
        ("Discounts", pytest.approx(-(10 + 4 + 6))),
        ("Returns & credits", pytest.approx(-50)),
        ("Net revenue", pytest.approx(430)),
        ("Cost of goods", pytest.approx(-(40 + 10 + 20 + 24 - 20 + 250 + 20 + 8))),
        ("Gross profit", pytest.approx(430 - 352)),
    ]
    for step in (step for step in bridge["steps"] if step["metric_id"]):
        magnitude = -step["value"] if step["kind"] == "decrease" else step["value"]
        assert explain(upload_client, dataset_id, step["metric_id"])["value"] == pytest.approx(magnitude)
    assert kpi(dashboard, "net_revenue")["value"] == pytest.approx(bridge["net_revenue"])


def test_returned_items_reverse_their_cost(upload_client: TestClient) -> None:
    dataset_id, dashboard = ready_dashboard(upload_client, "performance-profit.csv", PERFORMANCE_FIXTURE)
    assert kpi(dashboard, "gross_profit")["value"] == pytest.approx(78.0)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/performance").json()
    profitability = payload["profitability"]
    assert profitability["gross_profit"] == pytest.approx(78.0)
    assert profitability["margin"] == pytest.approx(78 / 430)
    assert profitability["cost_coverage"]["rows_with_cost"] == profitability["cost_coverage"]["contributing_rows"] == 8
    tools = group(payload, "profitability", "categories", "Tools")
    assert (tools["revenue"], tools["cost"], tools["gross_profit"]) == (pytest.approx(90), pytest.approx(40), pytest.approx(50))
    garden = group(payload, "profitability", "categories", "Garden")
    assert garden["gross_profit"] == pytest.approx(-38) and garden["margin"] == pytest.approx(-38 / 220)
    assert profitability["groups"]["categories"]["lowest_margin"][0]["label"] == "Garden"
    assert profitability["groups"]["categories"]["loss_making_groups"] == 1


def test_returns_and_discounts_by_group(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "performance-returns.csv", PERFORMANCE_FIXTURE)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/performance").json()
    returns = payload["returns"]
    assert returns["return_rate"] == pytest.approx(50 / (500 - 20))
    tools = group(payload, "returns", "categories", "Tools")
    assert (tools["gross_sales"], tools["net_sales"], tools["returns_value"]) == (pytest.approx(150), pytest.approx(90 + 50), pytest.approx(50))
    assert tools["return_rate"] == pytest.approx(50 / 140)
    assert tools["small_sample"] is True
    discounts = payload["discounts"]
    assert discounts["treatment"] == "deducted"
    assert discounts["discount_value"] == pytest.approx(20) and discounts["list_value"] == pytest.approx(500)
    assert discounts["discount_rate"] == pytest.approx(0.04)
    assert discounts["discounted_rows"] == 3 and discounts["sale_rows"] == 7
    assert group(payload, "discounts", "categories", "Toys")["discount_rate"] == pytest.approx(10 / 130)
    split = discounts["margin_split"]
    assert split["discounted"]["margin"] == pytest.approx(96 / 180)
    assert split["full_price"]["margin"] == pytest.approx(12 / 300)


def test_concentration_curves_and_gini(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "performance-concentration.csv", PERFORMANCE_FIXTURE)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/performance").json()
    products = payload["concentration"]["products"]
    assert products["items"] == 5 and products["excluded_non_positive"] == 0
    assert products["top_20pct_share"] == pytest.approx(200 / 430)
    assert products["items_for_50pct"] == 2 and products["items_for_80pct"] == 3
    ascending = [20, 36, 84, 90, 200]
    expected_gini = 2 * sum((rank + 1) * value for rank, value in enumerate(ascending)) / (len(ascending) * sum(ascending)) - (len(ascending) + 1) / len(ascending)
    assert products["gini"] == pytest.approx(expected_gini)
    assert products["curve"][-1]["revenue_share"] == pytest.approx(1.0)
    assert products["top_items"][0]["label"] == "Delta"
    customers = payload["concentration"]["customers"]
    assert customers["items"] == 5 and customers["excluded_non_positive"] == 1
    assert customers["items_for_80pct"] == 3
    assert customers.get("top_items") is None


def test_performance_respects_filters(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "performance-filters.csv", PERFORMANCE_FIXTURE)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/performance", params={"channel": "web"}).json()
    bridge = payload["bridge"]
    assert bridge["gross_sales"] == pytest.approx(100 + 30 + 200)
    assert bridge["net_revenue"] == pytest.approx(90 + 30 - 50 + 200)
    assert payload["filters"]["channels"] == ["web"]
    filtered_dashboard = upload_client.get(f"/api/datasets/{dataset_id}/dashboard", params={"channel": "web"}).json()
    assert kpi(filtered_dashboard, "net_revenue")["value"] == pytest.approx(bridge["net_revenue"])


def test_performance_sections_explain_order_total_files(upload_client: TestClient) -> None:
    dataset_id, _dashboard = ready_dashboard(upload_client, "performance-order-total.csv", ORDER_TOTAL_ONLY)
    payload = upload_client.get(f"/api/datasets/{dataset_id}/performance").json()
    assert payload["bridge"]["available"] is False and "order totals" in payload["bridge"]["reason"]
    assert payload["profitability"]["available"] is False
    assert payload["concentration"]["products"]["available"] is False


def test_workbook_and_report_include_performance_tables(upload_client: TestClient) -> None:
    from openpyxl import load_workbook

    dataset_id, _dashboard = ready_dashboard(upload_client, "performance-export.csv", PERFORMANCE_FIXTURE)
    response = upload_client.get(f"/api/datasets/{dataset_id}/export/workbook.xlsx")
    assert response.status_code == 200, response.text
    workbook = load_workbook(io.BytesIO(response.content), read_only=True)
    assert {"Breakdowns", "Revenue bridge", "Profitability", "Returns", "Discounts", "Concentration"} <= set(workbook.sheetnames)
    bridge_rows = {row[0]: row[1] for row in workbook["Revenue bridge"].iter_rows(min_row=2, values_only=True) if len(row) > 1 and row[0] and row[1] is not None}
    assert bridge_rows["Net revenue"] == pytest.approx(430) and bridge_rows["Gross profit"] == pytest.approx(78)
    workbook.close()
    report = upload_client.get(f"/api/datasets/{dataset_id}/export/report.md").text
    assert "## Revenue & profit" in report and "| Gross profit |" in report
