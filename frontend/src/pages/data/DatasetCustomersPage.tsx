import { useParams } from "react-router-dom";
import { CustomerIntelligence } from "../../components/CustomerIntelligence";
import { PageHeader } from "../../components/PageHeader";
import { PageSkeleton } from "../../components/Skeleton";
import { EmptyState } from "../../components/States";
import { DatasetTabs, FailedView, ProcessingView } from "../../features/datasets/DatasetChrome";
import { useDatasetStatus } from "../../features/datasets/queries";

export function DatasetCustomersPage() {
  const { datasetId = "" } = useParams();
  const status = useDatasetStatus(datasetId);
  if (status.isPending) return <PageSkeleton />;
  if (status.isError) return <EmptyState title="Dataset not found" text="It may have expired, been deleted, or belong to another browser session." />;
  if (status.data.dataset.status === "failed") return <FailedView status={status.data} />;
  if (status.data.dataset.status !== "ready") return <ProcessingView status={status.data} />;
  return (
    <div className="page">
      <PageHeader
        eyebrow="Your data · customers"
        title={status.data.dataset.display_name}
        description="RFM segmentation, acquisition cohorts and a censoring-safe repeat rate, computed on the same contributing rows as the dashboard."
        actions={<DatasetTabs datasetId={datasetId} active="customers" />}
      />
      <CustomerIntelligence endpoint={`/api/datasets/${datasetId}/customers?v=${status.data.dataset.data_version}`} showCohorts />
    </div>
  );
}
