from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import uuid

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.services.email import (
    ConsoleEmailSender,
    ResendEmailSender,
    build_email_sender,
)
from app.services.jwt_tokens import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
)
from app.services.passwords import hash_password, verify_password

TEST_SECRET = "test-jwt-secret-key-with-32-plus-chars"


def test_hash_password_round_trip_and_invalid_hash_rejection() -> None:
    password_hash = hash_password("Start123!")

    assert password_hash != "Start123!"
    assert verify_password(password_hash, "Start123!") is True
    assert verify_password(password_hash, "Wrong123!") is False
    assert verify_password("not-a-valid-argon2-hash", "Start123!") is False


def test_access_token_round_trip_preserves_core_claims() -> None:
    user_id = uuid.uuid7()

    token = create_access_token(
        user_id=user_id,
        secret_key=TEST_SECRET,
        expires_minutes=15,
    )
    payload = decode_access_token(token, secret_key=TEST_SECRET)

    assert payload.user_id == user_id
    assert payload.jti
    assert payload.exp > payload.iat


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = create_access_token(
        user_id=uuid.uuid7(),
        secret_key=TEST_SECRET,
        expires_minutes=15,
    )

    with pytest.raises(InvalidAccessTokenError, match="Invalid or expired access token"):
        decode_access_token(
            token,
            secret_key="wrong-secret-key-with-32-plus-chars",
        )


def test_build_email_sender_returns_console_sender_for_console_backend() -> None:
    sender = build_email_sender(
        SimpleNamespace(
            email_backend="console",
            email_from="noreply@example.com",
            email_outbox_dir=None,
            resend_api_key=None,
        )
    )

    assert isinstance(sender, ConsoleEmailSender)


def test_build_email_sender_requires_api_key_for_resend_backend() -> None:
    with pytest.raises(ValueError, match="RESEND_API_KEY is required"):
        build_email_sender(
            SimpleNamespace(
                email_backend="resend",
                email_from="noreply@example.com",
                email_outbox_dir=None,
                resend_api_key=None,
            )
        )


@pytest.mark.asyncio
async def test_console_email_sender_logs_metadata_only_and_writes_outbox(
    tmp_path: Path,
) -> None:
    sender = ConsoleEmailSender(
        email_from="noreply@example.com",
        outbox_dir=tmp_path,
    )

    with capture_logs() as logs:
        await sender.send(
            to="user@example.com",
            subject="Verify your account",
            html_body=(
                '<a href="http://localhost:5173/auth/verify-email?token=secret-token">'
                "Verify"
                "</a>"
            ),
        )

    assert len(logs) == 1
    log_entry = logs[0]
    assert log_entry["event"] == "email.console.sent"
    assert log_entry["to"] == "user@example.com"
    assert log_entry["subject"] == "Verify your account"
    assert "html_body" not in log_entry
    assert "secret-token" not in json.dumps(log_entry)

    outbox_files = sorted(tmp_path.glob("*.json"))
    assert len(outbox_files) == 1

    payload = json.loads(outbox_files[0].read_text())
    assert payload["to"] == "user@example.com"
    assert payload["subject"] == "Verify your account"
    assert payload["html_body"].startswith('<a href="http://localhost:5173/auth/verify-email')
    assert payload["links"] == [
        {
            "route_path": "/auth/verify-email",
            "token": "secret-token",
        }
    ]


@pytest.mark.asyncio
async def test_resend_email_sender_serializes_api_key_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    resend_module = ModuleType("resend")

    class Emails:
        @staticmethod
        def send(params: object) -> None:
            captured["params"] = params

    resend_module.Emails = Emails
    resend_module.api_key = None
    monkeypatch.setitem(__import__("sys").modules, "resend", resend_module)

    async def fake_to_thread(function, *args):
        function(*args)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    sender = ResendEmailSender(
        api_key="resend-test-key",
        email_from="noreply@example.com",
    )
    await sender.send(
        to="user@example.com",
        subject="Verify your account",
        html_body="<p>Hello</p>",
    )

    assert resend_module.api_key == "resend-test-key"
    assert captured["params"] == {
        "from": "noreply@example.com",
        "to": ["user@example.com"],
        "subject": "Verify your account",
        "html": "<p>Hello</p>",
    }


def test_build_email_sender_returns_resend_sender_when_configured() -> None:
    sender = build_email_sender(
        SimpleNamespace(
            email_backend="resend",
            email_from="noreply@example.com",
            email_outbox_dir=None,
            resend_api_key=SecretStr("resend-test-key"),
        )
    )

    assert isinstance(sender, ResendEmailSender)
