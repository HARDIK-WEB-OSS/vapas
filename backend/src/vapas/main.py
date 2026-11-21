from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from pydantic import BaseModel

from vapas.api.routes_account import router as account_router
from vapas.api.routes_findings import router as findings_router
from vapas.api.routes_knowledge import router as knowledge_router
from vapas.api.routes_statements import router as statements_router
from vapas.auth.routes import router as auth_router
from vapas.config import Settings, get_settings
from vapas.errors import register_error_handlers
from vapas.health import Probe, run_probes
from vapas.logging_setup import configure_logging
from vapas.services import Services


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
        services = Services.from_settings(active)
        app.state.services = services
        app.state.probes = services.dependencies.probes()
        try:
            yield
        finally:
            await services.close()

    app = FastAPI(title="VAPAS", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(statements_router)
    app.include_router(findings_router)
    app.include_router(knowledge_router)

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
