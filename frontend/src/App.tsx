import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PageSkeleton } from "./components/Skeleton";
import { EmptyState } from "./components/States";

const OverviewPage = lazy(() => import("./pages/olist/OverviewPage").then((module) => ({ default: module.OverviewPage })));
const DeliveryPage = lazy(() => import("./pages/olist/DeliveryPage").then((module) => ({ default: module.DeliveryPage })));
const CustomersPage = lazy(() => import("./pages/olist/CustomersPage").then((module) => ({ default: module.CustomersPage })));
const SellersPage = lazy(() => import("./pages/olist/SellersPage").then((module) => ({ default: module.SellersPage })));
const MarketsPage = lazy(() => import("./pages/olist/MarketsPage").then((module) => ({ default: module.MarketsPage })));
const OlistInsightsPage = lazy(() => import("./pages/olist/InsightsPage").then((module) => ({ default: module.OlistInsightsPage })));
const DatasetCustomersPage = lazy(() => import("./pages/data/DatasetCustomersPage").then((module) => ({ default: module.DatasetCustomersPage })));
const DatasetInsightsPage = lazy(() => import("./pages/data/DatasetInsightsPage").then((module) => ({ default: module.DatasetInsightsPage })));
const ResearchPage = lazy(() => import("./pages/olist/ResearchPage").then((module) => ({ default: module.ResearchPage })));
const UploadPage = lazy(() => import("./pages/data/UploadPage").then((module) => ({ default: module.UploadPage })));
const DatasetDashboardPage = lazy(() => import("./pages/data/DatasetDashboardPage").then((module) => ({ default: module.DatasetDashboardPage })));
const DatasetPerformancePage = lazy(() => import("./pages/data/DatasetPerformancePage").then((module) => ({ default: module.DatasetPerformancePage })));
const DataQualityPage = lazy(() => import("./pages/data/DataQualityPage").then((module) => ({ default: module.DataQualityPage })));

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<PageSkeleton />}>
        <Routes>
          <Route path="/" element={<Navigate to="/olist/overview" replace />} />
          <Route path="/olist" element={<Navigate to="/olist/overview" replace />} />
          <Route path="/olist/overview" element={<OverviewPage />} />
          <Route path="/olist/delivery" element={<DeliveryPage />} />
          <Route path="/olist/customers" element={<CustomersPage />} />
          <Route path="/olist/sellers" element={<SellersPage />} />
          <Route path="/olist/markets" element={<MarketsPage />} />
          <Route path="/olist/insights" element={<OlistInsightsPage />} />
          <Route path="/olist/research" element={<ResearchPage />} />
          <Route path="/data" element={<UploadPage />} />
          <Route path="/data/:datasetId" element={<DatasetDashboardPage />} />
          <Route path="/data/:datasetId/performance" element={<DatasetPerformancePage />} />
          <Route path="/data/:datasetId/quality" element={<DataQualityPage />} />
          <Route path="/data/:datasetId/insights" element={<DatasetInsightsPage />} />
          <Route path="/data/:datasetId/customers" element={<DatasetCustomersPage />} />
          <Route
            path="*"
            element={
              <EmptyState title="Page not found" text="This page does not exist. Use the navigation to open the Olist demo or upload your own spreadsheet." />
            }
          />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
