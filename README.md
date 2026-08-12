# HoopsLab

HoopsLab is a basketball analytics project building toward a contextual NBA
shot-quality model and an interactive shot-analysis product. The current
checkpoint implements the reproducible data boundary, validated shot domain,
PostgreSQL schema, and migration foundation; it does not yet train a model or
serve an API/dashboard.

```text
version-pinned shotdetail Parquet
  -> schema and domain validation
  -> normalized records + PostgreSQL schema (current)
  -> multi-season persistence and feature pipeline (next)
  -> FastAPI and React analytics experience (later)
```

The initial stack is Python 3.13, uv, Pydantic, PyArrow, SQLAlchemy/Alembic,
PostgreSQL, scikit-learn, pytest, Ruff, and mypy.

## Data source

The source contract uses completed-season `shotdetail` Parquet snapshots from
the [NBA Data Archive](https://huggingface.co/datasets/cdechoch/nba-data-archive),
which mirrors Vladislav Shufinskiy's
[Apache-2.0 archive](https://github.com/shufinskiy/nba_data). Source revisions
and file hashes are pinned in code before they are accepted. The current
validation asset is one pinned 2023-24 file; the cohort manifest is the next
data-layer step. External data is downloaded to an ignored local cache and is
never committed.

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
```

The validation command downloads one pinned 2023-24 regular-season file (about
2.25 MB), verifies its SHA-256, and parses a bounded sample through the domain
contract.

Run the local checks with:

```bash
make check
make test
```

See [docs/architecture.md](docs/architecture.md) for the data contract,
relational design, and leakage boundary.
