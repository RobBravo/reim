import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MapControls } from "../MapControls";
import { Indicator } from "@/types/api";

const MOCK_INDICATORS: Indicator[] = [
  {
    id: "1",
    code: "cpi_monthly",
    name: "Índice de Precios al Consumidor",
    description: "Inflación mensual",
    frequency: "monthly",
    unit: "Índice",
    decimals: 2,
    category: "prices",
    comparable: true,
    levels_comparable: true,
    currency_convertible: false,
    methodology_varies_by_country: false,
    requires_administrative_area: false,
  },
];

describe("MapControls", () => {
  it("renders indicator and level buttons", () => {
    const onSelectIndicator = vi.fn();
    const onSelectLevel = vi.fn();
    const onSelectPeriod = vi.fn();

    render(
      <MapControls
        indicators={MOCK_INDICATORS}
        selectedIndicatorId="cpi_monthly"
        onSelectIndicator={onSelectIndicator}
        level="country"
        onSelectLevel={onSelectLevel}
        periods={["2026-07", "2026-06"]}
        selectedPeriod="2026-07"
        onSelectPeriod={onSelectPeriod}
      />
    );

    expect(screen.getByText("Controles del Mapa")).toBeInTheDocument();
    expect(screen.getByText("Nacional")).toBeInTheDocument();
    expect(screen.getByText("Provincial (PA)")).toBeInTheDocument();
    expect(screen.getAllByText("2026-07").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText("Provincial (PA)"));
    expect(onSelectLevel).toHaveBeenCalledWith("administrative_area");
  });
});
