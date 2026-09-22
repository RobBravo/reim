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

export function useObservations(indicatorCode?: string, administrativeArea?: string) {
  return useQuery({
    queryKey: ["observations", indicatorCode, administrativeArea],
    queryFn: () =>
      indicatorCode
        ? reimApi.getObservations({ indicator_code: indicatorCode, administrative_area: administrativeArea })
        : Promise.resolve([]),
    enabled: Boolean(indicatorCode),
  });
}
