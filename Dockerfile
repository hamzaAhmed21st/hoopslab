FROM ghcr.io/astral-sh/uv:0.12.1-python3.13-trixie-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend ./backend
RUN uv sync --locked --no-dev

EXPOSE 8000

CMD ["uvicorn", "hoopslab.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
