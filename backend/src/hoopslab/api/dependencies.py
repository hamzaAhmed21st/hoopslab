"""Request-scoped database and process-scoped model dependencies."""

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from hoopslab.api.runtime import PredictionRuntime


def get_runtime(request: Request) -> PredictionRuntime:
    """Return the process-owned runtime without recreating it."""
    return cast(PredictionRuntime, request.app.state.model_runtime)


def require_runtime(
    runtime: Annotated[PredictionRuntime, Depends(get_runtime)],
) -> PredictionRuntime:
    """Fail model-dependent endpoints with a generic public error."""
    if not runtime.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model unavailable",
        )
    return runtime


def get_session(request: Request) -> Iterator[Session]:
    """Yield and always close one synchronous SQLAlchemy session."""
    session = Session(bind=request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


RuntimeDependency = Annotated[PredictionRuntime, Depends(require_runtime)]
SessionDependency = Annotated[Session, Depends(get_session)]
