import { useMemo } from "react";
import { useParams } from "react-router-dom";
import type { DatasetQuality, DatasetStatusPayload, QualityIssue } from "../../api/datasetTypes";
import { Plot } from "../../charts/Plot";
import { chartColors } from "../../charts/theme";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { useMetricDebugger } from "../../components/MetricDebugger";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { PageSkeleton } from "../../components/Skeleton";
import { Callout, EmptyState, ErrorState } from "../../components/States";
import { IconCheck, IconFormula } from "../../components/icons";
import { DatasetTabs, FailedView, ProcessingView, SchemaBadges } from "../../features/datasets/DatasetChrome";
import { useDatasetQuality, useDatasetStatus, useUpdatePolicies } from "../../features/datasets/queries";
import { formatMetricValue, formatNumber, formatPercent, formatSigned } from "../../lib/format";

const SEVERITY_COLORS: Record<QualityIssue["severity"], string> = {
  info: "var(--accent)",
  warning: "var(--warning)",
  critical: "var(--critical)",
};

const EXCLUSION_COLORS = ["#d03b3b", "#eb6834", "#eda100", "#8a63d2", "#1baf7a", "#7a8396", "#3987e5"];

function ExclusionChart({ quality }: { quality: DatasetQuality }) {
  const counts = quality.summary.record_counts;
  const data = useMemo(() => {
    if (!counts) return [];
    const first: { label: string; value: number; color: string } = { label: "Contributing", value: counts.contributing_records, color: chartColors.accent };
    const segments = [first].concat(
      counts.excluded.map((item, index) => ({ label: item.label, value: item.records, color: EXCLUSION_COLORS[index % EXCLUSION_COLORS.length] ?? "#7a8396" })),
    );
    return segments.map((segment) => ({
      type: "bar",
      orientation: "h",
      name: segment.label,
      y: ["Rows"],
      x: [segment.value],
      marker: { color: segment.color, line: { color: "#fff", width: 2 } },
      hovertemplate: `<b>${segment.label}</b><br>%{x:,} rows<extra></extra>`,
    }));
  }, [counts]);
  const layout = useMemo(
    () => ({
      barmode: "stack",
      margin: { l: 8, r: 8, t: 4, b: 8 },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: -0.35, yanchor: "top" },
      xaxis: { visible: false },
      yaxis: { visible: false },
      bargap: 0.1,
    }),
    [],
  );
  if (!counts) return null;
  return <Plot data={data} layout={layout} height={130} ariaLabel="Contributing and excluded rows" />;
}

function PoliciesCard({ quality, datasetId }: { quality: DatasetQuality; datasetId: string }) {
  const mutation = useUpdatePolicies(datasetId);
  const impactUnit = quality.impact.find((item) => item.metric_id === quality.summary.headline_metric);
  return (
    <Card title="Cleaning policies" subtitle="Reversible: toggling a policy recomputes every number instantly" stagger={1}>
      <div className="stack" style={{ gap: 14 }}>
        {quality.policies.map((policy) => (
          <div key={policy.key} className="row" style={{ alignItems: "flex-start", gap: 14 }}>
            <button
              type="button"
              role="switch"
              className="toggle"
              aria-checked={policy.enabled}
              aria-label={policy.label}
              disabled={mutation.isPending}
              onClick={() => mutation.mutate({ [policy.key]: !policy.enabled })}
            />
            <div className="stack" style={{ gap: 2 }}>
              <strong className="text-sm">
                {policy.label}{" "}
                {policy.enabled !== policy.default && (
                  <span className="badge badge-warning" style={{ marginLeft: 6 }}>
                    changed
                  </span>
                )}
              </strong>
              <span className="text-xs muted">{policy.description}</span>
              {policy.delta_if_toggled !== null && policy.delta_if_toggled !== 0 && impactUnit && (
                <span className="text-xs" style={{ color: "var(--ink-2)" }}>
                  {policy.enabled ? "Turning off" : "Turning on"} changes {impactUnit.label.toLowerCase()} by{" "}
                  <strong>{formatSignedMetric(policy.delta_if_toggled, impactUnit.unit, impactUnit.currency)}</strong>
                </span>
              )}
            </div>
          </div>
        ))}
        {mutation.isError && <Callout tone="critical">{(mutation.error as Error).message}</Callout>}
      </div>
    </Card>
  );
}

function formatSignedMetric(value: number, unit: string, currency: string | null): string {
  const magnitude = formatMetricValue(Math.abs(value), unit, currency);
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${magnitude}`;
}

function QualityContent({ status, quality }: { status: DatasetStatusPayload; quality: DatasetQuality }) {
  const { open } = useMetricDebugger();
  const datasetId = status.dataset.dataset_id;
  const counts = quality.summary.record_counts;
  const source = quality.source;
  const canonical = quality.canonical;
  const flagged = counts?.overlapping_flags.reduce((total, item) => total + item.records, 0) ?? 0;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Your data · data quality impact"
        title={status.dataset.display_name}
        description="Everything MIERU changed, excluded or flagged, and exactly how each decision moves your numbers. The uploaded file itself is never modified."
        actions={<DatasetTabs datasetId={datasetId} active="quality" />}
      />
      <div className="row row-wrap">
        <SchemaBadges grain={canonical.grain} basis={canonical.revenue_basis} currency={canonical.currency} rows={source.rows} />
      </div>

      <div className="grid grid-kpi">
        <Card stagger={0}>
          <span className="kpi-label">Rows in file</span>
          <div className="kpi-value tabular">{formatNumber(quality.summary.rows_in_file)}</div>
          <span className="kpi-context">
            {source.format.toUpperCase()} · {source.columns} columns
          </span>
        </Card>
        <Card stagger={1}>
          <span className="kpi-label">Contributing rows</span>
          <div className="kpi-value tabular">{formatNumber(counts?.contributing_records)}</div>
          <span className="kpi-context">Used for {quality.summary.headline_metric === "net_revenue" ? "revenue" : "order counts"}</span>
        </Card>
        <Card stagger={2}>
          <span className="kpi-label">Excluded rows</span>
          <div className="kpi-value tabular" style={{ color: counts?.excluded_total ? "var(--breach-ink)" : undefined }}>
            {formatNumber(counts?.excluded_total)}
          </div>
          <span className="kpi-context">Each with exactly one primary reason</span>
        </Card>
        <Card stagger={3}>
          <span className="kpi-label">Flags on kept rows</span>
          <div className="kpi-value tabular">{formatNumber(flagged)}</div>
          <span className="kpi-context">Can overlap · never removed silently</span>
        </Card>
      </div>

      {counts && (
        <Card
          title="Where every row went"
          subtitle={
            counts.is_consistent ? (
              <span className="row" style={{ gap: 6 }}>
                <IconCheck width={14} height={14} style={{ color: "var(--good)" }} />
                {formatNumber(counts.input_records)} input = {formatNumber(counts.contributing_records)} contributing + {formatNumber(counts.excluded_total)}{" "}
                excluded
              </span>
            ) : (
              "Counts do not reconcile"
            )
          }
          actions={
            <button type="button" className="btn btn-sm" onClick={() => open({ source: "dataset", datasetId, metricId: quality.summary.headline_metric })}>
              <IconFormula width={14} height={14} /> Open in Metric Debugger
            </button>
          }
          stagger={1}
        >
          <ExclusionChart quality={quality} />
        </Card>
      )}

      <div className="grid grid-main-side">
        <Card title="Impact on your KPIs" subtitle="Same file, with and without the cleaning policies" stagger={2}>
          <DataTable
            rows={quality.impact}
            rowKey={(row) => row.metric_id}
            columns={[
              { key: "label", header: "Metric", render: (row) => <strong>{row.label}</strong> },
              { key: "raw", header: "Without policies", align: "right", render: (row) => formatMetricValue(row.without_policies, row.unit, row.currency) },
              { key: "clean", header: "With policies", align: "right", render: (row) => formatMetricValue(row.with_policies, row.unit, row.currency) },
              {
                key: "delta",
                header: "Change",
                align: "right",
                render: (row) =>
                  row.delta === null || row.delta === 0 ? (
                    <span className="muted">no change</span>
                  ) : (
                    <span style={{ color: row.delta < 0 ? "var(--breach-ink)" : "var(--good)" }}>
                      {formatSignedMetric(row.delta, row.unit, row.currency)} {row.delta_share !== null && `(${formatSigned(row.delta_share * 100, 1)}%)`}
                    </span>
                  ),
              },
            ]}
          />
          <p className="text-xs muted" style={{ marginTop: 10 }}>
            "Without policies" still excludes values that cannot be read as numbers or dates; those cannot be summed without inventing data.
          </p>
        </Card>
        <PoliciesCard quality={quality} datasetId={datasetId} />
      </div>

      <SectionTitle title="Issues found" description="Severity reflects the potential effect on your numbers." />
      <Card stagger={2}>
        {quality.issues.length === 0 ? (
          <EmptyState title="No data-quality issues detected" text="Every row was readable and no duplicates, cancellations or anomalies were found." />
        ) : (
          <DataTable
            rows={quality.issues}
            rowKey={(row) => row.code}
            initialSort={{ key: "rows", direction: "desc" }}
            columns={[
              {
                key: "label",
                header: "Issue",
                render: (row) => (
                  <span>
                    <span className="severity-dot" style={{ background: SEVERITY_COLORS[row.severity] }} aria-hidden="true" />
                    <strong>{row.label}</strong>
                    <div className="text-xs muted" style={{ marginLeft: 16 }}>
                      {row.explanation}
                    </div>
                  </span>
                ),
              },
              { key: "rows", header: "Rows", align: "right", sortValue: (row) => row.rows, render: (row) => formatNumber(row.rows) },
              { key: "share", header: "Share", align: "right", sortValue: (row) => row.share, render: (row) => formatPercent(row.share) },
              {
                key: "severity",
                header: "Severity",
                render: (row) => (
                  <span className={`badge ${row.severity === "critical" ? "badge-critical" : row.severity === "warning" ? "badge-warning" : ""}`}>
                    {row.severity}
                  </span>
                ),
              },
              { key: "treatment", header: "Treatment", render: (row) => row.treatment },
            ]}
          />
        )}
      </Card>

      <div className="grid grid-main-side">
        <Card title="Column profiles" subtitle="What MIERU detected in each column" stagger={3}>
          <DataTable
            rows={quality.columns}
            rowKey={(row) => row.name}
            maxHeight={420}
            columns={[
              { key: "name", header: "Column", sortValue: (row) => row.name, render: (row) => <strong>{row.name}</strong> },
              {
                key: "role",
                header: "Detected role",
                sortValue: (row) => row.role_label ?? "",
                render: (row) => (row.role_label ? <span className="badge badge-accent">{row.role_label}</span> : <span className="muted">not used</span>),
              },
              {
                key: "filled",
                header: "Filled",
                align: "right",
                sortValue: (row) => row.non_null_share,
                render: (row) => formatPercent(row.non_null_share, 0),
              },
              { key: "numeric", header: "Numeric", align: "right", sortValue: (row) => row.numeric_rate, render: (row) => formatPercent(row.numeric_rate, 0) },
              { key: "date", header: "Dates", align: "right", sortValue: (row) => row.date_rate, render: (row) => formatPercent(row.date_rate, 0) },
              { key: "sample", header: "Sample", render: (row) => <span className="text-xs muted">{row.sample_values.join(" · ")}</span> },
            ]}
          />
        </Card>
        <Card title="How the file was read" stagger={4}>
          <dl className="kv">
            <dt>Format</dt>
            <dd>{source.format.toUpperCase()}</dd>
            {source.encoding && (
              <>
                <dt>Encoding</dt>
                <dd>{source.encoding}</dd>
              </>
            )}
            {source.delimiter && (
              <>
                <dt>Delimiter</dt>
                <dd>{source.delimiter}</dd>
              </>
            )}
            {source.sheet_name && (
              <>
                <dt>Worksheet</dt>
                <dd>
                  {source.sheet_name} ({source.sheet_names.length} in workbook)
                </dd>
              </>
            )}
            <dt>Header row</dt>
            <dd>
              {source.synthesized_header ? "none found (generated names)" : `row ${source.header_row_number}`}
              {source.skipped_leading_rows > 0 && ` · ${source.skipped_leading_rows} title row(s) skipped`}
            </dd>
            <dt>Grain</dt>
            <dd>{canonical.grain}</dd>
            <dt>Revenue</dt>
            <dd>{canonical.revenue_label}</dd>
            <dt>File fingerprint</dt>
            <dd className="text-xs">SHA-256 {source.sha256?.slice(0, 16)}…</dd>
          </dl>
          {source.notes.length > 0 && (
            <ul className="list" style={{ marginTop: 12 }}>
              {source.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <SectionTitle
        title="Transformation audit trail"
        description="Every step from upload to dashboard, in order. Re-running the same file with the same settings reproduces these results."
      />
      <Card stagger={5}>
        <ol className="timeline">
          {quality.audit.map((entry, index) => (
            <li key={`${entry.step}-${index}`}>
              <strong className="text-sm">{entry.title}</strong>
              <span className="text-sm muted">{entry.detail}</span>
            </li>
          ))}
          {quality.policies.map((policy) => (
            <li key={policy.key}>
              <strong className="text-sm">
                Policy · {policy.label}: {policy.enabled ? "on" : "off"}
              </strong>
              <span className="text-sm muted">{policy.description}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

export function DataQualityPage() {
  const { datasetId = "" } = useParams();
  const status = useDatasetStatus(datasetId);
  const ready = status.data?.dataset.status === "ready";
  const quality = useDatasetQuality(datasetId, status.data?.dataset.data_version, ready);
  if (status.isPending) return <PageSkeleton />;
  if (status.isError) return <EmptyState title="Dataset not found" text="It may have expired, been deleted, or belong to another browser session." />;
  if (status.data.dataset.status === "failed") return <FailedView status={status.data} />;
  if (!ready) return <ProcessingView status={status.data} />;
  if (quality.isPending) return <PageSkeleton kpis={4} />;
  if (quality.isError) return <ErrorState title="Could not build the quality report" text={(quality.error as Error).message} />;
  return <QualityContent status={status.data} quality={quality.data} />;
}
