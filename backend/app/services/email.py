from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import re

import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)
_resend_send_lock = threading.Lock()


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html_body: str) -> None: ...


class ConsoleEmailSender:
    def __init__(self, *, email_from: str, outbox_dir: Path | None = None) -> None:
        self._email_from = email_from
        self._outbox_dir = outbox_dir

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        links = self._extract_links(html_body)
        outbox_file: Path | None = None
        if self._outbox_dir is not None:
            outbox_file = await asyncio.to_thread(
                self._write_outbox_entry,
                to=to,
                subject=subject,
                html_body=html_body,
                links=links,
            )

        logger.info(
            "email.console.sent",
            email_from=self._email_from,
            to=to,
            subject=subject,
            links=[{"route_path": link["route_path"]} for link in links],
            outbox_file=str(outbox_file) if outbox_file is not None else None,
        )

    def _write_outbox_entry(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        links: list[dict[str, str]],
    ) -> Path:
        assert self._outbox_dir is not None
        self._outbox_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "email_from": self._email_from,
            "to": to,
            "subject": subject,
            "html_body": html_body,
            "links": links,
        }
        outbox_file = self._outbox_dir / f"{uuid.uuid4()}.json"
        outbox_file.write_text(json.dumps(payload), encoding="utf-8")
        return outbox_file

    @staticmethod
    def _extract_links(html_body: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []

        for url in re.findall(r'href=["\']([^"\']+)["\']', html_body):
            parsed = urlparse(url)
            token = parse_qs(parsed.query).get("token", [None])[0]
            if not parsed.path or token is None:
                continue
            links.append(
                {
                    "route_path": parsed.path,
                    "token": token,
                }
            )

        return links


class ResendEmailSender:
    def __init__(self, *, api_key: str, email_from: str) -> None:
        self._api_key = api_key
        self._email_from = email_from

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        params = {
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

    email_outbox_dir = getattr(settings, "email_outbox_dir", None)
    return ConsoleEmailSender(
        email_from=settings.email_from,
        outbox_dir=Path(email_outbox_dir) if email_outbox_dir else None,
    )
