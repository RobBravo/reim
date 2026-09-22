import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SeriesPage from "../page";

const mocks = vi.hoisted(() => ({
  search: "",
  comparison: { data: undefined as unknown, isLoading: false, isFetching: false, isError: false, error: null as Error | null },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.search),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/hooks/useReimApi", () => ({
  useIndicators: () => ({ data: [{ code: "GDP", name: "PIB" }], isLoading: false, isError: false }),
  useCountries: () => ({ data: [{ iso3: "NIC", name: "Nicaragua", is_active: true }, { iso3: "CRI", name: "Costa Rica", is_active: true }], isLoading: false, isError: false }),
  useComparison: () => mocks.comparison,
}));
vi.mock("@/components/series/SeriesChart", () => ({
  SeriesChart: ({ title }: { title: string }) => <div data-testid="series-chart">{title}</div>,
}));

function response(options: { total?: number; comparable?: boolean; levelsComparable?: boolean; series?: Array<Record<string, unknown>> } = {}) {
  const series = options.series ?? [{ country_iso3: "NIC", country_name: "Nicaragua", units: ["USD"], observations: 1 }];
  return {
    meta: { total: options.total ?? 1 }, indicator: { code: "GDP", name: "PIB", frequency: "annual" },
    comparable: options.comparable ?? true, levels_comparable: options.levelsComparable ?? true, comparability_notes: ["Nota"],
    series, data: [{ period_start: "2024-01-01", period_label: "2024", values: { NIC: 10, CRI: 20 } }],
  };
}

describe("/series page", () => {
  beforeEach(() => {
    mocks.search = "";
    mocks.comparison = { data: undefined, isLoading: false, isFetching: false, isError: false, error: null };
  });

  it("explains the first visit before any selection", () => {
    render(<SeriesPage />);
    expect(screen.getByText(/Elige un indicador y uno o más países/)).toBeInTheDocument();
  });

  it("rejects an inverted date range before showing a comparison", () => {
    mocks.search = "indicator=GDP&country=NIC&date_from=2025-01-01&date_to=2020-01-01";
    render(<SeriesPage />);
    expect(screen.getByText(/fecha inicial debe ser anterior o igual/)).toBeInTheDocument();
    expect(screen.queryByTestId("series-chart")).not.toBeInTheDocument();
  });

  it("identifies a catalog-invalid selection separately from API failures", () => {
    mocks.search = "indicator=UNKNOWN&country=NIC";
    render(<SeriesPage />);
    expect(screen.getByText(/indicador no válidos/)).toBeInTheDocument();
  });

  it("shows API failures as service errors", () => {
    mocks.search = "indicator=GDP&country=NIC";
    mocks.comparison = { ...mocks.comparison, isError: true, error: new Error("API Error 500") };
    render(<SeriesPage />);
    expect(screen.getByText(/No se pudieron consultar los datos: API Error 500/)).toBeInTheDocument();
  });

  it("shows an API 404 as a failed request instead of an empty result", () => {
    mocks.search = "indicator=GDP&country=NIC";
    mocks.comparison = { ...mocks.comparison, isError: true, error: new Error("API Error 404: Not Found") };
    render(<SeriesPage />);
    expect(screen.getByText(/API Error 404: Not Found/)).toBeInTheDocument();
  });

  it("shows a loading status while comparison data is pending", () => {
    mocks.search = "indicator=GDP&country=NIC";
    mocks.comparison = { ...mocks.comparison, isLoading: true };
    render(<SeriesPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Cargando observaciones");
  });

  it("distinguishes a valid selection with no observations", () => {
    mocks.search = "indicator=GDP&country=NIC";
    mocks.comparison = { ...mocks.comparison, data: response({ total: 0 }) };
    render(<SeriesPage />);
    expect(screen.getByText(/La selección es válida, pero no hay observaciones/)).toBeInTheDocument();
  });

  it("keeps a selected country named when the response has partial coverage", () => {
    mocks.search = "indicator=GDP&country=NIC&country=CRI";
    mocks.comparison = { ...mocks.comparison, data: response() };
    render(<SeriesPage />);
    expect(screen.getByText(/Costa Rica: sin observaciones devueltas/)).toBeInTheDocument();
  });

  it("does not draw a truncated result over the 1,500 period cap", () => {
    mocks.search = "indicator=GDP&country=NIC";
    mocks.comparison = { ...mocks.comparison, data: response({ total: 1800 }) };
    render(<SeriesPage />);
    expect(screen.getByText(/contiene 1800 períodos/)).toBeInTheDocument();
    expect(screen.queryByTestId("series-chart")).not.toBeInTheDocument();
  });

  it("uses one shared chart when both comparability flags are true", () => {
    mocks.search = "indicator=GDP&country=NIC&country=CRI";
    mocks.comparison = { ...mocks.comparison, data: response({ series: [
      { country_iso3: "NIC", country_name: "Nicaragua", units: ["USD"], observations: 1 },
      { country_iso3: "CRI", country_name: "Costa Rica", units: ["USD"], observations: 1 },
    ] }) };
    render(<SeriesPage />);
    expect(screen.getAllByTestId("series-chart")).toHaveLength(1);
  });

  it("uses small multiples when comparable levels are false", () => {
    mocks.search = "indicator=GDP&country=NIC&country=CRI";
    mocks.comparison = { ...mocks.comparison, data: response({ comparable: true, levelsComparable: false, series: [
      { country_iso3: "NIC", country_name: "Nicaragua", units: ["USD"], observations: 1 },
      { country_iso3: "CRI", country_name: "Costa Rica", units: ["USD"], observations: 1 },
    ] }) };
    render(<SeriesPage />);
    expect(screen.getAllByTestId("series-chart")).toHaveLength(2);
    expect(screen.getByText("Nota")).toBeInTheDocument();
  });

  it("excludes unit-changing series from charts but keeps their values in the table", () => {
    mocks.search = "indicator=GDP&country=NIC&country=CRI";
    mocks.comparison = { ...mocks.comparison, data: response({ series: [
      { country_iso3: "NIC", country_name: "Nicaragua", units: ["USD", "LCU"], observations: 1 },
      { country_iso3: "CRI", country_name: "Costa Rica", units: ["USD"], observations: 1 },
    ] }) };
    render(<SeriesPage />);
    expect(screen.getByText(/No se grafica Nicaragua/)).toBeInTheDocument();
    expect(screen.getAllByTestId("series-chart")).toHaveLength(1);
    expect(screen.getByRole("table")).toHaveTextContent("Nicaragua");
    expect(screen.getByRole("table")).toHaveTextContent("10");
  });
});
