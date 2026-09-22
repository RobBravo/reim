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

  it("points Series and Operaciones at their modern pages", () => {
    render(<Header />);
    expect(screen.getByText("Series").closest("a")).toHaveAttribute("href", "/series");
    expect(screen.getByText("Operaciones").closest("a")).toHaveAttribute("href", "/runs");
  });

  it("points Catálogo at its static page", () => {
    render(<Header />);
    expect(screen.getByText("Catálogo").closest("a")).toHaveAttribute("href", "/catalog");
  });
});
