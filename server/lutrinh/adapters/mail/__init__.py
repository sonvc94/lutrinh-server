"""Mail adapter (page 06 §1 ``adapters/mail/``). SMTP needs the host's account, so only the
log adapter exists for now; the app factory takes any ``Mailer``."""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger("lutrinh.mail")


class Mailer(Protocol):
    def send(self, subject: str, body: str) -> None: ...


class LogMailer:
    """Writes the message to the log instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        self.sent.append((subject, body))
        log.warning("mail (not sent, no SMTP adapter yet): %s\n%s", subject, body)
