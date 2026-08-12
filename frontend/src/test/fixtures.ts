import type {
  ModelMetadata,
  Player,
  Shot,
  ShotPage,
  ShotQualitySummary,
} from "../api/types";

export const luka: Player = { player_id: 1629029, name: "Luka Dončić" };

export const modelFixture: ModelMetadata = {
  model_version: "fb075abb1647",
  family: "hist_gradient_boosting",
  calibration: "sigmoid",
  feature_names: ["coordinate_x_ft", "coordinate_y_ft"],
  training_seasons: [2018, 2019, 2020, 2021],
  calibration_season: 2022,
  selection_season: 2022,
  heldout_season: 2023,
  held_out_metrics: {
    log_loss: 0.637054,
    brier_score: 0.224358,
    roc_auc: 0.657832,
    ece: 0.006517,
  },
  limitations: ["Contextual make probability, not causal player value."],
};

export const summaryFixture: ShotQualitySummary = {
  player: luka,
  filters: {
    season_start: 2023,
    season_type: null,
    shot_type: null,
    shot_zone_basic: null,
    shooter_is_home: null,
  },
  attempts: 200,
  made: 98,
  actual_fg_pct: 0.49,
  expected_fg_pct: 0.46,
  actual_minus_expected_fg_pct: 0.03,
  expected_makes: 92,
  actual_minus_expected_makes: 6,
  model_version: "fb075abb1647",
};

export const madeShot: Shot = {
  game_id: 1,
  event_id: 20,
  game_date: "2024-04-10",
  season_start: 2023,
  season_type: "rg",
  coordinate_x_ft: 0,
  coordinate_y_ft: 25,
  made: true,
  make_probability: 0.38,
  shot_distance_ft: 25,
  action_type: "Jump Shot",
  shot_type: "3PT Field Goal",
  shot_zone_basic: "Above the Break 3",
  shot_zone_area: "Center(C)",
  shot_zone_range: "24+ ft.",
  shooter_is_home: true,
  period: 1,
  seconds_remaining: 500,
};

export const missedShot: Shot = {
  ...madeShot,
  game_id: 2,
  event_id: 10,
  coordinate_x_ft: 12,
  coordinate_y_ft: 8,
  made: false,
  make_probability: 0.54,
  shot_distance_ft: 14,
  action_type: "Pullup Jump Shot",
  shot_type: "2PT Field Goal",
  shot_zone_basic: "Mid-Range",
  shot_zone_range: "8-16 ft.",
};

export const shotPageFixture: ShotPage = {
  player: luka,
  filters: summaryFixture.filters,
  model_version: "fb075abb1647",
  pagination: { offset: 0, limit: 100, total: 245 },
  items: [madeShot, missedShot],
};
