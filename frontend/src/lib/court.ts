export const COURT_VIEW = {
  minX: -25,
  maxX: 25,
  minY: -4.75,
  maxY: 42.25,
} as const;

export const COURT_SVG = {
  left: 25,
  top: 25,
  width: 450,
  height: 423,
} as const;

export type CourtPoint = { x: number; y: number };

export function courtToSvg(x: number, y: number): CourtPoint {
  return {
    x: COURT_SVG.left + ((x + 25) / 50) * COURT_SVG.width,
    y: COURT_SVG.top + ((42.25 - y) / 47) * COURT_SVG.height,
  };
}

export function isInsideCourtView(x: number, y: number): boolean {
  return (
    x >= COURT_VIEW.minX &&
    x <= COURT_VIEW.maxX &&
    y >= COURT_VIEW.minY &&
    y <= COURT_VIEW.maxY
  );
}

export function threePointPath(): string {
  const cornerY = Math.sqrt(23.75 ** 2 - 22 ** 2);
  const physical: CourtPoint[] = [{ x: -22, y: COURT_VIEW.minY }];
  physical.push({ x: -22, y: cornerY });
  for (let step = 1; step < 24; step += 1) {
    const angle = Math.atan2(cornerY, -22) -
      (step / 24) * (Math.atan2(cornerY, -22) - Math.atan2(cornerY, 22));
    physical.push({ x: 23.75 * Math.cos(angle), y: 23.75 * Math.sin(angle) });
  }
  physical.push({ x: 22, y: cornerY }, { x: 22, y: COURT_VIEW.minY });
  return physical
    .map((point, index) => {
      const svg = courtToSvg(point.x, point.y);
      return `${index === 0 ? "M" : "L"} ${svg.x.toFixed(2)} ${svg.y.toFixed(2)}`;
    })
    .join(" ");
}

export function restrictedAreaPath(): string {
  const physical: CourtPoint[] = [];
  for (let step = 0; step <= 20; step += 1) {
    const x = -4 + (step / 20) * 8;
    physical.push({ x, y: Math.sqrt(4 ** 2 - x ** 2) });
  }
  return physical
    .map((point, index) => {
      const svg = courtToSvg(point.x, point.y);
      return `${index === 0 ? "M" : "L"} ${svg.x.toFixed(2)} ${svg.y.toFixed(2)}`;
    })
    .join(" ");
}
