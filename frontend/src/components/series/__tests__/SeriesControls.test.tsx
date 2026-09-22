import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SeriesControls } from "../SeriesControls";
import { Country, Indicator } from "@/types/api";

const indicators = [{ code: "GDP", name: "PIB" }] as Indicator[];
const countries = [{ iso3: "NIC", name: "Nicaragua", is_active: true }, { iso3: "CRI", name: "Costa Rica", is_active: true }] as Country[];

describe("SeriesControls", () => {
  it("submits one indicator, multiple countries and optional date bounds", () => {
    const onSubmit = vi.fn();
    render(<SeriesControls indicators={indicators} countries={countries} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Indicador"), { target: { value: "GDP" } });
    const countrySelect = screen.getByLabelText(/Países/) as HTMLSelectElement;
    Array.from(countrySelect.options).forEach((option) => { option.selected = ["NIC", "CRI"].includes(option.value); });
    fireEvent.change(countrySelect);
    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2020-01-01" } });
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2024-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Consultar series" }));
    expect(onSubmit).toHaveBeenCalledWith({ indicator: "GDP", countries: ["NIC", "CRI"], dateFrom: "2020-01-01", dateTo: "2024-12-31" });
  });
});
