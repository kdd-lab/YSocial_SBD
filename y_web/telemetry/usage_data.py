"""Telemetry implementation removed from this build."""


class Telemetry:
    def __init__(self, *args, **kwargs):
        self.enabled = False

    def register_update_app(self, *args, **kwargs):
        return False

    def log_event(self, *args, **kwargs):
        return False

    def log_stack_trace(self, *args, **kwargs):
        return False

    def submit_experiment_logs(self, *args, **kwargs):
        return False, "Telemetry is disabled in this build."
