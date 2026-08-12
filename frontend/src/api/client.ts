import type {
  AnalyticsFilters,
  ModelMetadata,
  Player,
  ShotPage,
  ShotQualitySummary,
} from "./types";

type JsonRecord = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPlayer(value: unknown): value is Player {
  return (
    isRecord(value) &&
    typeof value.player_id === "number" &&
    typeof value.name === "string"
  );
}

function isModelMetadata(value: unknown): value is ModelMetadata {
  if (!isRecord(value) || !isRecord(value.held_out_metrics)) return false;
  const metrics = value.held_out_metrics;
  return (
    typeof value.model_version === "string" &&
    value.family === "hist_gradient_boosting" &&
    value.calibration === "sigmoid" &&
    Array.isArray(value.feature_names) &&
    value.feature_names.every((field) => typeof field === "string") &&
    Array.isArray(value.training_seasons) &&
    value.training_seasons.every((season) => typeof season === "number") &&
    value.calibration_season === 2022 &&
    value.selection_season === 2022 &&
    value.heldout_season === 2023 &&
    ["log_loss", "brier_score", "roc_auc", "ece"].every(
      (field) => typeof metrics[field] === "number",
    ) &&
    Array.isArray(value.limitations) &&
    value.limitations.every((limitation) => typeof limitation === "string")
  );
}

function isShotFilters(value: unknown): boolean {
  return (
    isRecord(value) &&
    [null, "rg", "po"].includes(value.season_type as string | null) &&
    (value.season_start === null || typeof value.season_start === "number") &&
    (value.shot_type === null || typeof value.shot_type === "string") &&
    (value.shot_zone_basic === null || typeof value.shot_zone_basic === "string") &&
    (value.shooter_is_home === null || typeof value.shooter_is_home === "boolean")
  );
}

function isShotQualitySummary(value: unknown): value is ShotQualitySummary {
  return (
    isRecord(value) &&
    isPlayer(value.player) &&
    isShotFilters(value.filters) &&
    typeof value.attempts === "number" &&
    typeof value.made === "number" &&
    (value.actual_fg_pct === null || typeof value.actual_fg_pct === "number") &&
    (value.expected_fg_pct === null || typeof value.expected_fg_pct === "number") &&
    (value.actual_minus_expected_fg_pct === null ||
      typeof value.actual_minus_expected_fg_pct === "number") &&
    typeof value.expected_makes === "number" &&
    typeof value.actual_minus_expected_makes === "number" &&
    typeof value.model_version === "string"
  );
}

function isShotPage(value: unknown): value is ShotPage {
  if (
    !isRecord(value) ||
    !isPlayer(value.player) ||
    !isShotFilters(value.filters) ||
    typeof value.model_version !== "string" ||
    !isRecord(value.pagination) ||
    !Array.isArray(value.items)
  ) {
    return false;
  }
  const pagination = value.pagination;
  return (
    [pagination.offset, pagination.limit, pagination.total].every(
      (item) => typeof item === "number",
    ) &&
    value.items.every(
      (shot) =>
        isRecord(shot) &&
        typeof shot.game_id === "number" &&
        typeof shot.event_id === "number" &&
        typeof shot.game_date === "string" &&
        typeof shot.season_start === "number" &&
        ["rg", "po"].includes(shot.season_type as string) &&
        typeof shot.coordinate_x_ft === "number" &&
        typeof shot.coordinate_y_ft === "number" &&
        typeof shot.made === "boolean" &&
        typeof shot.make_probability === "number" &&
        typeof shot.shot_distance_ft === "number" &&
        typeof shot.action_type === "string" &&
        ["2PT Field Goal", "3PT Field Goal"].includes(shot.shot_type as string) &&
        typeof shot.shot_zone_basic === "string" &&
        typeof shot.shot_zone_area === "string" &&
        typeof shot.shot_zone_range === "string" &&
        typeof shot.shooter_is_home === "boolean" &&
        typeof shot.period === "number" &&
        typeof shot.seconds_remaining === "number",
    )
  );
}

async function fetchJson<T>(
  url: string,
  validate: (value: unknown) => value is T,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/json" }, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Could not reach HoopsLab.");
  }
  if (!response.ok) {
    throw new ApiError(
      response.status === 503 ? "Analytics not ready" : "Request failed",
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("HoopsLab returned an unreadable response.", response.status);
  }
  if (!validate(payload)) {
    throw new ApiError("HoopsLab returned an unexpected response.", response.status);
  }
  return payload;
}

function analyticsParams(filters: AnalyticsFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.season_start !== null) {
    params.set("season_start", String(filters.season_start));
  }
  if (filters.shot_type !== null) params.set("shot_type", filters.shot_type);
  if (filters.shooter_is_home !== null) {
    params.set("shooter_is_home", String(filters.shooter_is_home));
  }
  return params;
}

export async function getReadiness(signal?: AbortSignal): Promise<"ready"> {
  const response = await fetchJson(
    "/health/ready",
    (value): value is { status: "ready" } =>
      isRecord(value) && value.status === "ready",
    signal,
  );
  return response.status;
}

export function getModel(signal?: AbortSignal): Promise<ModelMetadata> {
  return fetchJson("/api/v1/model", isModelMetadata, signal);
}

export async function searchPlayers(
  search: string,
  signal?: AbortSignal,
): Promise<Player[]> {
  const params = new URLSearchParams({ search, limit: "10" });
  const response = await fetchJson(
    `/api/v1/players?${params.toString()}`,
    (value): value is { items: Player[] } =>
      isRecord(value) && Array.isArray(value.items) && value.items.every(isPlayer),
    signal,
  );
  return response.items;
}

export function getShotQuality(
  playerId: number,
  filters: AnalyticsFilters,
  signal?: AbortSignal,
): Promise<ShotQualitySummary> {
  const params = analyticsParams(filters);
  return fetchJson(
    `/api/v1/players/${playerId}/shot-quality?${params.toString()}`,
    isShotQualitySummary,
    signal,
  );
}

export function getShots(
  playerId: number,
  filters: AnalyticsFilters,
  offset: number,
  signal?: AbortSignal,
): Promise<ShotPage> {
  const params = analyticsParams(filters);
  params.set("offset", String(offset));
  params.set("limit", "100");
  return fetchJson(
    `/api/v1/players/${playerId}/shots?${params.toString()}`,
    isShotPage,
    signal,
  );
}

export function errorMessage(
  error: unknown,
  context: "summary" | "player-analytics" | "general",
): string {
  if (error instanceof ApiError) {
    if (error.status === 503) return "Analytics not ready";
    if (
      error.status === 404 &&
      (context === "summary" || context === "player-analytics")
    ) {
      return "Player not found; search again.";
    }
    if (error.status === 422 && context === "summary") {
      return "This population is too large. Refine filters and try again.";
    }
    return error.message;
  }
  return "HoopsLab could not complete this request.";
}
