import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunsPage from "../page";

const mocks = vi.hoisted(() => ({
  id: null as string | null,
  runs: { data: undefined as unknown, isLoading: false, isError: false, error: null as Error | null },
  run: { data: undefined as unknown, isLoading: false, isError: false, error: null as Error | null },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.id ? `id=${mocks.id}` : ""),
}));

vi.mock("@/hooks/useReimApi", () => ({
  useRuns: () => mocks.runs,
  useRun: () => mocks.run,
}));

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: "run-1", pipeline_key: "worldbank_ni_cpi", source_id: null,
    connector_version: "2.1", pipeline_version: "1.4",
    started_at: "2026-09-22T12:00:00Z", finished_at: "2026-09-22T12:00:04Z", duration_ms: 4000,
    status: "success", records_extracted: 15, records_inserted: 12, records_updated: 2,
    records_unchanged: 1, records_rejected: 0, error_type: null, error_message: null,
    run_metadata: {}, created_at: "2026-09-22T12:00:04Z", ...overrides,
  };
}

describe("/runs page", () => {
  beforeEach(() => {
    mocks.id = null;
    mocks.runs = { data: { data: [run()], meta: { total: 145, limit: 100, offset: 0, returned: 1, has_more: true } }, isLoading: false, isError: false, error: null };
    mocks.run = { data: undefined, isLoading: false, isError: false, error: null };
  });

  it("shows recent run history, counters and the bounded history window", () => {
    render(<RunsPage />);
    expect(screen.getByRole("table", { name: /ejecuciones recientes/i })).toHaveTextContent("worldbank_ni_cpi");
    expect(screen.getByRole("table")).toHaveTextContent("Correcta");
    expect(screen.getByRole("table")).toHaveTextContent("12 / 2 / 0");
    expect(screen.getByText(/100 ejecuciones más recientes/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ver detalle/i })).toHaveAttribute("href", "/runs?id=run-1");
  });

  it("distinguishes loading, unavailable history and an empty history", () => {
    mocks.runs = { ...mocks.runs, isLoading: true };
    const { rerender } = render(<RunsPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/cargando historial/i);

    mocks.runs = { ...mocks.runs, isLoading: false, isError: true, error: new Error("API Error 503") };
    rerender(<RunsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("API Error 503");

    mocks.runs = { data: { data: [], meta: { total: 0, limit: 100, offset: 0, returned: 0, has_more: false } }, isLoading: false, isError: false, error: null };
    rerender(<RunsPage />);
    expect(screen.getByText(/ninguna ejecución registrada/i)).toBeInTheDocument();
  });

  it("renders detailed run metadata, all counters and quality checks", () => {
    mocks.id = "run-1";
    mocks.run = { data: {
      ...run({
        status: "failed", records_extracted: 20, records_inserted: 12, records_updated: 2,
        records_unchanged: 3, records_rejected: 3, error_type: "SourceUnavailable",
        error_message: "El editor no respondió", run_metadata: { file: "ipc.csv", rows: 20 },
      }),
      quality_checks: [{
        id: "check-1", check_name: "not_empty", check_type: "completeness", status: "failed",
        severity: "error", indicator_code: "ipc", period_label: "2026-08", expected_value: "1",
        actual_value: "0", details: {}, created_at: "2026-09-22T12:00:03Z",
      }],
    }, isLoading: false, isError: false, error: null };

    render(<RunsPage />);

    expect(screen.getByRole("heading", { name: /detalle de ejecución/i })).toBeInTheDocument();
    expect(screen.getByText("SourceUnavailable")).toBeInTheDocument();
    expect(screen.getByText("El editor no respondió")).toBeInTheDocument();
    expect(screen.getByText("20 / 12 / 2 / 3 / 3")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /verificaciones de calidad/i })).toHaveTextContent("not_empty");
    expect(screen.getByText("ipc.csv")).toBeInTheDocument();
  });

  it("shows loading, API errors and not-found states for a selected run", () => {
    mocks.id = "invalid-id";
    mocks.run = { ...mocks.run, isLoading: true };
    const { rerender } = render(<RunsPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/cargando detalle/i);

    mocks.run = { ...mocks.run, isLoading: false, isError: true, error: new Error("API Error 404: Not Found") };
    rerender(<RunsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent(/no se encontró esa ejecución/i);
  });
});
