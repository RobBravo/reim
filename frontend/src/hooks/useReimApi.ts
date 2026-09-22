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

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: reimApi.getSources,
  });
}

export function useOrganizations() {
  return useQuery({
    queryKey: ["organizations"],
    queryFn: reimApi.getOrganizations,
  });
}

export function usePipelineSummaries() {
  return useQuery({
    queryKey: ["pipeline-summaries"],
    queryFn: reimApi.getPipelineSummaries,
  });
}

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: reimApi.getRuns,
  });
}

export function useRun(runId?: string | null) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => {
      if (!runId) throw new Error("A run ID is required");
      return reimApi.getRun(runId);
    },
    enabled: Boolean(runId),
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

export function useComparison(
  indicatorCode?: string,
  countries: string[] = [],
  dateFrom?: string,
  dateTo?: string
) {
  const enabled = Boolean(indicatorCode && countries.length > 0);

  return useQuery({
    queryKey: ["comparison", indicatorCode, countries, dateFrom, dateTo],
    queryFn: () => {
      if (!indicatorCode || countries.length === 0) {
        throw new Error("An indicator and at least one country are required");
      }
      return reimApi.getComparison({
        indicator_code: indicatorCode,
        countries,
        date_from: dateFrom,
        date_to: dateTo,
      });
    },
    enabled,
  });
}
