import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { madeShot, missedShot, shotPageFixture, summaryFixture } from "../test/fixtures";
import { pageScope } from "../lib/shotScope";
import { ShotChart } from "./ShotChart";
import { ShotTable } from "./ShotTable";
import { Summary } from "./Summary";

describe("analytics presentation", () => {
  it("formats full-population actual versus expected as percentage points", () => {
    render(<Summary summary={summaryFixture} />);
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("49.0%")).toBeInTheDocument();
    expect(screen.getByText("46.0%")).toBeInTheDocument();
    expect(screen.getByText("+3.0 pp")).toBeInTheDocument();
    expect(screen.getByText(/not a causal measure/i)).toBeInTheDocument();
  });

  it("renders em dashes rather than fake zeros for an empty population", () => {
    render(
      <Summary
        summary={{
          ...summaryFixture,
          attempts: 0,
          made: 0,
          actual_fg_pct: null,
          expected_fg_pct: null,
          actual_minus_expected_fg_pct: null,
        }}
      />,
    );
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.getByText(/No shots match/i)).toBeInTheDocument();
  });

  it("discloses page scope and distinguishes makes from misses by shape", () => {
    const outside = { ...madeShot, game_id: 3, coordinate_x_ft: 30 };
    render(<ShotChart page={{ ...shotPageFixture, items: [madeShot, missedShot, outside] }} />);

    expect(screen.getByText("Showing newest 1–3 of 245 attempts")).toBeInTheDocument();
    expect(screen.getByText(/Summary above covers the full filtered population/i)).toBeInTheDocument();
    expect(screen.getByText(/1 current-page shot is outside/i)).toBeInTheDocument();
    expect(document.querySelectorAll(".shot-made circle")).toHaveLength(1);
    expect(document.querySelectorAll(".shot-missed line")).toHaveLength(2);
    expect(screen.getAllByRole("img").length).toBeGreaterThan(2);
  });

  it("states the exact newest range for later pages", () => {
    expect(
      pageScope({
        ...shotPageFixture,
        pagination: { offset: 100, limit: 100, total: 245 },
        items: Array.from({ length: 100 }, (_, index) => ({
          ...madeShot,
          event_id: index,
        })),
      }),
    ).toBe("Showing newest 101–200 of 245 attempts");
    expect(
      pageScope({ ...shotPageFixture, items: [], pagination: { offset: 300, limit: 100, total: 245 } }),
    ).toBe("Showing newest 0 of 245 attempts");
  });

  it("offers bounded deterministic page controls and a text equivalent", () => {
    const onOffsetChange = vi.fn();
    render(<ShotTable page={shotPageFixture} onOffsetChange={onOffsetChange} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("● Made")).toBeInTheDocument();
    expect(screen.getByText("× Missed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Newer" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    expect(onOffsetChange).toHaveBeenCalledWith(100);
  });

  it("reports the reachable final page at the API offset boundary", () => {
    render(
      <ShotTable
        page={{
          ...shotPageFixture,
          pagination: { offset: 10_000, limit: 100, total: 10_200 },
        }}
        onOffsetChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Page 101 of 101")).toBeInTheDocument();
    expect(
      screen.getByText("Inspection is limited to the newest 10,100 attempts."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Newer" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Older" })).toBeDisabled();
  });
});
