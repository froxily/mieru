from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scipy import stats

from run import run_pipeline
from src.analysis import METRICS_PATH, OUTPUT_DIR, load_metrics
from src.api import app
from src.plotting import FIGURE_FILENAMES
from src.warehouse import DATABASE_PATH, connect_read_only

MIN_FIGURE_BYTES: int = 30 * 1024
API_SMOKE_PATHS: tuple[str, ...] = (
    "/summary",
    "/cohorts?start_month=2017-01&end_month=2018-08",
    "/sla-simulator?delay_days=3&order_gmv=120.0&freight_ratio=0.15&distance_km=350.0",
)


def pipeline_artifacts_present() -> bool:
    return (
        DATABASE_PATH.exists()
        and METRICS_PATH.exists()
        and all((OUTPUT_DIR / file_name).exists() for file_name in FIGURE_FILENAMES)
    )


@pytest.fixture(scope="session")
def metrics() -> dict[str, Any]:
    if not pipeline_artifacts_present():
        run_pipeline()
    return load_metrics(METRICS_PATH)


@pytest.fixture(scope="session")
def api_client(metrics: dict[str, Any]) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def test_order_fulfillment_mart_has_one_row_per_delivered_order(metrics: dict[str, Any]) -> None:
    with connect_read_only() as connection:
        mart_rows, distinct_orders = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT order_id) FROM mart_order_fulfillment"
        ).fetchone()
        eligible_raw_orders = connection.execute(
            """
            SELECT COUNT(*) FROM raw_orders
            WHERE order_status = 'delivered'
              AND order_purchase_timestamp IS NOT NULL
              AND order_delivered_customer_date IS NOT NULL
              AND order_estimated_delivery_date IS NOT NULL
            """
        ).fetchone()[0]
    assert mart_rows == distinct_orders
    assert mart_rows == eligible_raw_orders
    assert mart_rows > 90_000


def test_sla_breached_reviews_are_significantly_lower(metrics: dict[str, Any]) -> None:
    with connect_read_only() as connection:
        reviews = connection.execute(
            "SELECT review_score, sla_delay_days FROM mart_order_fulfillment WHERE review_score IS NOT NULL"
        ).df()
    breached_scores = reviews.loc[reviews["sla_delay_days"] > 0, "review_score"]
    on_time_scores = reviews.loc[reviews["sla_delay_days"] <= 0, "review_score"]
    welch_test = stats.ttest_ind(breached_scores, on_time_scores, equal_var=False)
    review_summary = metrics["two_sample_tests"]["review_score"]
    assert breached_scores.mean() < on_time_scores.mean()
    assert welch_test.pvalue < 1e-10
    assert review_summary["sla_breached"]["mean"] < review_summary["on_time"]["mean"]
    assert review_summary["welch_p_value"] < 1e-10


def test_seller_gmv_gini_is_in_plausible_range(metrics: dict[str, Any]) -> None:
    assert 0.50 < metrics["seller_concentration"]["gini_coefficient"] < 0.95


@pytest.mark.parametrize("figure_name", FIGURE_FILENAMES)
def test_figures_exist_and_exceed_30kb(metrics: dict[str, Any], figure_name: str) -> None:
    figure_path = OUTPUT_DIR / figure_name
    assert figure_path.exists()
    assert figure_path.stat().st_size > MIN_FIGURE_BYTES


@pytest.mark.parametrize("path", API_SMOKE_PATHS)
def test_api_endpoints_return_200(api_client: TestClient, path: str) -> None:
    response = api_client.get(path)
    assert response.status_code == 200
    assert response.json()


def test_sla_simulator_is_sign_dependent_and_penalises_breach(api_client: TestClient) -> None:
    one_day_late = api_client.get("/sla-simulator", params={"delay_days": 1}).json()
    thirty_days_late = api_client.get("/sla-simulator", params={"delay_days": 30}).json()
    early = api_client.get("/sla-simulator", params={"delay_days": -5}).json()
    late_probability = one_day_late["scenario"]["predicted_severe_detractor_probability"]
    baseline_probability = one_day_late["on_time_baseline"]["predicted_severe_detractor_probability"]
    assert late_probability > baseline_probability
    assert late_probability == pytest.approx(thirty_days_late["scenario"]["predicted_severe_detractor_probability"])
    assert early["scenario"]["predicted_severe_detractor_probability"] == pytest.approx(baseline_probability)
    assert "SIGN" in one_day_late["model_note"]


def test_cohorts_endpoint_validates_month_range(api_client: TestClient) -> None:
    assert api_client.get("/cohorts", params={"start_month": "2018-08", "end_month": "2017-01"}).status_code == 422
    assert api_client.get("/cohorts", params={"start_month": "2017-13"}).status_code == 422


def test_cohort_period_zero_is_full_retention(metrics: dict[str, Any]) -> None:
    with connect_read_only() as connection:
        period_zero_rates = connection.execute(
            "SELECT DISTINCT retention_rate_pct FROM mart_cohort_retention WHERE period_number = 0"
        ).fetchall()
    assert period_zero_rates == [(100.0,)]


def test_review_csv_multiline_comments_parsed_without_row_splits(metrics: dict[str, Any]) -> None:
    with connect_read_only() as connection:
        review_rows = connection.execute("SELECT COUNT(*) FROM raw_order_reviews").fetchone()[0]
        malformed_rows = connection.execute(
            """
            SELECT COUNT(*) FROM raw_order_reviews
            WHERE NOT regexp_full_match(review_id, '[0-9a-f]{32}')
               OR NOT regexp_full_match(order_id, '[0-9a-f]{32}')
               OR review_score NOT BETWEEN 1 AND 5
               OR review_score IS NULL
            """
        ).fetchone()[0]
    parsing_check = metrics["data_integrity"]["review_csv_parsing_check"]
    assert parsing_check["python_csv_module_records"] == parsing_check["duckdb_records"] == review_rows
    assert malformed_rows == 0
