# HoopsLab

HoopsLab is a basketball analytics project building toward a contextual NBA
shot-quality model and an interactive shot-analysis product. It currently
implements revision/hash-pinned multi-season ingestion, normalized PostgreSQL
storage, leakage-aware feature construction, and deterministic chronological
splits. It does not yet train a model or serve an API/dashboard.

```text
six pinned shotdetail Parquet seasons
  -> hash, schema, and row validation
  -> atomic normalized PostgreSQL ingestion
  -> local feature dataset + whole-game split manifest
  -> probability model and calibration (next)
  -> FastAPI and React analytics experience (later)
```

The initial stack is Python 3.13, uv, Pydantic, PyArrow, SQLAlchemy/Alembic,
PostgreSQL, scikit-learn, pytest, Ruff, and mypy.

## Data source

The source contract uses completed-season `shotdetail` Parquet snapshots from
the [NBA Data Archive](https://huggingface.co/datasets/cdechoch/nba-data-archive),
which mirrors Vladislav Shufinskiy's
[Apache-2.0 archive](https://github.com/shufinskiy/nba_data). Source revisions
and file hashes for the completed 2018-19 through 2023-24 regular seasons are
pinned in code before they are accepted. External source data and generated
feature/quality artifacts remain in ignored local directories.

The underlying statistics originate from NBA public services. HoopsLab is a
non-commercial portfolio project, attributes NBA.com, and does not redistribute
the dataset, logos, video, or play-by-play. Review the current
[NBA.com Terms of Use](https://www.nba.com/termsofuse) before reuse or public
deployment.

## Local setup

Requirements: uv, Docker with Compose, and Git.

```bash
uv sync --locked --all-groups
cp .env.example .env
docker compose up -d --wait db
uv run alembic upgrade head
uv run python scripts/validate_source.py
uv run python scripts/ingest.py
uv run python scripts/data_quality.py
uv run python scripts/build_features.py
```

The validation command downloads six pinned regular-season files (about 13 MB
total), verifies every SHA-256 and schema, and parses bounded samples. Ingestion
then validates every row and commits each season atomically. Re-running the same
source records a safe skip rather than duplicating basketball data.

Run the local checks with:

```bash
make check
make test
```

See [docs/architecture.md](docs/architecture.md) for the data contract,
relational design, and leakage boundary.
