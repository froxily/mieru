import { useQuery } from "@tanstack/react-query";
import { getJson } from "../../api/client";
import { InsightsGrid, type InsightsPayload } from "../../components/InsightCards";
import { PageHeader } from "../../components/PageHeader";
import { QueryBoundary } from "../../components/QueryBoundary";

export function OlistInsightsPage() {
  const query = useQuery({
    queryKey: ["olist", "insights"],
    queryFn: ({ signal }) => getJson<InsightsPayload>("/api/olist/insights", signal),
    staleTime: Infinity,
  });
  return (
    <QueryBoundary query={query}>
      {(payload) => (
        <div className="page">
          <PageHeader
            eyebrow="Olist marketplace · decision center"
            title="What to act on"
            description="Evidence-backed findings, each with the supporting numbers, an interpretation, a concrete action and its limitations. Generated deterministically from the warehouse and the research models — no external AI."
          />
          <InsightsGrid payload={payload} metricReference={(metricId) => ({ source: "olist", metricId })} />
        </div>
      )}
    </QueryBoundary>
  );
}
