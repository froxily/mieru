import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api/client";
import type { MetricExplanation } from "../api/types";
import { formatMetricValue, formatNumber, prettifyLabel } from "../lib/format";
import { IconCheck, IconClose, IconCopy, IconFormula } from "./icons";
import { Skeleton } from "./Skeleton";
import { Callout, ErrorState } from "./States";
import { useFocusTrap } from "../lib/useFocusTrap";

export type MetricReference = { source: "olist"; metricId: string } | { source: "dataset"; datasetId: string; metricId: string; query?: string };

interface MetricDebuggerContextValue {
  open: (reference: MetricReference) => void;
}

const MetricDebuggerContext = createContext<MetricDebuggerContextValue>({ open: () => undefined });

export function useMetricDebugger(): MetricDebuggerContextValue {
  return useContext(MetricDebuggerContext);
}

function explanationPath(reference: MetricReference): string {
  if (reference.source === "olist") return `/api/metrics/olist/${encodeURIComponent(reference.metricId)}/explain`;
  const suffix = reference.query ? `?${reference.query}` : "";
  return `/api/datasets/${encodeURIComponent(reference.datasetId)}/metrics/${encodeURIComponent(reference.metricId)}/explain${suffix}`;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        });
      }}
    >
      {copied ? <IconCheck width={14} height={14} /> : <IconCopy width={14} height={14} />}
      {copied ? "Copied" : "Copy SQL"}
    </button>
  );
}

function RecordCountsSection({ counts }: { counts: NonNullable<MetricExplanation["record_counts"]> }) {
  const total = Math.max(counts.input_records, 1);
  const contributingWidth = (counts.contributing_records / total) * 100;
  return (
    <section className="drawer-section">
      <h3>Supporting records</h3>
      <div className="stack">
        <div className="count-bar" aria-hidden="true">
          <span style={{ width: `${contributingWidth}%`, background: "var(--accent)" }} />
          <span style={{ width: `${100 - contributingWidth}%`, background: "var(--line-strong)" }} />
        </div>
        <dl className="kv">
          <dt>Grain</dt>
          <dd>{counts.grain}</dd>
          <dt>Input records</dt>
          <dd>{formatNumber(counts.input_records)}</dd>
          <dt>Contributing</dt>
          <dd>{formatNumber(counts.contributing_records)}</dd>
          {counts.excluded.map((item) => (
            <FragmentRow key={item.reason} label={`Excluded · ${item.label}`} value={formatNumber(item.records)} />
          ))}
          <dt>Invariant</dt>
          <dd>
            {counts.is_consistent ? (
              <span className="badge badge-good">
                <IconCheck width={12} height={12} /> input = contributing + excluded
              </span>
            ) : (
              <span className="badge badge-critical">Counts do not reconcile</span>
            )}
          </dd>
        </dl>
        {counts.overlapping_flags.length > 0 && (
          <div className="stack">
            <p className="text-xs muted">
              Quality flags below can overlap (one record may carry several), so they are reported separately and do not add up to the exclusions.
            </p>
            <dl className="kv">
              {counts.overlapping_flags.map((item) => (
                <FragmentRow key={item.reason} label={item.label} value={formatNumber(item.records)} />
              ))}
            </dl>
          </div>
        )}
      </div>
    </section>
  );
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function ListSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section className="drawer-section">
      <h3>{title}</h3>
      <ul className="list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function ContextSection({ context, currency }: { context: Record<string, unknown>; currency: string | null }) {
  const funnel = context.upstream_funnel as Record<string, number> | undefined;
  const reconciliation = context.gmv_for_reconciliation as number | undefined;
  const extraEntries = Object.entries(context).filter(
    ([key, value]) => key !== "upstream_funnel" && key !== "gmv_for_reconciliation" && (typeof value === "number" || typeof value === "string"),
  );
  if (!funnel && reconciliation === undefined && extraEntries.length === 0) return null;
  return (
    <section className="drawer-section">
      <h3>Upstream context</h3>
      <dl className="kv">
        {funnel && (
          <>
            <FragmentRow label="Raw orders in source" value={formatNumber(funnel.raw_orders)} />
            <FragmentRow label="Not delivered (excluded)" value={formatNumber(funnel.excluded_not_delivered)} />
            <FragmentRow label="Delivered, missing dates (excluded)" value={formatNumber(funnel.excluded_delivered_missing_dates)} />
            <FragmentRow label="Delivered orders in mart" value={formatNumber(funnel.delivered_orders_in_mart)} />
          </>
        )}
        {reconciliation !== undefined && <FragmentRow label="GMV for reconciliation" value={formatMetricValue(reconciliation, "currency", currency)} />}
        {extraEntries.map(([key, value]) => (
          <FragmentRow key={key} label={prettifyLabel(key)} value={typeof value === "number" ? formatNumber(value, 2) : String(value)} />
        ))}
      </dl>
    </section>
  );
}

function ExplanationBody({ explanation }: { explanation: MetricExplanation }) {
  const { definition } = explanation;
  return (
    <>
      <section className="drawer-section">
        <h3>Value</h3>
        {explanation.status === "ok" ? (
          <div className="kpi-value tabular">{formatMetricValue(explanation.value, definition.unit, explanation.currency)}</div>
        ) : (
          <Callout tone="warning" title="Not calculated">
            {explanation.unavailable_reason}
          </Callout>
        )}
        <p className="text-sm muted" style={{ marginTop: 8 }}>
          {definition.description}
        </p>
      </section>
      <section className="drawer-section">
        <h3>Formula</h3>
        <div className="formula">{definition.formula}</div>
      </section>
      {explanation.record_counts && <RecordCountsSection counts={explanation.record_counts} />}
      <ListSection title="Source columns" items={definition.source_columns} />
      <ListSection title="Transformations" items={definition.transformations} />
      <ListSection title="Filters & exclusions" items={definition.exclusions} />
      <ListSection title="Assumptions" items={definition.assumptions} />
      <ListSection title="Limitations" items={definition.limitations} />
      <ContextSection context={explanation.context} currency={explanation.currency} />
      {explanation.lineage.length > 0 && (
        <section className="drawer-section">
          <h3>Lineage</h3>
          <ol className="lineage">
            {explanation.lineage.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </section>
      )}
      {explanation.sql && (
        <section className="drawer-section">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Executed SQL (DuckDB)</h3>
            <CopyButton text={explanation.sql} />
          </div>
          <pre className="code">{explanation.sql}</pre>
        </section>
      )}
    </>
  );
}

function MetricDrawer({ reference, onClose }: { reference: MetricReference; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLDivElement | null>(null);
  useFocusTrap(drawerRef);
  const path = explanationPath(reference);
  const query = useQuery({ queryKey: ["metric-explain", path], queryFn: ({ signal }) => getJson<MetricExplanation>(path, signal) });

  useEffect(() => {
    closeRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const title = query.data?.definition.label ?? "Metric";
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} aria-hidden="true" />
      <div ref={drawerRef} className="drawer" role="dialog" aria-modal="true" aria-labelledby="metric-drawer-title">
        <header className="drawer-header">
          <div className="stack" style={{ gap: 6 }}>
            <span className="badge badge-accent" style={{ alignSelf: "flex-start" }}>
              <IconFormula width={12} height={12} /> Metric Debugger
            </span>
            <h2 id="metric-drawer-title" style={{ fontSize: "1.25rem" }}>
              {title}
            </h2>
            <span className="text-xs muted">
              {reference.metricId} · {query.data?.definition.grain ?? ""} grain
            </span>
          </div>
          <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label="Close metric debugger">
            <IconClose />
          </button>
        </header>
        <div className="drawer-body">
          {query.isPending && (
            <div className="stack">
              <Skeleton height={36} width={220} />
              <Skeleton height={64} />
              <Skeleton height={140} />
              <Skeleton height={180} />
            </div>
          )}
          {query.isError && <ErrorState title="Could not load this explanation" text={(query.error as Error).message} />}
          {query.data && <ExplanationBody explanation={query.data} />}
        </div>
      </div>
    </>
  );
}

export function MetricDebuggerProvider({ children }: { children: ReactNode }) {
  const [reference, setReference] = useState<MetricReference | null>(null);
  const open = useCallback((next: MetricReference) => setReference(next), []);
  const close = useCallback(() => setReference(null), []);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <MetricDebuggerContext.Provider value={value}>
      {children}
      {reference && <MetricDrawer reference={reference} onClose={close} />}
    </MetricDebuggerContext.Provider>
  );
}
