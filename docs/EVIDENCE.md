# HoopsLab: implementation and verification

For a short code review, start with [transactional ingestion](../backend/src/hoopslab/ingestion.py) and its [PostgreSQL tests](../backend/tests/test_ingestion_database.py). For the modeling work, compare the [evaluation report](evidence/final-test-report.json) with the [protocol](../backend/src/hoopslab/modeling/protocol.py) and [workflow tests](../backend/tests/test_modeling.py).

## Implementation and tests

| Accomplishment | Implementation | Verification |
| --- | --- | --- |
| Six-season, reproducible inputs | [Source manifest and validation](../backend/src/hoopslab/sources/archive.py): immutable source revision, SHA-256, schema, and expected row counts for 2018-19 through 2023-24. | [Source tests](../backend/tests/test_archive_source.py). |
| Atomic imports and repeat-import handling | [Season ingestion](../backend/src/hoopslab/ingestion.py): matching completed imports are skipped; conflicting source identities are rejected; season data writes use a database transaction. | [PostgreSQL ingestion tests](../backend/tests/test_ingestion_database.py): repeat imports, provenance conflict, and failed normalization without completion or partial game records. |
| Chronological evaluation | [Protocol](../backend/src/hoopslab/modeling/protocol.py) and [workflow](../backend/src/hoopslab/modeling/workflow.py): development-season restrictions, whole-game separation, calibration/selection boundaries, and locked final evaluation. | [Modeling tests](../backend/tests/test_modeling.py): reject test-season development access, keep game sets disjoint, and run a synthetic develop/lock/evaluate flow that rejects a second report. |
| Validated model serving | [Runtime](../backend/src/hoopslab/api/runtime.py) and [routes](../backend/src/hoopslab/api/routes.py): validate artifact identity and serve single/batch predictions. | [Runtime tests](../backend/tests/test_api_runtime.py): tampered records, incorrect model configuration, missing artifacts, and prediction behavior. |
| Interactive analytics | [SVG court](../frontend/src/components/ShotChart.tsx), [API analytics](../backend/src/hoopslab/api/analytics.py), and [React application](../frontend/src/App.tsx). | [Analytics API tests](../backend/tests/test_api_analytics.py), [UI tests](../frontend/src/components/AnalyticsView.test.tsx), and [court-coordinate tests](../frontend/src/lib/court.test.ts). |

## Recorded CI evidence

[Successful run 31649357416](https://github.com/hamzaAhmed21st/hoopslab/actions/runs/31649357416), commit `6a9684694d230dc480775fd50d8d5b7034e66381`:

- Backend: **79 passed, 1 skipped**.
- Frontend: **26 passed** across 6 test files.
- Migration verification, lint/type checks, frontend build, and container builds succeeded.
- The skipped test was `test_real_locked_model_has_a_bounded_serving_smoke`: the ignored locked-model artifacts were not present.

These counts describe that recorded run, not a permanently fixed test count or a coverage percentage. The [workflow](../.github/workflows/ci.yml) defines the checks; the README badge links to current CI.

## Model results and reproducibility

The [original evaluation report](evidence/final-test-report.json), created on **August 12, 2026**, records a local evaluation on **218,701 shots from 1,230 games** in 2023-24. These are the same results described in the [architecture report](architecture.md#held-out-evaluation):

| Model | Log loss | Brier score | ROC-AUC |
| --- | ---: | ---: | ---: |
| Selected calibrated histogram gradient boosting | 0.637055 | 0.224358 | 0.657832 |
| Locked calibrated logistic comparator | 0.642787 | 0.226538 | 0.650390 |

**What is available:** source manifests, modeling/evaluation implementation, tests, the unchanged original machine-generated evaluation report, and [provenance excerpts](evidence/provenance.json) from its original selection lock and model manifest. The provenance includes original-file checksums, model/feature/split identities, source revision and asset hashes, model configurations, package versions, seeds, and chronological segment boundaries.

**Verification performed for publication:** the report, selection lock, and model manifest agree on the selected model and comparator. Their SHA-256 identities match the original local model bundle, feature Parquet, and split manifest. The split manifest contains 1,230 held-out games, and the report's metrics round to the documented values. The recorded selection lock predates the report. This was an artifact consistency check, not retraining or a new evaluation.

**What is not committed:** the trained model binary, generated feature dataset, per-game split assignments, and full runtime lock/manifest files. Public readers can inspect the recorded scores and identities, but cannot independently recompute the predictions from these documentation files alone. CI's synthetic workflow tests verify behavior, not the full-dataset scores. The original records do not record a training-code Git commit; the historical CI commit above must not be treated as that missing identity.

The [local setup](../README.md#run-locally) describes database preparation, feature generation, and the develop/verify/lock/evaluate sequence. The serving runtime expects the recorded model configuration and exact segment sizes; it is not a general loader for arbitrary newly trained models. The modeling entry points are [develop](../scripts/develop_model.py), [lock](../scripts/lock_model.py), [evaluate](../scripts/evaluate_model.py), and [verify](../scripts/verify_model.py). Without compatible local artifacts, model-dependent routes return 503 rather than substituting a model.

## Interpretation

- This is descriptive shot-quality analysis, not a causal estimate of player or defender value.
- Tests of locking and split separation do not establish that every possible source of modeling leakage is absent.

[Back to the project](../README.md)
