import { useQuery } from "@tanstack/react-query";
import { getJson } from "../../api/client";

export interface DatasetSummary {
  dataset_id: string;
  display_name: string;
  status: "queued" | "processing" | "ready" | "failed";
  stage: string;
  created_at: string;
  expires_at: string;
}

export function useDatasetList() {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: ({ signal }) => getJson<{ datasets: DatasetSummary[] }>("/api/datasets", signal),
    staleTime: 5_000,
    retry: false,
  });
}

export function useActiveDatasets(): DatasetSummary[] {
  const query = useDatasetList();
  return query.data?.datasets ?? [];
}
