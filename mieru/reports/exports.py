import csv
import datetime as dt
import html
import io
import re
from collections.abc import Iterator
from typing import Any

import duckdb

from mieru.metrics.upload import EXCLUSION_LABELS, FLAG_LABELS, POLICY_DESCRIPTIONS, DatasetContext, Filters, classified_cte

EXPORT_BATCH_ROWS: int = 5000
EXCEL_MAX_ROWS: int = 1_048_575
FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
PLAIN_NUMBER = re.compile(r"^[+-]?(\d+([.,]\d+)*|\.\d+)([eE][+-]?\d+)?$")
EXPORT_KINDS: dict[str, tuple[str, str]] = {
    "cleaned.csv": ("text/csv; charset=utf-8", "cleaned"),
    "annotated.csv": ("text/csv; charset=utf-8", "annotated"),
    "workbook.xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "workbook"),
    "report.html": ("text/html; charset=utf-8", "report"),
    "report.md": ("text/markdown; charset=utf-8", "report"),
}


def neutralize_formula(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(FORMULA_PREFIXES) and not PLAIN_NUMBER.match(value.strip()):
        return "'" + value
    return value


def export_columns(source_columns: list[str]) -> list[str]:
    return [
        *source_columns,
        "mieru_row_id",
        "mieru_status",
        "mieru_exclusion_reason",
        "mieru_flags",
        "mieru_order_date",
        "mieru_net_value",
    ]


def row_query(context: DatasetContext, filters: Filters, source_count: int, only_contributing: bool) -> tuple[str, list[Any]]:
    cte_sql, parameters, _reasons = classified_cte(("revenue",) if context.capability("revenue")[0] else (), context, filters)
    flag_expression = " || ".join(f"CASE WHEN scoped.{flag} THEN '{flag};' ELSE '' END" for flag in FLAG_LABELS)
    source_select = ", ".join(f's."c{index:03d}"' for index in range(source_count))
    sql = f"""WITH {cte_sql.strip()}
SELECT {source_select}{', ' if source_select else ''}
       scoped._row_id,
       CASE WHEN scoped.contributes THEN 'included' ELSE 'excluded' END AS status,
       scoped.exclusion_reason,
       {flag_expression} AS flags,
       strftime(scoped.order_ts, '%Y-%m-%d %H:%M:%S') AS order_date,
       CASE WHEN scoped.contributes THEN COALESCE(scoped.net_value, scoped.order_value_once) END AS net_value
FROM scoped
JOIN src_rows AS s ON s._row_id = scoped._row_id
{'WHERE scoped.contributes' if only_contributing else ''}
ORDER BY scoped._row_id"""
    return sql, parameters


def iter_csv(connection: duckdb.DuckDBPyConnection, context: DatasetContext, filters: Filters, source_columns: list[str], only_contributing: bool) -> Iterator[bytes]:
    sql, parameters = row_query(context, filters, len(source_columns), only_contributing)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    buffer.write("\ufeff")
    writer.writerow([neutralize_formula(column) for column in export_columns(source_columns)])
    cursor = connection.execute(sql, parameters)
    while True:
        rows = cursor.fetchmany(EXPORT_BATCH_ROWS)
        for row in rows:
            values = list(row)
            reason = values[-4]
            values[-4] = EXCLUSION_LABELS.get(reason, reason) if reason else ""
            values[-3] = (values[-3] or "").rstrip(";")
            writer.writerow([neutralize_formula(value) if value is not None else "" for value in values])
        yield buffer.getvalue().encode("utf-8")
        buffer.seek(0)
        buffer.truncate(0)
        if not rows:
            break


def build_workbook(
    connection: duckdb.DuckDBPyConnection,
    context: DatasetContext,
    filters: Filters,
    source_columns: list[str],
    dashboard: dict[str, Any],
    quality: dict[str, Any],
    insights: dict[str, Any],
    display_name: str,
    performance: dict[str, Any] | None = None,
) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)

    def sheet(title: str, header: list[str], rows: list[list[Any]]) -> None:
        worksheet = workbook.create_sheet(title)
        worksheet.append([neutralize_formula(value) for value in header])
        for row in rows:
            worksheet.append([neutralize_formula(value) for value in row])

    summary_rows: list[list[Any]] = [
        ["File", display_name],
        ["Generated (UTC)", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")],
        ["Grain", dashboard["dataset"]["grain"]],
        ["Revenue basis", dashboard["dataset"]["revenue_label"]],
        ["Currency", dashboard["dataset"]["currency"] or "not specified"],
        ["Filters", ", ".join(f"{key}={value}" for key, value in filters.to_dict().items() if value) or "none"],
        [],
        ["KPI", "Value", "Unit", "Status / reason"],
    ]
    for kpi in dashboard["kpis"]:
        summary_rows.append([kpi["label"], kpi["value"], kpi["unit"] + (f" ({kpi['currency']})" if kpi.get("currency") else ""), kpi["status"] if kpi["status"] == "ok" else kpi["unavailable_reason"]])
    summary_rows += [[], ["Policy", "Enabled", "Description"]]
    for key, descriptor in POLICY_DESCRIPTIONS.items():
        summary_rows.append([descriptor["label"], "yes" if context.policies.get(key) else "no", descriptor["description"]])
    summary_rows += [[], ["Assumptions"]] + [[item] for item in dashboard.get("assumptions", [])]
    summary = workbook.create_sheet("Summary")
    title_row = [neutralize_formula("MIERU export")]
    summary.append(title_row)
    for row in summary_rows:
        summary.append([neutralize_formula(value) for value in row])
    data_sheet = workbook.create_sheet("Cleaned data")
    data_sheet.append([neutralize_formula(column) for column in export_columns(source_columns)])
    sql, parameters = row_query(context, filters, len(source_columns), only_contributing=True)
    cursor = connection.execute(sql, parameters)
    written = 0
    while written < EXCEL_MAX_ROWS:
        rows = cursor.fetchmany(EXPORT_BATCH_ROWS)
        if not rows:
            break
        for row in rows[: EXCEL_MAX_ROWS - written]:
            values = list(row)
            values[-4] = EXCLUSION_LABELS.get(values[-4], values[-4]) if values[-4] else ""
            values[-3] = (values[-3] or "").rstrip(";")
            data_sheet.append([neutralize_formula(value) for value in values])
        written += len(rows)
    sheet(
        "Quality issues",
        ["Issue (whole file)", "Rows", "Share", "Severity", "Treatment", "Explanation"],
        [[issue["label"], issue["rows"], issue["share"], issue["severity"], issue["treatment"], issue["explanation"]] for issue in quality["issues"]],
    )
    counts = quality["summary"]["record_counts"] or {"excluded": [], "input_records": 0, "contributing_records": 0}
    sheet(
        "Exclusions",
        ["Reason", "Rows"],
        [["Input rows", counts["input_records"]], ["Contributing rows", counts["contributing_records"]]]
        + [[item["label"], item["records"]] for item in counts["excluded"]],
    )
    sheet(
        "KPI impact",
        ["Metric", "Without policies", "With policies", "Change"],
        [[item["label"], item["without_policies"], item["with_policies"], item["delta"]] for item in quality["impact"]],
    )
    sheet("Audit trail", ["Step", "Title", "Detail", "At (UTC)"], [[entry["step"], entry["title"], entry["detail"], entry["at"]] for entry in quality["audit"]])
    sheet(
        "Column profiles",
        ["Column", "Detected role", "Filled share", "Numeric share", "Date share", "Sample"],
        [[column["name"], column["role_label"] or "", column["non_null_share"], column["numeric_rate"], column["date_rate"], " · ".join(column["sample_values"])] for column in quality["columns"]],
    )
    sheet(
        "Insights",
        ["Kind", "Finding", "Interpretation", "Action", "Limitations"],
        [[card["kind"], card["finding"], card["interpretation"], card["action"], " | ".join(card["limitations"])] for card in insights["cards"]],
    )
    for title, header, rows in analytics_tables(dashboard, performance):
        sheet(title, header, rows)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


DIMENSION_LABELS: dict[str, str] = {"products": "Product", "categories": "Category", "regions": "Region", "channels": "Channel"}


def grouped_rows(groups: dict[str, Any], fields: tuple[str, ...]) -> list[list[Any]]:
    return [[DIMENSION_LABELS.get(key, key), group["label"], *[group[field] for field in fields]] for key, payload in groups.items() for group in payload["rows"]]


def analytics_tables(dashboard: dict[str, Any], performance: dict[str, Any] | None) -> list[tuple[str, list[str], list[list[Any]]]]:
    tables: list[tuple[str, list[str], list[list[Any]]]] = []
    breakdown_rows: list[list[Any]] = []
    for key, breakdown in dashboard.get("breakdowns", {}).items():
        if not breakdown.get("available"):
            continue
        for row in breakdown["rows"]:
            breakdown_rows.append([DIMENSION_LABELS.get(key, key), row["label"], row["revenue"], row["revenue_share"], row["orders"], row["units"], row["rows"]])
        if breakdown.get("others"):
            others = breakdown["others"]
            breakdown_rows.append([DIMENSION_LABELS.get(key, key), others["label"], others["revenue"], others["revenue_share"], None, None, others["rows"]])
    if breakdown_rows:
        tables.append(("Breakdowns", ["Dimension", "Group", "Net revenue", "Revenue share", "Orders", "Units", "Rows"], breakdown_rows))
    if not performance:
        return tables
    bridge = performance.get("bridge", {})
    if bridge.get("available"):
        rows = [[step["label"], step["value"], step["metric_id"] or ""] for step in bridge["steps"]]
        tables.append(("Revenue bridge", ["Step", "Value", "Metric"], rows + [[], [bridge["identity"]]] + [[note] for note in bridge["notes"]]))
    profitability = performance.get("profitability", {})
    if profitability.get("available"):
        rows = grouped_rows(profitability["groups"], ("revenue", "cost", "gross_profit", "margin", "rows"))
        tables.append(("Profitability", ["Dimension", "Group", "Net revenue", "Cost", "Gross profit", "Margin", "Rows"], rows + [[], [profitability["note"]]]))
    returns = performance.get("returns", {})
    if returns.get("available"):
        rows = grouped_rows(returns["groups"], ("gross_sales", "net_sales", "returns_value", "return_rate", "sale_rows", "return_rows", "small_sample"))
        header = ["Dimension", "Group", "Gross sales", "Sales after discounts", "Returns & credits", "Return rate", "Sale rows", "Return rows", "Small sample"]
        tables.append(("Returns", header, rows + [[], [returns["note"]]]))
    discounts = performance.get("discounts", {})
    if discounts.get("available"):
        rows = grouped_rows(discounts["groups"], ("discount_value", "list_value", "discount_rate", "discounted_rows", "sale_rows"))
        header = ["Dimension", "Group", "Discounts", "List value", "Discount rate", "Discounted rows", "Sale rows"]
        tables.append(("Discounts", header, rows + [[], [discounts["note"]]]))
    concentration = performance.get("concentration", {})
    if concentration.get("available"):
        rows = []
        for key in ("products", "customers"):
            summary = concentration.get(key, {})
            if summary.get("available"):
                rows.append(
                    [key.capitalize(), summary["items"], summary["top_10pct_share"], summary["top_20pct_share"], summary["items_for_50pct"], summary["items_for_80pct"], summary["gini"], summary["excluded_non_positive"]]
                )
        if rows:
            header = ["Items", "Count", "Top 10% share", "Top 20% share", "Items for 50%", "Items for 80%", "Gini", "Excluded (zero or negative revenue)"]
            tables.append(("Concentration", header, rows + [[], [concentration["note"]]]))
    return tables


def performance_summary(performance: dict[str, Any] | None, currency: str | None) -> list[tuple[str, str]]:
    if not performance:
        return []
    lines: list[tuple[str, str]] = []
    bridge = performance.get("bridge", {})
    if bridge.get("available"):
        lines += [(step["label"], format_value(step["value"], "currency", currency)) for step in bridge["steps"]]
    profitability = performance.get("profitability", {})
    if profitability.get("available"):
        coverage = profitability["cost_coverage"]
        lines.append(("Gross margin (rows with cost)", format_value(profitability["margin"], "ratio", None)))
        lines.append(("Rows with a recorded cost", f"{coverage['rows_with_cost']:,} of {coverage['contributing_rows']:,}"))
    returns = performance.get("returns", {})
    if returns.get("available"):
        lines.append(("Return rate", format_value(returns["return_rate"], "ratio", None)))
    discounts = performance.get("discounts", {})
    if discounts.get("available"):
        lines.append(("Discount rate", format_value(discounts["discount_rate"], "ratio", None)))
    concentration = performance.get("concentration", {})
    if concentration.get("available"):
        for key in ("products", "customers"):
            summary = concentration.get(key, {})
            if summary.get("available"):
                lines.append((f"Revenue share of the top 20% of {key}", format_value(summary["top_20pct_share"], "ratio", None)))
    return lines


def format_value(value: Any, unit: str, currency: str | None) -> str:
    if value is None:
        return "—"
    if unit in {"ratio", "share"}:
        return f"{value * 100:.1f}%"
    if unit == "currency":
        return f"{currency + ' ' if currency else ''}{value:,.2f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def report_sections(
    dashboard: dict[str, Any], quality: dict[str, Any], insights: dict[str, Any], filters: Filters, display_name: str, performance: dict[str, Any] | None = None
) -> dict[str, Any]:
    dataset = dashboard["dataset"]
    return {
        "title": f"MIERU report · {display_name}",
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "meta": [
            ("Rows in file", f"{dataset['rows']:,}"),
            ("Grain", dataset["grain_explanation"]),
            ("Revenue", dataset["revenue_label"]),
            ("Currency", dataset["currency"] or "not specified"),
            ("Filters", ", ".join(f"{key}={value}" for key, value in filters.to_dict().items() if value) or "none"),
        ],
        "kpis": [
            (kpi["label"], format_value(kpi["value"], kpi["unit"], kpi.get("currency")) if kpi["status"] == "ok" else f"Not available — {kpi['unavailable_reason']}")
            for kpi in dashboard["kpis"]
        ],
        "insights": insights["cards"],
        "performance": performance_summary(performance, dataset["currency"]),
        "impact": [
            (item["label"], format_value(item["without_policies"], item["unit"], item.get("currency")), format_value(item["with_policies"], item["unit"], item.get("currency")))
            for item in quality["impact"]
        ],
        "issues": [(issue["label"], f"{issue['rows']:,}", issue["treatment"]) for issue in quality["issues"]],
        "assumptions": list(dashboard.get("assumptions", [])) + [item["message"] for item in dashboard.get("clarifications", [])],
        "audit": [(entry["title"], entry["detail"]) for entry in quality["audit"]],
    }


def build_markdown_report(sections: dict[str, Any]) -> str:
    def escape(text: Any) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")

    lines = [f"# {escape(sections['title'])}", "", f"_Generated {sections['generated']} by MIERU. Every figure is reproducible from the uploaded file and the listed policies._", ""]
    lines += ["## Dataset", "", "| | |", "|---|---|"] + [f"| {escape(key)} | {escape(value)} |" for key, value in sections["meta"]] + [""]
    lines += ["## Key metrics", "", "| Metric | Value |", "|---|---|"] + [f"| {escape(label)} | {escape(value)} |" for label, value in sections["kpis"]] + [""]
    if sections.get("performance"):
        lines += ["## Revenue & profit", "", "| Measure | Value |", "|---|---|"] + [f"| {escape(label)} | {escape(value)} |" for label, value in sections["performance"]] + [""]
    lines += ["## Insights", ""]
    if not sections["insights"]:
        lines += ["No insight passed its evidence gates.", ""]
    for card in sections["insights"]:
        lines += [f"### {escape(card['finding'])}", "", f"- **What it means:** {escape(card['interpretation'])}", f"- **Suggested action:** {escape(card['action'])}"]
        lines += [f"- **Limitation:** {escape(item)}" for item in card["limitations"]] + [""]
    lines += ["## Data quality impact", "", "| Metric | Without policies | With policies |", "|---|---|---|"] + [f"| {escape(a)} | {escape(b)} | {escape(c)} |" for a, b, c in sections["impact"]] + [""]
    lines += ["_Issue counts below cover the whole file; the comparison above uses the active filters._", ""]
    lines += ["| Issue | Rows | Treatment |", "|---|---|---|"] + [f"| {escape(a)} | {escape(b)} | {escape(c)} |" for a, b, c in sections["issues"]] + [""]
    if sections["assumptions"]:
        lines += ["## Assumptions & clarifications", ""] + [f"- {escape(item)}" for item in sections["assumptions"]] + [""]
    lines += ["## Audit trail", ""] + [f"{index}. **{escape(title)}** — {escape(detail)}" for index, (title, detail) in enumerate(sections["audit"], start=1)]
    return "\n".join(lines) + "\n"


def build_html_report(sections: dict[str, Any]) -> str:
    def e(text: Any) -> str:
        return html.escape(str(text), quote=True)

    def table(header: list[str], rows: list[tuple[Any, ...]]) -> str:
        head = "".join(f"<th>{e(cell)}</th>" for cell in header)
        body = "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    insights_html = "".join(
        f"<section class='card'><h3>{e(card['finding'])}</h3><p><strong>What it means:</strong> {e(card['interpretation'])}</p>"
        f"<p><strong>Suggested action:</strong> {e(card['action'])}</p><ul>{''.join(f'<li>{e(item)}</li>' for item in card['limitations'])}</ul></section>"
        for card in sections["insights"]
    ) or "<p>No insight passed its evidence gates.</p>"
    assumptions_html = "".join(f"<li>{e(item)}</li>" for item in sections["assumptions"])
    audit_html = "".join(f"<li><strong>{e(title)}</strong> — {e(detail)}</li>" for title, detail in sections["audit"])
    performance_html = f"<h2>Revenue &amp; profit</h2>{table(['Measure', 'Value'], sections['performance'])}" if sections.get("performance") else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(sections['title'])}</title>
<style>
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;color:#0e1525;background:#f4f5f8;margin:0;padding:32px 16px;line-height:1.5}}
main{{max-width:960px;margin:0 auto}} h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 12px}} h3{{font-size:16px;margin:0 0 8px}}
.muted{{color:#7a8396;font-size:13px}} table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e8ee;border-radius:10px;overflow:hidden;font-size:14px}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid #e5e8ee}} th{{background:#f8f9fb;color:#7a8396;font-size:12px}}
.card{{background:#fff;border:1px solid #e5e8ee;border-radius:12px;padding:16px 20px;margin-bottom:12px}}
</style></head>
<body><main>
<h1>{e(sections['title'])}</h1><p class="muted">Generated {e(sections['generated'])} by MIERU · every figure is reproducible from the uploaded file and the listed policies.</p>
<h2>Dataset</h2>{table(['', ''], sections['meta'])}
<h2>Key metrics</h2>{table(['Metric', 'Value'], sections['kpis'])}
{performance_html}
<h2>Insights</h2>{insights_html}
<h2>Data quality impact</h2>{table(['Metric', 'Without policies', 'With policies'], sections['impact'])}
<p class="muted">Issue counts below cover the whole file; the comparison above uses the active filters.</p>{table(['Issue', 'Rows', 'Treatment'], sections['issues'])}
<h2>Assumptions &amp; clarifications</h2><ul>{assumptions_html or '<li>None</li>'}</ul>
<h2>Audit trail</h2><ol>{audit_html}</ol>
</main></body></html>
"""
