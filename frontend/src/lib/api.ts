import {
  Country,
  Indicator,
  Observation,
  GeoBoundariesCollection,
  PageResponse,
  ComparisonResponse,
} from "@/types/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const MAX_SERIES_PERIODS = 1500;

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
  getComparison: async (params: {
    indicator_code: string;
    countries: string[];
    date_from?: string;
    date_to?: string;
  }): Promise<ComparisonResponse> => {
    const makeUrl = (offset: number) => {
      const query = new URLSearchParams({
        indicator: params.indicator_code,
        order: "asc",
        limit: String(MAX_SERIES_PERIODS),
        offset: String(offset),
      });
      for (const country of params.countries) {
        query.append("country", country);
      }
      if (params.date_from) query.set("date_from", params.date_from);
      if (params.date_to) query.set("date_to", params.date_to);
      return `/api/v1/compare?${query.toString()}`;
    };

    const first = await fetchJson<ComparisonResponse>(makeUrl(0));
    if (first.meta.total > MAX_SERIES_PERIODS) return first;

    const data = [...first.data];
    if (first.meta.returned !== first.data.length) {
      throw new Error("Comparison page returned count does not match data");
    }
    if (first.meta.total > 0 && first.meta.returned === 0) {
      throw new Error("No comparison periods returned");
    }

    let offset = first.meta.returned;
    while (offset < first.meta.total) {
      const page = await fetchJson<ComparisonResponse>(makeUrl(offset));
      if (page.meta.returned === 0) {
        throw new Error("No comparison periods returned");
      }
      if (page.meta.returned !== page.data.length) {
        throw new Error("Comparison page returned count does not match data");
      }
      data.push(...page.data);
      offset += page.meta.returned;
    }

    return {
      ...first,
      data,
      meta: {
        ...first.meta,
        limit: MAX_SERIES_PERIODS,
        offset: 0,
        returned: data.length,
        has_more: false,
      },
    };
  },
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
