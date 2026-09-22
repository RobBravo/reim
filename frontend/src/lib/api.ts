import {
  Country,
  Indicator,
  Observation,
  GeoBoundariesCollection,
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
  getCountries: () => fetchJson<Country[]>("/api/v1/countries"),
  getIndicators: () => fetchJson<Indicator[]>("/api/v1/indicators"),
  getBoundaries: (level: "country" | "administrative_area") =>
    fetchJson<GeoBoundariesCollection>(`/api/v1/geo/boundaries?level=${level}`),
  getObservations: (params: {
    indicator_id: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const query = new URLSearchParams({
      indicator_id: params.indicator_id,
      page_size: "1000",
    });
    if (params.start_date) query.set("start_date", params.start_date);
    if (params.end_date) query.set("end_date", params.end_date);
    return fetchJson<Observation[]>(`/api/v1/observations?${query.toString()}`);
  },
};
