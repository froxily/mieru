import { useQuery } from "@tanstack/react-query";
import { getJson } from "../../api/client";
import type { OlistCustomers, OlistDelivery, OlistMarkets, OlistOverview, OlistResearch, OlistSellers } from "../../api/types";

const STATIC_DATA = { staleTime: Infinity, gcTime: Infinity, retry: 1 } as const;

export function useOlistOverview() {
  return useQuery({ queryKey: ["olist", "overview"], queryFn: ({ signal }) => getJson<OlistOverview>("/api/olist/overview", signal), ...STATIC_DATA });
}

export function useOlistDelivery() {
  return useQuery({ queryKey: ["olist", "delivery"], queryFn: ({ signal }) => getJson<OlistDelivery>("/api/olist/delivery", signal), ...STATIC_DATA });
}

export function useOlistCustomers() {
  return useQuery({ queryKey: ["olist", "customers"], queryFn: ({ signal }) => getJson<OlistCustomers>("/api/olist/customers", signal), ...STATIC_DATA });
}

export function useOlistSellers() {
  return useQuery({ queryKey: ["olist", "sellers"], queryFn: ({ signal }) => getJson<OlistSellers>("/api/olist/sellers", signal), ...STATIC_DATA });
}

export function useOlistResearch() {
  return useQuery({ queryKey: ["olist", "research"], queryFn: ({ signal }) => getJson<OlistResearch>("/api/olist/research", signal), ...STATIC_DATA });
}

export function useOlistMarkets() {
  return useQuery({ queryKey: ["olist", "markets"], queryFn: ({ signal }) => getJson<OlistMarkets>("/api/olist/markets", signal), ...STATIC_DATA });
}
