import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Header } from "../Header";

vi.mock("next/navigation", () => ({
  usePathname: () => "/map/",
}));

describe("Header", () => {
  it("renders brand and navigation links", () => {
    render(<Header />);
    expect(screen.getByText("REIM")).toBeInTheDocument();
    expect(screen.getByText("Mapa")).toBeInTheDocument();
    expect(screen.getByText("Series")).toBeInTheDocument();
    expect(screen.getByText("Catálogo")).toBeInTheDocument();
  });

  it("points Series and Operaciones at the interim /legacy pages", () => {
    render(<Header />);
    expect(screen.getByText("Series").closest("a")).toHaveAttribute("href", "/legacy/series");
    expect(screen.getByText("Operaciones").closest("a")).toHaveAttribute("href", "/legacy/runs");
  });

  it("leaves Catálogo pointed at the not-yet-built page", () => {
    render(<Header />);
    expect(screen.getByText("Catálogo").closest("a")).toHaveAttribute("href", "/catalog");
  });
});
