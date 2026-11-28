class ServicePausedError(Exception):
    pass


def ensure_intake_open(kill_switch: bool) -> None:
    if kill_switch:
        raise ServicePausedError("signups and uploads are paused")


def intake_state(kill_switch: bool) -> str:
    return "paused" if kill_switch else "open"
