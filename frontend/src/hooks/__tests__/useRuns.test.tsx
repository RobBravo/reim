import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { reimApi } from "@/lib/api";
import { PipelineRunDetail } from "@/types/api";
import { useRun, useRuns } from "../useReimApi";

function wrapperFor(client: QueryClient) {
  function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return QueryWrapper;
}

describe("run history hooks", () => {
  afterEach(() => vi.restoreAllMocks());

  it("loads the run page into the history query", async () => {
    const response = { data: [], meta: { total: 0, limit: 100, offset: 0, returned: 0, has_more: false } };
    const request = vi.spyOn(reimApi, "getRuns").mockResolvedValue(response);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useRuns(), { wrapper: wrapperFor(client) });

    await waitFor(() => expect(result.current.data).toEqual(response));
    expect(client.getQueryCache().getAll().map((query) => query.queryKey)).toContainEqual(["runs"]);
    expect(request).toHaveBeenCalledOnce();
  });

  it("does not request a detail until a run ID is selected", async () => {
    const detail: PipelineRunDetail = {
      id: "run-1", pipeline_key: "source_a", source_id: null, connector_version: null,
      pipeline_version: null, started_at: "2026-09-22T12:00:00Z", finished_at: null,
      duration_ms: null, status: "running", records_extracted: 0, records_inserted: 0,
      records_updated: 0, records_unchanged: 0, records_rejected: 0, error_type: null,
      error_message: null, run_metadata: {}, created_at: "2026-09-22T12:00:00Z", quality_checks: [],
    };
    const request = vi.spyOn(reimApi, "getRun").mockResolvedValue(detail);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useRun(id), {
      wrapper: wrapperFor(client), initialProps: { id: null as string | null },
    });

    expect(result.current.fetchStatus).toBe("idle");
    expect(request).not.toHaveBeenCalled();
    rerender({ id: "run-1" });
    await waitFor(() => expect(result.current.data?.id).toBe("run-1"));
    expect(request).toHaveBeenCalledWith("run-1");
  });
});
