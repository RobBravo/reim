import { describe, it, expect } from "vitest";
import { computeChoroplethScale } from "../choropleth";

describe("computeChoroplethScale", () => {
  it("returns dark fallback for empty values", () => {
    const scale = computeChoroplethScale([]);
    expect(scale.getColor(10)).toBe("#1e293b");
    expect(scale.getColor(null)).toBe("#162232");
  });

  it("scales values from min to max across color ramp", () => {
    const scale = computeChoroplethScale([10, 20, 30, 40]);
    expect(scale.getColor(10)).toBe("#1e293b");
    expect(scale.getColor(40)).toBe("#e8b84b");
  });

  it("returns gold stop when min equals max", () => {
    const scale = computeChoroplethScale([50, 50]);
    expect(scale.getColor(50)).toBe("#e8b84b");
  });
});
