export type Player = {
  player_id: number;
  name: string;
};

export type AnalyticsFilters = {
  season_start: number | null;
  shot_type: "2PT Field Goal" | "3PT Field Goal" | null;
  shooter_is_home: boolean | null;
};

export type ModelMetadata = {
  model_version: string;
  family: "hist_gradient_boosting";
  calibration: "sigmoid";
  feature_names: string[];
  training_seasons: number[];
  calibration_season: 2022;
  selection_season: 2022;
  heldout_season: 2023;
  held_out_metrics: {
    log_loss: number;
    brier_score: number;
    roc_auc: number;
    ece: number;
  };
  limitations: string[];
};

export type ShotQualitySummary = {
  player: Player;
  filters: {
    season_start: number | null;
    season_type: "rg" | "po" | null;
    shot_type: "2PT Field Goal" | "3PT Field Goal" | null;
    shot_zone_basic: string | null;
    shooter_is_home: boolean | null;
  };
  attempts: number;
  made: number;
  actual_fg_pct: number | null;
  expected_fg_pct: number | null;
  actual_minus_expected_fg_pct: number | null;
  expected_makes: number;
  actual_minus_expected_makes: number;
  model_version: string;
};

export type Shot = {
  game_id: number;
  event_id: number;
  game_date: string;
  season_start: number;
  season_type: "rg" | "po";
  coordinate_x_ft: number;
  coordinate_y_ft: number;
  made: boolean;
  make_probability: number;
  shot_distance_ft: number;
  action_type: string;
  shot_type: "2PT Field Goal" | "3PT Field Goal";
  shot_zone_basic: string;
  shot_zone_area: string;
  shot_zone_range: string;
  shooter_is_home: boolean;
  period: number;
  seconds_remaining: number;
};

export type ShotPage = {
  player: Player;
  filters: ShotQualitySummary["filters"];
  model_version: string;
  pagination: {
    offset: number;
    limit: number;
    total: number;
  };
  items: Shot[];
};
