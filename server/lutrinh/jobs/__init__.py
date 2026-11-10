"""Background jobs (page 06 §3, D-20 A): the API enqueues ``jobs`` rows, ``worker`` runs them.

A handler takes the ``Context`` and the job payload and returns a small JSON result. Raising
``PermanentError`` fails the job at once (a 65 s video, a file that is not an image); any other
exception is retried with backoff until ``jobs.max_attempts``. Handlers open their own short
sessions: the slow part (Pillow, ffmpeg, the router) runs outside any transaction, so the API
keeps writing while a video is encoded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from lutrinh.adapters.routing import Routers
from lutrinh.config import Settings
from lutrinh.db.models import utcnow

Payload = dict[str, Any]
Result = dict[str, Any]


class PermanentError(Exception):
    """The job cannot succeed by trying again; ``str(exc)`` is the recorded error."""


@dataclass
class Context:
    settings: Settings
    sessions: sessionmaker[Session]
    routers: Routers
    clock: Callable[[], datetime] = field(default=utcnow)
