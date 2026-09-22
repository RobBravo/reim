import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CatalogPage from "../page";

const mocks = vi.hoisted(() => ({
  sources: { data: [] as Array<Record<string, unknown>>, isLoading: false, isError: false, error: null as Error | null },
  organizations: { data: [] as Array<Record<string, unknown>>, isLoading: false, isError: false, error: null as Error | null },
  pipelines: { data: [] as Array<Record<string, unknown>>, isLoading: false, isError: false, error: null as Error | null },
}));

vi.mock("@/hooks/useReimApi", () => ({
  useSources: () => mocks.sources,
  useOrganizations: () => mocks.organizations,
  usePipelineSummaries: () => mocks.pipelines,
}));

function source(overrides: Record<string, unknown> = {}) {
  return {
    id: "source-1", source_key: "worldbank_ni_cpi", name: "Inflación de Nicaragua", description: "IPC",
    frequency: "annual", license: "CC-BY-4.0", documentation_url: "https://example.test/source",
    base_url: "https://example.test", is_official: true, is_active: true, disabled_reason: null,
    organization_id: "org-1", ...overrides,
  };
}

function pipeline(overrides: Record<string, unknown> = {}) {
  return {
    source_key: "worldbank_ni_cpi", indicators: ["ipc", "inflation"],
    last_run_status: "success", last_run_at: "2026-09-22T12:00:00Z", last_success_at: "2026-09-22T12:00:00Z",
    records_inserted_last_run: 12, records_updated_last_run: 2, records_rejected_last_run: 0,
    ...overrides,
  };
}

describe("/catalog page", () => {
  beforeEach(() => {
    mocks.sources = { data: [source()], isLoading: false, isError: false, error: null };
    mocks.organizations = { data: [{ id: "org-1", name: "Banco Mundial", short_name: "BM" }], isLoading: false, isError: false, error: null };
    mocks.pipelines = { data: [pipeline()], isLoading: false, isError: false, error: null };
  });

  it("joins the source organization and shows catalog and latest-run details", () => {
    render(<CatalogPage />);
    expect(screen.getByRole("table", { name: /fuentes de datos registradas/i })).toHaveTextContent("Banco Mundial");
    expect(screen.getByRole("table")).toHaveTextContent("Inflación de Nicaragua");
    expect(screen.getByRole("table")).toHaveTextContent("2");
    expect(screen.getByRole("table")).toHaveTextContent("12 / 2 / 0");
    expect(screen.getByRole("link", { name: "Inflación de Nicaragua" })).toHaveAttribute("href", "https://example.test/source");
  });

  it("shows loading state while source metadata is being fetched", () => {
    mocks.sources = { ...mocks.sources, isLoading: true };
    render(<CatalogPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/Cargando catálogo/);
  });

  it("offers the legacy catalog if the API cannot load source metadata", () => {
    mocks.sources = { ...mocks.sources, isError: true, error: new Error("API Error 503") };
    render(<CatalogPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("API Error 503");
    expect(screen.getByRole("link", { name: /catálogo anterior/i })).toHaveAttribute("href", "/legacy");
  });

  it("keeps catalog metadata visible when pipeline freshness is unavailable", () => {
    mocks.pipelines = { ...mocks.pipelines, isError: true, error: new Error("API Error 503") };
    render(<CatalogPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/actualización no está disponible/);
    expect(screen.getByRole("table")).toHaveTextContent("Inflación de Nicaragua");
    expect(screen.getByRole("table")).toHaveTextContent("—");
  });

  it("marks non-open licenses and explicitly names an empty disabled-source section", () => {
    mocks.sources = { data: [source({ license: "CEPAL terms", source_key: "cepal_monthly_cpi" })], isLoading: false, isError: false, error: null };
    mocks.pipelines = { data: [pipeline({ source_key: "cepal_monthly_cpi" })], isLoading: false, isError: false, error: null };
    render(<CatalogPage />);
    expect(screen.getByText("No abierto")).toBeInTheDocument();
    expect(screen.getByText("No hay fuentes deshabilitadas.")).toBeInTheDocument();
  });

  it("distinguishes a source that has never run from unavailable freshness", () => {
    mocks.pipelines = { data: [pipeline({ last_run_status: null, last_success_at: null })], isLoading: false, isError: false, error: null };
    render(<CatalogPage />);
    expect(screen.getByRole("table")).toHaveTextContent("Nunca ejecutada");
  });

  it("states when the catalog contains no sources", () => {
    mocks.sources = { data: [], isLoading: false, isError: false, error: null };
    mocks.pipelines = { data: [], isLoading: false, isError: false, error: null };
    render(<CatalogPage />);
    expect(screen.getByText("No hay fuentes registradas en el catálogo.")).toBeInTheDocument();
    expect(screen.getByText("No hay fuentes deshabilitadas.")).toBeInTheDocument();
  });

  it("names disabled sources with their recorded reason", () => {
    mocks.sources = { data: [source({ is_active: false, disabled_reason: "El editor bloqueó el acceso." })], isLoading: false, isError: false, error: null };
    render(<CatalogPage />);
    expect(screen.getByText(/El editor bloqueó el acceso/)).toBeInTheDocument();
  });
});
