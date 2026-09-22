import {
  Country,
  Indicator,
  Observation,
  GeoBoundariesCollection,
  PageResponse,
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`);
  if (!res.ok) {
    throw new Error(`API Error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const reimApi = {
  getCountries: async () => {
    const page = await fetchJson<PageResponse<Country>>("/api/v1/countries?limit=100");
    return page.data;
  },
  getIndicators: async () => {
    const page = await fetchJson<PageResponse<Indicator>>("/api/v1/indicators?limit=500");
    return page.data;
  },
  getBoundaries: (level: "country" | "administrative_area") =>
    fetchJson<GeoBoundariesCollection>(`/api/v1/geo/boundaries?level=${level}`),
  getObservations: async (params: {
    indicator_code: string;
    administrative_area?: string;
  }) => {
    const query = new URLSearchParams({
      indicator: params.indicator_code,
      limit: "1000",
    });
    if (params.administrative_area) {
      query.set("administrative_area", params.administrative_area);
    }
    const page = await fetchJson<PageResponse<Observation>>(`/api/v1/observations?${query.toString()}`);
    return page.data;
  },
};
