from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from pydantic import BaseModel

from vapas.config import Settings, get_settings
from vapas.health import Dependencies, Probe, run_probes
from vapas.logging_setup import configure_logging


class Liveness(BaseModel):
    status: str


class Readiness(BaseModel):
    status: str
    checks: dict[str, bool]


def create_app(settings: Settings | None = None, probes: Mapping[str, Probe] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if probes is not None:
            app.state.probes = probes
            yield
            return
        active = settings or get_settings()
        configure_logging(active.log_level)
        dependencies = Dependencies.from_settings(active)
        app.state.probes = dependencies.probes()
        try:
            yield
        finally:
            await dependencies.close()

    app = FastAPI(title="VAPAS", lifespan=lifespan)

    @app.get("/health")
    async def health() -> Liveness:
        return Liveness(status="ok")

    @app.get("/ready")
    async def ready(response: Response) -> Readiness:
        checks = await run_probes(app.state.probes)
        if all(checks.values()):
            return Readiness(status="ready", checks=checks)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(status="not_ready", checks=checks)

    return app


app = create_app()
