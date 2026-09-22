import { useQuery } from "@tanstack/react-query";
import { reimApi } from "@/lib/api";

export function useCountries() {
  return useQuery({
    queryKey: ["countries"],
    queryFn: reimApi.getCountries,
  });
}

export function useIndicators() {
  return useQuery({
    queryKey: ["indicators"],
    queryFn: reimApi.getIndicators,
  });
}

export function useBoundaries(level: "country" | "administrative_area") {
  return useQuery({
    queryKey: ["boundaries", level],
    queryFn: () => reimApi.getBoundaries(level),
    staleTime: Infinity, // Geometries never change during a session
  });
}

export function useObservations(indicatorId?: string) {
  return useQuery({
    queryKey: ["observations", indicatorId],
    queryFn: () =>
      indicatorId ? reimApi.getObservations({ indicator_id: indicatorId }) : Promise.resolve([]),
    enabled: Boolean(indicatorId),
  });
}
