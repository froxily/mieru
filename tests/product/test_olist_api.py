import json
import math

import pytest
from fastapi.testclient import TestClient

from mieru.config import ConfigurationError, load_settings
from mieru.olist.metrics import OLIST_METRICS
from src.analysis import METRICS_PATH


@pytest.fixture(scope="module")
def research() -> dict:
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))


def kpi_value(payload: dict, metric_id: str) -> float:
    return next(item["value"] for item in payload["kpis"] if item["metric_id"] == metric_id)


def test_health_reports_ready_demo(client: TestClient) -> None:
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["product"] == "MIERU"
    assert payload["olist_demo"] == "ready"


def test_overview_kpis_equal_research_pipeline(client: TestClient, research: dict) -> None:
    overview = client.get("/api/olist/overview").json()
    platform = research["platform_kpis"]
    assert math.isclose(kpi_value(overview, "olist.gmv"), platform["total_gmv_brl"], rel_tol=1e-12)
    assert kpi_value(overview, "olist.delivered_orders") == platform["delivered_orders"]
    assert kpi_value(overview, "olist.customers") == platform["unique_customers"]
    assert math.isclose(kpi_value(overview, "olist.aov"), platform["average_order_value_brl"], rel_tol=1e-9)
    assert math.isclose(100 * kpi_value(overview, "olist.sla_breach_rate"), platform["sla_breach_rate_pct"], rel_tol=1e-12)
    assert math.isclose(100 * kpi_value(overview, "olist.repeat_purchase_rate"), platform["customer_repeat_purchase_rate_pct"], rel_tol=1e-12)
    assert math.isclose(kpi_value(overview, "olist.mean_review_score"), platform["mean_review_score"], rel_tol=1e-12)


def test_dashboard_breakdowns_reconcile_to_platform_gmv(client: TestClient, research: dict) -> None:
    overview = client.get("/api/olist/overview").json()
    platform_gmv = research["platform_kpis"]["total_gmv_brl"]
    category_gmv = sum(item["gmv"] for item in overview["categories"]["top"]) + overview["categories"]["remainder"]["gmv"]
    assert math.isclose(category_gmv, platform_gmv, rel_tol=1e-9)
    assert math.isclose(sum(item["gmv"] for item in overview["states"]), platform_gmv, rel_tol=1e-9)
    assert math.isclose(sum(item["gmv"] for item in overview["monthly"]), platform_gmv, rel_tol=1e-9)
    assert sum(item["delivered_orders"] for item in overview["monthly"]) == research["platform_kpis"]["delivered_orders"]
    partial_months = [item["month"] for item in overview["monthly"] if item["is_partial"]]
    assert "2018-08" in partial_months
    assert all(month.startswith("2016") for month in partial_months if month != "2018-08")


@pytest.mark.parametrize("metric", OLIST_METRICS, ids=lambda metric: metric.definition.metric_id)
def test_every_olist_metric_explanation_is_internally_consistent(client: TestClient, metric) -> None:
    explanation = client.get(f"/api/metrics/olist/{metric.definition.metric_id}/explain").json()
    if metric.unavailable_reason:
        assert explanation["status"] == "unavailable"
        assert explanation["value"] is None
        assert explanation["unavailable_reason"]
        return
    counts = explanation["record_counts"]
    assert explanation["status"] == "ok"
    assert explanation["value"] is not None
    assert counts["input_records"] == counts["contributing_records"] + counts["excluded_total"]
    assert counts["is_consistent"] is True
    assert explanation["sql"]
    funnel = explanation["context"]["upstream_funnel"]
    assert funnel["raw_orders"] == funnel["excluded_not_delivered"] + funnel["excluded_delivered_missing_dates"] + funnel["delivered_orders_in_mart"]


def test_debugger_value_matches_dashboard_value(client: TestClient) -> None:
    overview = client.get("/api/olist/overview").json()
    for item in overview["kpis"]:
        explanation = client.get(f"/api/metrics/olist/{item['metric_id']}/explain").json()
        assert explanation["value"] == item["value"]


def test_seller_gini_matches_research(client: TestClient, research: dict) -> None:
    sellers = client.get("/api/olist/sellers").json()
    assert math.isclose(kpi_value(sellers, "olist.seller_gmv_gini"), research["seller_concentration"]["gini_coefficient"], rel_tol=1e-12)
    assert math.isclose(
        kpi_value(sellers, "olist.seller_share_for_80pct_gmv") * 100,
        research["seller_concentration"]["sellers_for_80pct_gmv"]["seller_share_pct"],
        rel_tol=1e-12,
    )
    assert sellers["lorenz"]["seller_share"][0] == 0.0 and math.isclose(sellers["lorenz"]["gmv_share"][-1], 1.0)


@pytest.mark.parametrize("path", ["/summary", "/cohorts?start_month=2017-01&end_month=2018-08", "/sla-simulator?delay_days=3"])
def test_legacy_research_api_is_mounted_unchanged(client: TestClient, path: str) -> None:
    from src.api import app as legacy_app

    with TestClient(legacy_app) as legacy_client:
        assert client.get(f"/api/olist/research{path}").json() == legacy_client.get(path).json()


def test_figures_are_whitelisted(client: TestClient) -> None:
    assert client.get("/api/olist/figures/01_cohort_retention_heatmap.png").status_code == 200
    assert client.get("/api/olist/figures/metrics_summary.json").status_code == 404
    assert client.get("/api/olist/figures/..%2F..%2Frun.py").status_code == 404


def test_security_headers_and_spa_fallback(client: TestClient) -> None:
    page = client.get("/dashboard/olist")
    assert page.status_code == 200
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    api = client.get("/api/health")
    assert api.headers["cache-control"] == "no-store"
    assert client.get("/api/does-not-exist").status_code == 404


def test_production_requires_persistent_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIERU_ENV", "production")
    monkeypatch.delenv("MIERU_SESSION_SECRET", raising=False)
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("MIERU_SESSION_SECRET", "too-short")
    with pytest.raises(ConfigurationError):
        load_settings()
    monkeypatch.setenv("MIERU_SESSION_SECRET", "x" * 48)
    settings = load_settings()
    assert settings.secure_cookies is True
    assert settings.session_secret == ("x" * 48).encode()


def test_production_trusts_forwarded_headers_only_from_private_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIERU_ENV", "production")
    monkeypatch.setenv("MIERU_SESSION_SECRET", "x" * 48)
    monkeypatch.delenv("MIERU_FORWARDED_ALLOW_IPS", raising=False)
    trusted = load_settings().forwarded_allow_ips
    assert trusted is not None and "*" not in trusted
    assert "10.0.0.0/8" in trusted and "100.64.0.0/10" in trusted
    monkeypatch.setenv("MIERU_FORWARDED_ALLOW_IPS", "10.1.2.3")
    assert load_settings().forwarded_allow_ips == "10.1.2.3"
    monkeypatch.setenv("MIERU_ENV", "development")
    assert load_settings().forwarded_allow_ips is None


def test_olist_insights_are_evidence_backed_and_match_research(client: TestClient, research: dict) -> None:
    insights = client.get("/api/olist/insights").json()
    cards = {card["insight_id"]: card for card in insights["cards"]}
    assert {"sla_breach_detractors", "promise_cliff", "seller_concentration", "retention_structural"} <= set(cards)
    breach = cards["sla_breach_detractors"]
    odds_ratio = next(item["value"] for item in breach["evidence"] if item["label"].startswith("Adjusted odds ratio"))
    expected = next(term["odds_ratio"] for term in research["logistic_models"]["model_1_severe_detractor"]["terms"] if term["term"] == "is_sla_breached")
    assert odds_ratio == expected
    assert any("not a randomised causal estimate" in limitation for limitation in breach["limitations"])
    for card in insights["cards"]:
        assert card["kind"] in {"risk", "info", "opportunity", "quality"}
        assert card["evidence"] and card["action"] and card["limitations"]


def test_olist_forecast_uses_complete_months_and_identical_backtest(client: TestClient) -> None:
    forecast = client.get("/api/olist/forecast").json()
    assert forecast["available"] is True
    assert forecast["history"][0]["period"] == "2017-01-01"
    assert forecast["history"][-1]["period"] == "2018-07-01"
    assert len({model["evaluation_points"] for model in forecast["models"]}) == 1
    assert forecast["intervals"]["shown"] is False


def test_olist_customer_intelligence_counts_every_customer(client: TestClient, research: dict) -> None:
    payload = client.get("/api/olist/customer-intelligence").json()
    assert payload["available"] is True
    assert payload["customers"] == research["platform_kpis"]["unique_customers"]
    assert sum(segment["customers"] for segment in payload["segments"]) == payload["customers"]
    assert math.isclose(payload["revenue_total"], research["platform_kpis"]["total_gmv_brl"], rel_tol=1e-9)
    assert abs(payload["reconciliation"]["difference"]) < 0.01


def test_market_scorecards_reconcile_to_platform_totals(client: TestClient, research: dict) -> None:
    payload = client.get("/api/olist/markets").json()
    categories, states = payload["categories"], payload["states"]
    platform_gmv = research["platform_kpis"]["total_gmv_brl"]
    assert math.isclose(sum(row["gmv"] for row in categories["rows"]), platform_gmv, rel_tol=1e-9)
    assert math.isclose(sum(row["gmv"] for row in states["rows"]), platform_gmv, rel_tol=1e-9)
    assert states["orders_total"] == research["platform_kpis"]["delivered_orders"]
    assert categories["reliable_categories"] == sum(1 for row in categories["rows"] if row["orders"] >= categories["min_orders"])
    assert categories["association"]["n_groups"] == categories["reliable_categories"]
    for row in categories["rows"] + states["rows"]:
        low, high = row["sla_breach_ci"]
        assert low <= row["sla_breach_rate"] <= high
    weighted_breach = sum(row["sla_breach_rate"] * row["delivered_orders"] for row in states["rows"]) / states["orders_total"]
    assert weighted_breach * 100 == pytest.approx(research["platform_kpis"]["sla_breach_rate_pct"], abs=1e-9)
