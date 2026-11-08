import { useState, type CSSProperties } from "react";
import { formatMetricValue, type MetricUnit } from "../lib/format";
import { IconAlert, IconCheck, IconInfo, IconShield, IconSparkle } from "./icons";
import { useMetricDebugger, type MetricReference } from "./MetricDebugger";

export interface InsightEvidence {
  label: string;
  value: number | null;
  unit: MetricUnit;
  currency: string | null;
  metric_id: string | null;
}

export interface Insight {
  insight_id: string;
  kind: "opportunity" | "risk" | "info" | "quality";
  confidence: "high" | "medium";
  finding: string;
  evidence: InsightEvidence[];
  interpretation: string;
  action: string;
  limitations: string[];
  gates: string[];
}

export interface InsightsPayload {
  cards: Insight[];
  skipped: { rule: string; reason: string }[];
  rules_evaluated: number;
  method: string;
  currency?: string | null;
}

const KIND_META: Record<Insight["kind"], { label: string; badge: string; icon: typeof IconInfo }> = {
  risk: { label: "Risk", badge: "badge-breach", icon: IconAlert },
  opportunity: { label: "Opportunity", badge: "badge-good", icon: IconSparkle },
  info: { label: "Finding", badge: "badge-accent", icon: IconInfo },
  quality: { label: "Data quality", badge: "badge-warning", icon: IconShield },
};

function formatEvidence(item: InsightEvidence): string {
  if (item.unit === "index") {
    if (item.value === null) return "—";
    return Math.abs(item.value) < 0.01 && item.value !== 0 ? item.value.toExponential(1) : item.value.toFixed(2);
  }
  return formatMetricValue(item.value, item.unit, item.currency);
}

export function InsightCardView({
  insight,
  metricReference,
  stagger,
}: {
  insight: Insight;
  metricReference?: (metricId: string) => MetricReference;
  stagger: number;
}) {
  const { open } = useMetricDebugger();
  const meta = KIND_META[insight.kind];
  const Icon = meta.icon;
  return (
    <article className="card card-interactive insight" style={{ "--stagger": stagger } as CSSProperties} aria-label={insight.finding}>
      <div className="card-body stack" style={{ gap: 14, padding: 20 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <span className={`badge ${meta.badge}`}>
            <Icon width={13} height={13} /> {meta.label}
          </span>
          <span className="text-xs muted">{insight.confidence === "high" ? "High confidence" : "Medium confidence"}</span>
        </div>
        <h3 style={{ fontSize: "1.0625rem", lineHeight: 1.4 }}>{insight.finding}</h3>
        <dl className="kv insight-evidence">
          {insight.evidence.map((item) => (
            <InsightEvidenceRow
              key={item.label}
              item={item}
              onTrace={item.metric_id && metricReference ? () => open(metricReference(item.metric_id as string)) : undefined}
            />
          ))}
        </dl>
        <div className="stack" style={{ gap: 6 }}>
          <span className="highlight-title">What it means</span>
          <p className="text-sm">{insight.interpretation}</p>
        </div>
        <div className="insight-action">
          <IconCheck width={15} height={15} />
          <p className="text-sm">
            <strong>Suggested action: </strong>
            {insight.action}
          </p>
        </div>
        <details className="insight-details">
          <summary className="text-xs">Assumptions, limitations & evidence gates</summary>
          <ul className="list" style={{ marginTop: 8 }}>
            {insight.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
            {insight.gates.map((gate) => (
              <li key={gate}>Gate: {gate}</li>
            ))}
          </ul>
        </details>
      </div>
    </article>
  );
}

function InsightEvidenceRow({ item, onTrace }: { item: InsightEvidence; onTrace?: () => void }) {
  return (
    <>
      <dt>{item.label}</dt>
      <dd>
        <strong className="tabular">{formatEvidence(item)}</strong>
        {onTrace && (
          <button type="button" className="btn btn-ghost btn-sm" style={{ marginLeft: 6, height: 22 }} onClick={onTrace}>
            trace
          </button>
        )}
      </dd>
    </>
  );
}

export function InsightsGrid({ payload, metricReference }: { payload: InsightsPayload; metricReference?: (metricId: string) => MetricReference }) {
  const [showSkipped, setShowSkipped] = useState(false);
  return (
    <div className="stack" style={{ gap: 20 }}>
      {payload.cards.length === 0 ? (
        <div className="callout callout-info">
          <IconInfo className="callout-icon" />
          <div className="callout-body">
            <strong>No insight passed its evidence gates</strong>
            <span>MIERU only shows findings backed by enough data. See the rules that were evaluated below.</span>
          </div>
        </div>
      ) : (
        <div className="grid grid-2">
          {payload.cards.map((insight, index) => (
            <InsightCardView key={insight.insight_id} insight={insight} metricReference={metricReference} stagger={index} />
          ))}
        </div>
      )}
      <div className="row row-wrap" style={{ justifyContent: "space-between" }}>
        <span className="text-xs muted">{payload.method}</span>
        {payload.skipped.length > 0 && (
          <button type="button" className="btn btn-sm" onClick={() => setShowSkipped((value) => !value)} aria-expanded={showSkipped}>
            {showSkipped ? "Hide" : "Show"} {payload.skipped.length} rule{payload.skipped.length === 1 ? "" : "s"} that did not fire
          </button>
        )}
      </div>
      {showSkipped && (
        <div className="card">
          <div className="card-body">
            <ul className="list">
              {payload.skipped.map((item) => (
                <li key={`${item.rule}-${item.reason}`}>
                  <strong>{item.rule.replace(/_/g, " ")}</strong>: {item.reason}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
