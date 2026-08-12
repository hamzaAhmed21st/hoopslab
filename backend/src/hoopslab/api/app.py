"""FastAPI application factory and resource lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine

from hoopslab.api.routes import api_router, health_router
from hoopslab.api.runtime import ModelRuntime, ModelRuntimeError, PredictionRuntime
from hoopslab.config import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    runtime: PredictionRuntime | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    """Build an importable app with injectable process-scoped resources."""
    configured_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.engine = engine or create_engine(
            configured_settings.database_url, pool_pre_ping=True
        )
        application.state.model_runtime = runtime or ModelRuntime(
            artifact_path=configured_settings.model_artifact_path,
            manifest_path=configured_settings.model_manifest_path,
            lock_path=configured_settings.model_lock_path,
            report_path=configured_settings.model_report_path,
        )
        with suppress(ModelRuntimeError):
            application.state.model_runtime.initialize()
        try:
            yield
        finally:
            application.state.engine.dispose()

    application = FastAPI(
        title="HoopsLab API",
        version="1.0.0",
        description="Locked shot-quality inference and read-only player analytics.",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
