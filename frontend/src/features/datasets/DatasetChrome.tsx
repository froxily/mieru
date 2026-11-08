import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Clarification, DatasetStatusPayload } from "../../api/datasetTypes";
import { Card } from "../../components/Card";
import { Callout, ErrorState } from "../../components/States";
import { IconCheck, IconClose } from "../../components/icons";
import { formatNumber } from "../../lib/format";

const STAGE_LABELS: Record<string, string> = {
  uploaded: "File received",
  decoding: "Reading & decoding",
  profiling: "Profiling columns",
  mapping: "Detecting column roles",
  cleaning: "Cleaning & checking quality",
  analytics: "Building dashboards",
};

export const GRAIN_LABELS: Record<string, string> = {
  line: "Line-item file",
  order: "One row per order",
  transaction: "Transaction list",
};

export const BASIS_LABELS: Record<string, string> = {
  line_amount: "Revenue from amount column",
  quantity_x_unit_price: "Revenue = quantity × price",
  order_total: "Revenue from order totals (once per order)",
  unit_price_one_unit_per_row: "Revenue from price (one unit per row)",
};

export function ProcessingView({ status }: { status: DatasetStatusPayload }) {
  const stages = status.stages.filter((stage) => stage !== "ready");
  const currentIndex = Math.max(0, stages.indexOf(status.dataset.stage));
  return (
    <div className="page">
      <Card stagger={0}>
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.2fr)", alignItems: "center", gap: 32 }}>
          <div className="stack">
            <span className="page-eyebrow" style={{ margin: 0 }}>
              Analysing your file
            </span>
            <h1 className="page-title" style={{ fontSize: "1.75rem" }}>
              {status.dataset.display_name}
            </h1>
            <p className="muted text-sm">
              MIERU is reading the file, recognising its structure and preparing dashboards. This usually takes a few seconds; large files can take up to a
              minute.
            </p>
            <div className="progress" aria-hidden="true">
              <div className="progress-bar indeterminate" />
            </div>
          </div>
          <p className="visually-hidden" aria-live="polite">
            Step {currentIndex + 1} of {stages.length}: {STAGE_LABELS[stages[currentIndex] ?? ""] ?? status.dataset.stage}
          </p>
          <ol className="stepper" aria-label="Processing progress" style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {stages.map((stage, index) => {
              const state = index < currentIndex ? "done" : index === currentIndex ? "active" : "";
              return (
                <li key={stage} className={`step ${state}`}>
                  <span className="step-dot">{state === "done" && <IconCheck />}</span>
                  {STAGE_LABELS[stage] ?? stage}
                </li>
              );
            })}
          </ol>
        </div>
      </Card>
    </div>
  );
}

export function FailedView({ status }: { status: DatasetStatusPayload }) {
  const navigate = useNavigate();
  return (
    <ErrorState
      title="This file could not be analysed"
      text={status.dataset.error ?? "Processing failed."}
      action={
        <button type="button" className="btn btn-primary" onClick={() => navigate("/data")}>
          Upload another file
        </button>
      }
    />
  );
}

export function ClarificationsBanner({ assumptions, clarifications }: { assumptions: string[]; clarifications: Clarification[] }) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || (assumptions.length === 0 && clarifications.length === 0)) return null;
  const needsAttention = clarifications.some((item) => item.kind !== "assumption");
  return (
    <div className="stack" style={{ position: "relative" }}>
      <Callout tone={needsAttention ? "warning" : "info"} title={needsAttention ? "Some things need your attention" : "How MIERU interpreted this file"}>
        <ul className="list" style={{ marginTop: 4 }}>
          {clarifications.map((item) => (
            <li key={`${item.kind}-${item.role}-${item.message}`}>{item.message}</li>
          ))}
          {assumptions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </Callout>
      <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => setDismissed(true)} style={{ position: "absolute", right: 10, top: 10 }}>
        <IconClose />
      </button>
    </div>
  );
}

export function DatasetTabs({ datasetId, active }: { datasetId: string; active: "dashboard" | "performance" | "quality" | "insights" | "customers" }) {
  return (
    <nav className="segmented" aria-label="Dataset views">
      <Link to={`/data/${datasetId}`} className="segmented-link" aria-current={active === "dashboard" ? "page" : undefined}>
        Dashboard
      </Link>
      <Link to={`/data/${datasetId}/performance`} className="segmented-link" aria-current={active === "performance" ? "page" : undefined}>
        Performance
      </Link>
      <Link to={`/data/${datasetId}/quality`} className="segmented-link" aria-current={active === "quality" ? "page" : undefined}>
        Data quality
      </Link>
      <Link to={`/data/${datasetId}/customers`} className="segmented-link" aria-current={active === "customers" ? "page" : undefined}>
        Customers
      </Link>
      <Link to={`/data/${datasetId}/insights`} className="segmented-link" aria-current={active === "insights" ? "page" : undefined}>
        Insights
      </Link>
    </nav>
  );
}

const EXPORT_OPTIONS: { kind: string; label: string; description: string }[] = [
  { kind: "workbook.xlsx", label: "Excel workbook", description: "Cleaned data, KPIs, quality issues, exclusions, audit trail and insights" },
  { kind: "cleaned.csv", label: "Cleaned data (CSV)", description: "Contributing rows only, with MIERU's parsed date and net value" },
  { kind: "annotated.csv", label: "Annotated data (CSV)", description: "Every row with its exclusion reason and quality flags" },
  { kind: "report.html", label: "Executive report (HTML)", description: "Shareable summary of KPIs, insights and data quality" },
  { kind: "report.md", label: "Executive report (Markdown)", description: "Same report for docs, wikis or GitHub" },
];

export function ExportMenu({ datasetId, query }: { datasetId: string; query: string }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const items = () => Array.from(menuRef.current?.querySelectorAll<HTMLAnchorElement>('[role="menuitem"]') ?? []);
  const close = (restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  };

  useEffect(() => {
    if (open) items()[0]?.focus();
  }, [open]);

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const entries = items();
    const index = entries.findIndex((entry) => entry === document.activeElement);
    const move = (target: number) => {
      event.preventDefault();
      entries[(target + entries.length) % entries.length]?.focus();
    };
    if (event.key === "ArrowDown") move(index + 1);
    else if (event.key === "ArrowUp") move(index - 1);
    else if (event.key === "Home") move(0);
    else if (event.key === "End") move(entries.length - 1);
    else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "Tab") close(false);
  };

  return (
    <div className="dropdown">
      <button
        ref={triggerRef}
        type="button"
        className="btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? "export-menu" : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        Export
      </button>
      {open && (
        <>
          <div className="dropdown-backdrop" onClick={() => close(false)} aria-hidden="true" />
          <div className="dropdown-menu" role="menu" id="export-menu" aria-label="Export formats" ref={menuRef} onKeyDown={onMenuKeyDown}>
            {EXPORT_OPTIONS.map((option) => (
              <a
                key={option.kind}
                role="menuitem"
                tabIndex={-1}
                className="dropdown-item"
                href={`/api/datasets/${datasetId}/export/${option.kind}${query ? `?${query}` : ""}`}
                download
                onClick={() => close(true)}
              >
                <strong>{option.label}</strong>
                <span className="text-xs muted">{option.description}</span>
              </a>
            ))}
            <div className="dropdown-footnote text-xs muted" role="none">
              Exports use the current filters and cleaning policies. Spreadsheet formulas in your data are neutralised.
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export function SchemaBadges({ grain, basis, currency, rows }: { grain: string; basis: string | null; currency: string | null; rows: number }): ReactNode {
  return (
    <>
      <span className="badge">{formatNumber(rows)} rows</span>
      <span className="badge badge-accent">{GRAIN_LABELS[grain] ?? grain}</span>
      {basis && <span className="badge">{BASIS_LABELS[basis] ?? basis}</span>}
      <span className={`badge${currency ? "" : " badge-warning"}`}>{currency ?? "Currency not specified"}</span>
    </>
  );
}
