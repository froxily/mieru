import type { OlistResearch, ResearchModel } from "../../api/types";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { PageHeader, SectionTitle } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";
import { Callout } from "../../components/States";
import { formatNumber, formatPValue } from "../../lib/format";
import { useOlistResearch } from "../../features/olist/queries";

const TERM_LABELS: Record<string, string> = {
  const: "Intercept",
  is_sla_breached: "SLA breached",
  is_severe_detractor: "1–2★ review on first order",
  log_order_gmv: "log(1 + order GMV)",
  freight_ratio: "Freight share of GMV",
  log_distance_km: "log(1 + distance km)",
};

const MODEL_ORDER: [string, string][] = [
  ["model_1_severe_detractor", "Model 1 · P(1–2★ review)"],
  ["model_2_repeat_buyer", "Model 2 · P(repeat buyer)"],
  ["model_2b_repeat_buyer_detractor_exposure", "Model 2b · detractor exposure"],
  ["model_2c_repeat_within_180d_after_delivery", "Model 2c · 180-day repeat"],
];

function ModelTermsTable({ model }: { model: ResearchModel }) {
  const terms = (model.terms ?? []).filter((term) => term.term !== "const");
  return (
    <DataTable
      rows={terms}
      rowKey={(row) => row.term}
      dense
      columns={[
        {
          key: "term",
          header: "Predictor",
          render: (row) => (row.term === model.exposure ? <strong>{TERM_LABELS[row.term] ?? row.term}</strong> : (TERM_LABELS[row.term] ?? row.term)),
        },
        { key: "or", header: "Adjusted OR", align: "right", render: (row) => row.odds_ratio.toFixed(2) },
        { key: "ci", header: "95% CI (HC0)", align: "right", render: (row) => `${row.or_ci_low.toFixed(2)} – ${row.or_ci_high.toFixed(2)}` },
        { key: "p", header: "p", align: "right", render: (row) => formatPValue(row.p_value) },
      ]}
    />
  );
}

function ResearchContent({ data }: { data: OlistResearch }) {
  const fixedEffects = data.models.model_1_fixed_effects_robustness;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Olist marketplace · research"
        title="Research findings"
        description="The original reproducible study (DuckDB marts, Welch / Mann–Whitney / χ² tests, logistic regression with HC0 robust standard errors) preserved inside MIERU. Numbers are read from the frozen pipeline output."
      />
      <Card stagger={0}>
        <div className="stack">
          <span className="page-eyebrow" style={{ margin: 0 }}>
            Headline
          </span>
          <p style={{ fontSize: "1.25rem", lineHeight: 1.45, fontFamily: "var(--font-display)", color: "var(--ink-1)" }}>{data.headline.sentence}</p>
          <span className="text-xs muted">
            Pipeline output generated {data.metadata.generated_at_utc.replace("T", " ").replace("+00:00", " UTC")} · random seed {data.metadata.random_seed}
          </span>
        </div>
      </Card>

      <div className="grid grid-2">
        {MODEL_ORDER.map(([key, label], index) => {
          const model = data.models[key];
          if (!model) return null;
          return (
            <Card
              key={key}
              title={label}
              subtitle={`n = ${formatNumber(model.n_obs)} · events = ${formatNumber(model.n_events)} · McFadden R² = ${model.pseudo_r2_mcfadden?.toFixed(3)} · AUC = ${model.roc_auc?.toFixed(2)}`}
              stagger={index}
            >
              <ModelTermsTable model={model} />
            </Card>
          );
        })}
      </div>
      {fixedEffects?.odds_ratio && fixedEffects.odds_ratio_ci && (
        <Callout tone="info" title="Robustness">
          Adding customer-state and purchase-month fixed effects barely moves the breach odds ratio: {fixedEffects.odds_ratio.toFixed(2)} (95% CI{" "}
          {fixedEffects.odds_ratio_ci[0].toFixed(2)}–{fixedEffects.odds_ratio_ci[1].toFixed(2)}, n = {formatNumber(fixedEffects.n_obs)}).
        </Callout>
      )}

      <SectionTitle title="Caveats" description="What these results do and do not show." />
      <Card stagger={1}>
        <ul className="list">
          {data.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
        </ul>
      </Card>

      <SectionTitle title="Publication figures" description="300-DPI figures rendered by the research pipeline (src/plotting.py)." />
      <div className="grid grid-2">
        {data.figures.map((figure, index) => (
          <Card key={figure.file_name} title={figure.title} stagger={index}>
            <a href={figure.url} target="_blank" rel="noreferrer">
              <img className="figure-img" src={figure.url} alt={figure.title} loading="lazy" />
            </a>
          </Card>
        ))}
      </div>
      <p className="text-xs muted">{data.attribution}</p>
    </div>
  );
}

export function ResearchPage() {
  const query = useOlistResearch();
  return <QueryBoundary query={query}>{(data) => <ResearchContent data={data} />}</QueryBoundary>;
}
