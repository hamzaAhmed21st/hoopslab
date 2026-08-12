import { describe, expect, it } from "vitest";

import {
  formatPercentagePoints,
  formatPercent,
  seasonLabel,
} from "./format";

describe("analytics formatting", () => {
  it("formats nullable percentages without inventing zero", () => {
    expect(formatPercent(0.4664)).toBe("46.6%");
    expect(formatPercent(null)).toBe("—");
  });

  it("formats signed percentage-point differences", () => {
    expect(formatPercentagePoints(0.034)).toBe("+3.4 pp");
    expect(formatPercentagePoints(-0.021)).toBe("−2.1 pp");
    expect(formatPercentagePoints(0)).toBe("0.0 pp");
    expect(formatPercentagePoints(null)).toBe("—");
  });

  it("labels NBA seasons from their starting year", () => {
    expect(seasonLabel(2023)).toBe("2023–24");
  });
});
