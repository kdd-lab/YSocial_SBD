"""Compatibility stubs for removed process watchdog."""


def get_watchdog_status(*args, **kwargs):
    return {
        "enabled": False,
        "run_interval_minutes": 0,
        "status": "disabled",
        "message": "Watchdog removed in this build.",
    }


def run_watchdog_now(*args, **kwargs):
    return {"success": False, "message": "Watchdog removed in this build."}


def set_watchdog_interval(*args, **kwargs):
    return False


def toggle_watchdog(*args, **kwargs):
    return False


def get_watchdog(*args, **kwargs):
    return None


def stop_watchdog(*args, **kwargs):
    return True
