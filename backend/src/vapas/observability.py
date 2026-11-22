import logging
from typing import Any, cast

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.types import Event, Hint

from vapas.config import Settings

KEPT_REQUEST_KEYS = frozenset({"method", "url"})


def scrub(event: Event, _hint: Hint | None = None) -> Event:
    data = cast(dict[str, Any], event)
    request = data.get("request")
    if isinstance(request, dict):
        url = request.get("url")
        kept = {key: value for key, value in request.items() if key in KEPT_REQUEST_KEYS}
        if isinstance(url, str):
            kept["url"] = url.split("?", 1)[0]
        data["request"] = kept
    data.pop("user", None)
    data.pop("server_name", None)
    for exception in data.get("exception", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            frame.pop("vars", None)
    for crumb in data.get("breadcrumbs", {}).get("values", []):
        crumb.pop("data", None)
    return event


def init_error_tracking(settings: Settings, component: str) -> bool:
    if settings.sentry_dsn is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
        before_send=scrub,
        integrations=[LoggingIntegration(event_level=logging.ERROR)],
    )
    sentry_sdk.set_tag("component", component)
    return True
