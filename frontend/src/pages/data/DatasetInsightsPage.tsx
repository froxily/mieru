import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../../api/client";
import { InsightsGrid, type InsightsPayload } from "../../components/InsightCards";
import { PageHeader } from "../../components/PageHeader";
import { PageSkeleton } from "../../components/Skeleton";
import { EmptyState, ErrorState } from "../../components/States";
import { DatasetTabs, FailedView, ProcessingView } from "../../features/datasets/DatasetChrome";
import { useDatasetStatus } from "../../features/datasets/queries";

export function DatasetInsightsPage() {
  const { datasetId = "" } = useParams();
  const status = useDatasetStatus(datasetId);
  const ready = status.data?.dataset.status === "ready";
  const insights = useQuery({
    queryKey: ["dataset", datasetId, "insights", status.data?.dataset.data_version],
    queryFn: ({ signal }) => getJson<InsightsPayload>(`/api/datasets/${datasetId}/insights`, signal),
    enabled: ready,
    staleTime: 60_000,
  });
  if (status.isPending) return <PageSkeleton />;
  if (status.isError) return <EmptyState title="Dataset not found" text="It may have expired, been deleted, or belong to another browser session." />;
  if (status.data.dataset.status === "failed") return <FailedView status={status.data} />;
  if (!ready) return <ProcessingView status={status.data} />;
  if (insights.isPending) return <PageSkeleton kpis={0} charts={4} />;
  if (insights.isError) return <ErrorState title="Could not generate insights" text={(insights.error as Error).message} />;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Your data · decision center"
        title={status.data.dataset.display_name}
        description="Findings that passed minimum-evidence gates on your data, with the numbers behind them. Rules that did not fire are listed with the reason."
        actions={<DatasetTabs datasetId={datasetId} active="insights" />}
      />
      <InsightsGrid payload={insights.data} metricReference={(metricId) => ({ source: "dataset", datasetId, metricId })} />
    </div>
  );
}
