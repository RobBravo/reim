import { describe, it, expect, vi, beforeEach } from "vitest";
import { reimApi } from "../api";

describe("reimApi client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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
});
