import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { reimApi } from "@/lib/api";
import { ComparisonResponse } from "@/types/api";
import { useComparison } from "../useReimApi";

function comparisonResponse(value: number): ComparisonResponse {
  return {
    meta: { total: 1, limit: 1500, offset: 0, returned: 1, has_more: false },
    indicator: { code: "ipc", name: "Índice de precios", frequency: "monthly" },
    comparable: true,
    levels_comparable: true,
    comparability_notes: [],
    series: [
      {
        country_iso2: "NI",
        country_iso3: "NIC",
        country_name: "Nicaragua",
        units: ["index"],
        currency_codes: [null],
        source_keys: ["inide"],
        organization_codes: ["INIDE"],
        observations: 1,
        first_period: "2020-01",
        last_period: "2020-01",
      },
    ],
    data: [
      {
        period_start: "2020-01-01",
        period_end: "2020-01-31",
        period_label: "2020-01",
        values: { NIC: value },
      },
    ],
  };
}

describe("useComparison", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not request comparison data without an indicator and a country", () => {
    const apiCall = vi.spyOn(reimApi, "getComparison");
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useComparison("", []), { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("uses separate cached results for different date bounds", async () => {
    const apiCall = vi.spyOn(reimApi, "getComparison").mockImplementation(async ({ date_to }) =>
      comparisonResponse(date_to === "2020-12-31" ? 100 : 200)
    );
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ dateTo }: { dateTo: string }) => useComparison("ipc", ["NIC"], undefined, dateTo),
      { wrapper, initialProps: { dateTo: "2020-12-31" } }
    );

    await waitFor(() => expect(result.current.data?.data[0].values.NIC).toBe(100));
    rerender({ dateTo: "2021-12-31" });
    await waitFor(() => expect(result.current.data?.data[0].values.NIC).toBe(200));

    const dateKeys = client.getQueryCache().getAll().map((query) => query.queryKey);
    expect(dateKeys).toContainEqual(["comparison", "ipc", ["NIC"], undefined, "2020-12-31"]);
    expect(dateKeys).toContainEqual(["comparison", "ipc", ["NIC"], undefined, "2021-12-31"]);
    expect(apiCall).toHaveBeenCalledTimes(2);
  });
});
