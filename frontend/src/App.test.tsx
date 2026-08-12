import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import * as api from "./api/client";
import {
  luka,
  modelFixture,
  shotPageFixture,
  summaryFixture,
} from "./test/fixtures";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return {
    ...actual,
    getReadiness: vi.fn(),
    getModel: vi.fn(),
    searchPlayers: vi.fn(),
    getShotQuality: vi.fn(),
    getShots: vi.fn(),
  };
});

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

async function selectLuka() {
  const user = userEvent.setup();
  await user.type(screen.getByRole("combobox", { name: "Player" }), "Luka");
  const option = await screen.findByRole("option", { name: /Luka Dončić/i });
  fireEvent.click(option);
  expect(option).toHaveAttribute("aria-selected");
}

beforeEach(() => {
  vi.mocked(api.getReadiness).mockResolvedValue("ready");
  vi.mocked(api.getModel).mockResolvedValue(modelFixture);
  vi.mocked(api.searchPlayers).mockResolvedValue([luka]);
  vi.mocked(api.getShotQuality).mockResolvedValue(summaryFixture);
  vi.mocked(api.getShots).mockResolvedValue(shotPageFixture);
});

describe("dashboard flow", () => {
  it("starts honestly without player data and renders API-derived model context", async () => {
    renderApp();
    expect(screen.getByText(/Search for a player to open the court/i)).toBeInTheDocument();
    expect(screen.queryByText("49.0%")).not.toBeInTheDocument();
    expect(await screen.findByText("Analytics ready")).toBeInTheDocument();
    expect(await screen.findByText("0.637")).toBeInTheDocument();
    expect(screen.getByText("fb075abb1647")).toBeInTheDocument();
  });

  it("uses the generic unavailable copy for model 503 responses", async () => {
    vi.mocked(api.getModel).mockRejectedValue(
      new api.ApiError("private diagnostic", 503),
    );
    renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Analytics not ready",
    );
    expect(screen.queryByText("private diagnostic")).not.toBeInTheDocument();
  });

  it("shares filter state across summary and shots and resets pagination", async () => {
    const user = userEvent.setup();
    renderApp();
    await selectLuka();

    expect(await screen.findByText("+3.0 pp")).toBeInTheDocument();
    await waitFor(() => expect(api.getShots).toHaveBeenCalled());
    expect(api.getShotQuality).toHaveBeenLastCalledWith(
      1629029,
      { season_start: 2023, shot_type: null, shooter_is_home: null },
      expect.any(AbortSignal),
    );
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => {
      expect(api.getShots).toHaveBeenLastCalledWith(
        1629029,
        expect.any(Object),
        100,
        expect.any(AbortSignal),
      );
    });

    await user.selectOptions(screen.getByLabelText("Shot type"), "3PT Field Goal");
    await waitFor(() => {
      expect(api.getShotQuality).toHaveBeenLastCalledWith(
        1629029,
        { season_start: 2023, shot_type: "3PT Field Goal", shooter_is_home: null },
        expect.any(AbortSignal),
      );
      expect(api.getShots).toHaveBeenLastCalledWith(
        1629029,
        { season_start: 2023, shot_type: "3PT Field Goal", shooter_is_home: null },
        0,
        expect.any(AbortSignal),
      );
    });
  });

  it("keeps summary and shot-page loading states independent", async () => {
    vi.mocked(api.getShotQuality).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.getShots).mockReturnValue(new Promise(() => {}));
    renderApp();
    await selectLuka();

    expect(
      await screen.findByText("Calculating full-population shot quality…"),
    ).toBeInTheDocument();
    expect(screen.getByText("Loading the newest 100 shots…")).toBeInTheDocument();
  });

  it("clears prior-player analytics as soon as a new search begins", async () => {
    const user = userEvent.setup();
    renderApp();
    await selectLuka();
    expect(await screen.findByText("49.0%")).toBeInTheDocument();

    const input = screen.getByRole("combobox", { name: "Player" });
    await user.clear(input);
    await user.type(input, "Nikola");
    expect(screen.queryByText("49.0%")).not.toBeInTheDocument();
    expect(screen.getByText(/Search for a player to open the court/i)).toBeInTheDocument();
  });

  it("keeps readiness, summary, and shot-page failures independent", async () => {
    vi.mocked(api.getReadiness).mockRejectedValue(new api.ApiError("Analytics not ready", 503));
    vi.mocked(api.getShotQuality).mockRejectedValue(new api.ApiError("Request failed", 422));
    renderApp();
    await selectLuka();

    expect(await screen.findByText("Analytics not ready")).toBeInTheDocument();
    expect(
      await screen.findByText(/This population is too large. Refine filters/i),
    ).toBeInTheDocument();
    expect(await screen.findByText("Shot locations")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);
  });
});
