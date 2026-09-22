import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { reimApi } from "../api";

const comparisonSummary = {
  country_iso2: "NI",
  country_iso3: "NIC",
  country_name: "Nicaragua",
  units: ["percent"],
  currency_codes: [null],
  source_keys: ["inide"],
  organization_codes: ["INIDE"],
  observations: 1,
  first_period: "2020-01",
  last_period: "2020-01",
};

function comparisonPage({
  total,
  limit,
  offset,
  returned,
}: {
  total: number;
  limit: number;
  offset: number;
  returned: number;
}) {
  const data = Array.from({ length: returned }, (_, index) => {
    const period = offset + index;
    const year = 2020 + Math.floor(period / 12);
    const month = String((period % 12) + 1).padStart(2, "0");
    const periodStart = `${year}-${month}-01`;
    return {
      period_start: periodStart,
      period_end: periodStart,
      period_label: `period-${period}`,
      values: { NIC: period },
    };
  });

  return {
    indicator: { code: "ipc", name: "Índice de precios", frequency: "monthly" },
    comparable: true,
    levels_comparable: true,
    comparability_notes: [],
    series: [comparisonSummary],
    data,
    meta: {
      total,
      limit,
      offset,
      returned,
      has_more: offset + returned < total,
    },
  };
}

function jsonResponse(body: unknown) {
  return { ok: true, json: async () => body };
}

describe("reimApi client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches and unwraps countries successfully", async () => {
    const mockCountries = [{ id: "1", iso2: "NI", name: "Nicaragua" }];
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: mockCountries,
        meta: { total: 1, limit: 100, offset: 0, returned: 1, has_more: false },
      }),
    });

    const data = await reimApi.getCountries();
    expect(fetch).toHaveBeenCalledWith("/api/v1/countries?limit=100");
    expect(data).toEqual(mockCountries);
  });

  it("throws on HTTP error response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    await expect(reimApi.getCountries()).rejects.toThrow("API Error 500");
  });

  it("fetches repeated countries and follows the API's capped page size", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(comparisonPage({ total: 1200, limit: 1000, offset: 0, returned: 1000 })))
      .mockResolvedValueOnce(jsonResponse(comparisonPage({ total: 1200, limit: 1000, offset: 1000, returned: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    const result = await reimApi.getComparison({
      indicator_code: "ipc",
      countries: ["NIC", "GTM"],
      date_from: "2000-01-01",
      date_to: "2025-12-31",
    });

    const firstUrl = new URL(fetchMock.mock.calls[0][0] as string, "http://localhost");
    const secondUrl = new URL(fetchMock.mock.calls[1][0] as string, "http://localhost");
    expect(firstUrl.pathname).toBe("/api/v1/compare");
    expect(firstUrl.searchParams.get("indicator")).toBe("ipc");
    expect(firstUrl.searchParams.getAll("country")).toEqual(["NIC", "GTM"]);
    expect(firstUrl.searchParams.get("date_from")).toBe("2000-01-01");
    expect(firstUrl.searchParams.get("date_to")).toBe("2025-12-31");
    expect(firstUrl.searchParams.get("order")).toBe("asc");
    expect(firstUrl.searchParams.get("limit")).toBe("1500");
    expect(firstUrl.searchParams.get("offset")).toBe("0");
    expect(secondUrl.searchParams.get("offset")).toBe("1000");
    expect(result.data).toHaveLength(1200);
    expect(result.data[0].period_label).toBe("period-0");
    expect(result.data[1199].period_label).toBe("period-1199");
  });

  it("omits absent date bounds and stops fetching when over the period cap", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(comparisonPage({ total: 1800, limit: 1000, offset: 0, returned: 1000 }))
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await reimApi.getComparison({ indicator_code: "ipc", countries: ["NIC"] });
    const url = new URL(fetchMock.mock.calls[0][0] as string, "http://localhost");

    expect(url.searchParams.has("date_from")).toBe(false);
    expect(url.searchParams.has("date_to")).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.meta.total).toBe(1800);
    expect(result.data).toHaveLength(1000);
  });

  it("rejects a page that makes no progress toward the requested periods", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(comparisonPage({ total: 1200, limit: 1000, offset: 0, returned: 0 }))
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(reimApi.getComparison({ indicator_code: "ipc", countries: ["NIC"] }))
      .rejects.toThrow("No comparison periods returned");
  });
});
