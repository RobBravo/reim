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
});
