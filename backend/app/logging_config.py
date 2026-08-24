"""Make the application's own log lines reach somebody.

`LOG_LEVEL` has only ever been handed to uvicorn, which configures its own
loggers and nothing else. The two trees this project logs to - `app.*` from
module `__name__`, and the older `sketchy.*` names - had no handler at all, so
every logger.info and logger.exception in the codebase was written into
nothing: mail that could not be sent, a failing outbox sweep, a report being
filed, a game whose history could not be saved.

That is worse than quiet. The zero-configuration deployment this project
documents has no SMTP, and its console transport answers that by logging the
message it would have sent. If the log goes nowhere, the account recovery flow
silently does nothing at all on the default deployment.
"""
from __future__ import annotations

import logging
import os
import sys


TREES = ("app", "sketchy")
FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Attach one stream handler to each of the application's logger trees.

    Idempotent, because both the app's lifespan and a test may call it.
    Handlers are attached to the trees rather than the root so that uvicorn's
    own configuration is left exactly as it is.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "info")).upper()
    numeric = getattr(logging, resolved, logging.INFO)
    for name in TREES:
        logger = logging.getLogger(name)
        logger.setLevel(numeric)
        if any(getattr(h, "_sketchy_handler", False) for h in logger.handlers):
            continue
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(FORMAT))
        handler._sketchy_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        # Propagation is left on. Nothing configures the root logger here, so
        # there is no duplicate to avoid - and switching it off would cut these
        # records off from anything that attaches to root later, pytest's
        # caplog included.
