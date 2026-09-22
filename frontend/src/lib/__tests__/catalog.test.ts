import { describe, expect, it } from "vitest";
import { isRedistributable } from "../catalog";

describe("catalog licence classification", () => {
  it("recognizes the catalog's explicitly open licence slugs", () => {
    expect(isRedistributable("CC-BY-4.0")).toBe(true);
    expect(isRedistributable("public_official_data")).toBe(true);
  });

  it("treats unknown and missing licence terms conservatively", () => {
    expect(isRedistributable("publisher-specific terms")).toBe(false);
    expect(isRedistributable(null)).toBe(false);
  });
});
