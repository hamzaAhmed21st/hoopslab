import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import { luka } from "../test/fixtures";
import { PlayerSearch } from "./PlayerSearch";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, searchPlayers: vi.fn() };
});

function renderSearch(onSelect = vi.fn(), onClear = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PlayerSearch selectedPlayer={null} onSelect={onSelect} onClear={onClear} />
    </QueryClientProvider>,
  );
  return { onSelect, onClear };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("PlayerSearch", () => {
  it("debounces two-character search and selects a stable numeric ID by keyboard", async () => {
    vi.mocked(api.searchPlayers).mockResolvedValue([luka]);
    const { onSelect } = renderSearch();
    const input = screen.getByRole("combobox", { name: "Player" });

    fireEvent.change(input, { target: { value: "Lu" } });
    expect(api.searchPlayers).not.toHaveBeenCalled();
    await new Promise((resolve) => window.setTimeout(resolve, 150));
    expect(api.searchPlayers).not.toHaveBeenCalled();
    expect(await screen.findByText("NBA ID 1629029")).toBeInTheDocument();
    expect(api.searchPlayers).toHaveBeenCalledWith("Lu", expect.any(AbortSignal));

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(luka);
  });

  it("does not query one character and exposes a no-results state", async () => {
    const user = userEvent.setup();
    vi.mocked(api.searchPlayers).mockResolvedValue([]);
    renderSearch();
    const input = screen.getByRole("combobox", { name: "Player" });
    await user.type(input, "L");
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    expect(api.searchPlayers).not.toHaveBeenCalled();
    await user.type(input, "x");
    expect(await screen.findByText("No matching players.")).toBeInTheDocument();
  });

  it("shows a retryable search error", async () => {
    const user = userEvent.setup();
    vi.mocked(api.searchPlayers).mockRejectedValue(new api.ApiError("Could not reach HoopsLab."));
    renderSearch();
    await user.type(screen.getByRole("combobox", { name: "Player" }), "zz");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach HoopsLab.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });
});
