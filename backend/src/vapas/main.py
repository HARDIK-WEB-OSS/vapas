from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from vapas.api.routes_account import router as account_router
from vapas.api.routes_cases import router as cases_router
from vapas.api.routes_findings import router as findings_router
from vapas.api.routes_knowledge import router as knowledge_router
from vapas.api.routes_notifications import router as notifications_router
from vapas.api.routes_statements import router as statements_router
from vapas.auth.routes import router as auth_router
from vapas.config import LOCAL_ENVS, Settings, get_settings
from vapas.errors import register_error_handlers
from vapas.health import Probe, run_probes
from vapas.logging_setup import configure_logging
from vapas.observability import init_error_tracking
from vapas.security.api_limits import ApiLimiter, api_limits_middleware
from vapas.security.http_guards import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from vapas.services import Services


class Liveness(BaseModel):
    status: str


class Readiness(BaseModel):
    status: str
    checks: dict[str, bool]


def _api_limiter(request: Request) -> ApiLimiter:
    limiter: ApiLimiter = request.app.state.api_limiter
    return limiter


def create_app(settings: Settings | None = None, probes: Mapping[str, Probe] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if probes is not None:
            app.state.probes = probes
            yield
            return
        active = settings or get_settings()
        configure_logging(active.log_level)
        init_error_tracking(active, "api")
        services = Services.from_settings(active)
        app.state.services = services
        app.state.api_limiter = ApiLimiter(services.limiter)
        app.state.probes = services.dependencies.probes()
        try:
            yield
        finally:
            await services.close()

    active = settings if settings is not None or probes is not None else get_settings()
    hide_docs = active is not None and active.app_env not in LOCAL_ENVS
    app = FastAPI(
        title="VAPAS",
        lifespan=lifespan,
        docs_url=None if hide_docs else "/docs",
        redoc_url=None if hide_docs else "/redoc",
        openapi_url=None if hide_docs else "/openapi.json",
    )
    if active is not None and probes is None:
        app.middleware("http")(
            api_limits_middleware(_api_limiter, active.jwt_secret.get_secret_value(), active.client_ip_header)
        )
    app.add_middleware(BodySizeLimitMiddleware)
    if active is not None and probes is None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[active.public_app_url],
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )
    app.add_middleware(SecurityHeadersMiddleware, https_only=active is not None and active.secure_cookies)
    register_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(statements_router)
    app.include_router(findings_router)
    app.include_router(knowledge_router)
    app.include_router(cases_router)
    app.include_router(notifications_router)

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
