import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  errorMessage,
  getModel,
  getShotQuality,
  getShots,
  searchPlayers,
} from "./client";
import { modelFixture, shotPageFixture, summaryFixture } from "../test/fixtures";

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("uses bounded encoded player search", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({ items: [{ player_id: 1629029, name: "Luka Dončić" }] }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(searchPlayers("Luka Dončić")).resolves.toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/players?search=Luka+Don%C4%8Di%C4%87&limit=10",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("propagates the same filters and bounded page parameters", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(summaryFixture))
      .mockResolvedValueOnce(response(shotPageFixture));
    vi.stubGlobal("fetch", fetchMock);
    const filters = {
      season_start: 2023,
      shot_type: "3PT Field Goal" as const,
      shooter_is_home: false,
    };

    await getShotQuality(1629029, filters);
    await getShots(1629029, filters, 100);

    const firstUrl = String(fetchMock.mock.calls[0]?.[0]);
    const secondUrl = String(fetchMock.mock.calls[1]?.[0]);
    expect(firstUrl).toContain("season_start=2023");
    expect(firstUrl).toContain("shot_type=3PT+Field+Goal");
    expect(firstUrl).toContain("shooter_is_home=false");
    expect(secondUrl).toContain("offset=100");
    expect(secondUrl).toContain("limit=100");
  });

  it("rejects malformed success payloads", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ model_version: 7 })));
    await expect(getModel()).rejects.toMatchObject({
      message: "HoopsLab returned an unexpected response.",
    });
  });

  it("maps unavailable responses without exposing backend bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ detail: "/private/model/path" }, 503)),
    );
    const rejection = getModel();
    await expect(rejection).rejects.toBeInstanceOf(ApiError);
    await expect(rejection).rejects.toMatchObject({
      status: 503,
      message: "Analytics not ready",
    });
  });

  it("maps player-analytics 404 responses to actionable copy", () => {
    const error = new ApiError("Request failed", 404);

    expect(errorMessage(error, "summary")).toBe(
      "Player not found; search again.",
    );
    expect(errorMessage(error, "player-analytics")).toBe(
      "Player not found; search again.",
    );
    expect(errorMessage(error, "general")).toBe("Request failed");
  });

  it("accepts model metrics only from a valid API response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(modelFixture)));
    await expect(getModel()).resolves.toEqual(modelFixture);
  });
});
