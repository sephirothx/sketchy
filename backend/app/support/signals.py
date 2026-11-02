"""What the webhook route has seen, for the operator (#1473).

In the process rather than the database: a counter resets with the process, as
every other in `telemetry.py` does, and a bad signature is exactly what must
not be able to write a row. One worker, so one set of numbers.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from app.services.telemetry import labelled_counter_lines

RECORDED = "recorded"
DUPLICATE = "duplicate"
IGNORED = "ignored"
BAD_SIGNATURE = "bad_signature"
ERROR = "error"
RESULTS = (RECORDED, DUPLICATE, IGNORED, BAD_SIGNATURE, ERROR)


class SupportSignals:
    def __init__(self) -> None:
        self.webhooks: Counter[str] = Counter()
        self.last_webhook_at: datetime | None = None
        self.last_signature_failure_at: datetime | None = None

    def saw(self, result: str, now: datetime) -> None:
        self.webhooks[result] += 1
        if result == BAD_SIGNATURE:
            self.last_signature_failure_at = now
        else:
            self.last_webhook_at = now

    def prometheus_lines(self) -> list[str]:
        return labelled_counter_lines(
            "sketchy_support_webhooks_total",
            "Supporter pass webhooks by what became of them.",
            ("result",),
            (((result,), self.webhooks[result]) for result in RESULTS),
        )


support_signals = SupportSignals()
