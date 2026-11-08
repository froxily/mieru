import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson, sendJson } from "../../api/client";
import type { DatasetDashboard, DatasetFilters, DatasetPerformance, DatasetQuality, DatasetStatusPayload } from "../../api/datasetTypes";

export function filtersToQuery(filters: DatasetFilters): string {
  const params = new URLSearchParams();
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  filters.categories.forEach((value) => params.append("category", value));
  filters.regions.forEach((value) => params.append("region", value));
  filters.channels.forEach((value) => params.append("channel", value));
  return params.toString();
}

export const EMPTY_FILTERS: DatasetFilters = { start: null, end: null, categories: [], regions: [], channels: [] };

export function useDatasetStatus(datasetId: string) {
  return useQuery({
    queryKey: ["dataset", datasetId, "status"],
    queryFn: ({ signal }) => getJson<DatasetStatusPayload>(`/api/datasets/${datasetId}`, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.dataset.status;
      return status === "ready" || status === "failed" ? false : 600;
    },
    retry: false,
  });
}

export function useDatasetDashboard(datasetId: string, dataVersion: number | undefined, filters: DatasetFilters, enabled: boolean) {
  const query = filtersToQuery(filters);
  return useQuery({
    queryKey: ["dataset", datasetId, "dashboard", dataVersion, query],
    queryFn: ({ signal }) => getJson<DatasetDashboard>(`/api/datasets/${datasetId}/dashboard${query ? `?${query}` : ""}`, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useDatasetPerformance(datasetId: string, dataVersion: number | undefined, filters: DatasetFilters, enabled: boolean) {
  const query = filtersToQuery(filters);
  return useQuery({
    queryKey: ["dataset", datasetId, "performance", dataVersion, query],
    queryFn: ({ signal }) => getJson<DatasetPerformance>(`/api/datasets/${datasetId}/performance${query ? `?${query}` : ""}`, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useDatasetQuality(datasetId: string, dataVersion: number | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["dataset", datasetId, "quality", dataVersion],
    queryFn: ({ signal }) => getJson<DatasetQuality>(`/api/datasets/${datasetId}/quality`, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useUpdatePolicies(datasetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (policies: Record<string, boolean>) => sendJson(`/api/datasets/${datasetId}/policies`, "PUT", { policies }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["dataset", datasetId] });
      void client.invalidateQueries({ queryKey: ["metric-explain"] });
    },
  });
}

export function useUpdateMapping(datasetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (mapping: Record<string, string | null>) => sendJson(`/api/datasets/${datasetId}/mapping`, "PUT", { mapping }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["dataset", datasetId] });
      void client.invalidateQueries({ queryKey: ["datasets"] });
      void client.invalidateQueries({ queryKey: ["metric-explain"] });
    },
  });
}

export function useDeleteDataset(datasetId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => sendJson(`/api/datasets/${datasetId}`, "DELETE"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["datasets"] });
    },
  });
}
