import { describe, expect, it } from "vitest";

import { COURT_SVG, courtToSvg, isInsideCourtView } from "./court";

describe("court coordinates", () => {
  it("uses the explicit feet-to-SVG transform at physical view boundaries", () => {
    expect(courtToSvg(-25, 42.25)).toEqual({ x: COURT_SVG.left, y: COURT_SVG.top });
    expect(courtToSvg(25, -4.75)).toEqual({
      x: COURT_SVG.left + COURT_SVG.width,
      y: COURT_SVG.top + COURT_SVG.height,
    });
    expect(courtToSvg(0, 0).x).toBe(250);
  });

  it("omits rather than clamps coordinates outside the physical half-court", () => {
    expect(isInsideCourtView(25, 42.25)).toBe(true);
    expect(isInsideCourtView(25.1, 20)).toBe(false);
    expect(isInsideCourtView(0, 42.3)).toBe(false);
    expect(courtToSvg(30, 20).x).toBeGreaterThan(COURT_SVG.left + COURT_SVG.width);
  });
});
