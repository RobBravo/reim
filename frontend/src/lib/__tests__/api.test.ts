import { describe, it, expect, vi, beforeEach } from "vitest";
import { reimApi } from "../api";

describe("reimApi client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches countries successfully", async () => {
    const mockCountries = [{ id: "1", iso2: "NI", name: "Nicaragua" }];
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockCountries,
    });

    const data = await reimApi.getCountries();
    expect(fetch).toHaveBeenCalledWith("/api/v1/countries");
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
