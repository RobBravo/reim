import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SeriesChart } from "../SeriesChart";

const remove = vi.fn();
const addSeries = vi.fn(() => ({ setData: vi.fn() }));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  LineSeries: "line",
  createChart: vi.fn(() => ({ addSeries, remove, timeScale: () => ({ fitContent: vi.fn() }) })),
}));

describe("SeriesChart", () => {
  afterEach(() => vi.clearAllMocks());

  it("creates the data series and removes its chart on unmount", () => {
    const { unmount } = render(<SeriesChart title="PIB · Nicaragua" lines={[{ name: "Nicaragua", color: "#fff", points: [{ time: "2024-01-01", value: 2 }] }]} />);
    expect(screen.getByRole("heading", { name: "PIB · Nicaragua" })).toBeInTheDocument();
    expect(addSeries).toHaveBeenCalledOnce();
    unmount();
    expect(remove).toHaveBeenCalledOnce();
  });
});
