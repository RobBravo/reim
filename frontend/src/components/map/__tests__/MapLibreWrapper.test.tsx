import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MapLibreWrapper } from "../MapLibreWrapper";

describe("MapLibreWrapper", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders container element", () => {
    render(<MapLibreWrapper />);
    expect(screen.getByTestId("map-container")).toBeInTheDocument();
  });

  it("renders fallback message when WebGL is unavailable", () => {
    // In jsdom by default, getContext('webgl') returns null
    render(<MapLibreWrapper />);
    expect(screen.getByText("Visualizador WebGL")).toBeInTheDocument();
  });
});
