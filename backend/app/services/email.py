from __future__ import annotations

import asyncio
import threading
from typing import Protocol

import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)
_resend_send_lock = threading.Lock()


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html_body: str) -> None: ...


class ConsoleEmailSender:
    def __init__(self, *, email_from: str) -> None:
        self._email_from = email_from

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        logger.info(
            "email.console.sent",
            email_from=self._email_from,
            to=to,
            subject=subject,
            html_body=html_body,
        )


class ResendEmailSender:
    def __init__(self, *, api_key: str, email_from: str) -> None:
        self._api_key = api_key
        self._email_from = email_from

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        params: resend.Emails.SendParams = {
            "from": self._email_from,
            "to": [to],
            "subject": subject,
            "html": html_body,
        }
        await asyncio.to_thread(self._send_with_resend, params)

    def _send_with_resend(self, params: object) -> None:
        import resend

        with _resend_send_lock:
            resend.api_key = self._api_key
            resend.Emails.send(params)


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "resend":
        resend_api_key = settings.resend_api_key
        if resend_api_key is None:
            raise ValueError("RESEND_API_KEY is required when EMAIL_BACKEND=resend")
        return ResendEmailSender(
            api_key=resend_api_key.get_secret_value(),
            email_from=settings.email_from,
        )

    return ConsoleEmailSender(email_from=settings.email_from)
