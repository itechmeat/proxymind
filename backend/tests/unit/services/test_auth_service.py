from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import UserRefreshToken, UserToken
from app.db.models.enums import TokenType
from app.services.auth import (
    GENERIC_REGISTRATION_MESSAGE,
    AuthService,
    InvalidTokenError,
    cleanup_auth_tokens,
)

TEST_JWT_SECRET = SecretStr("test-jwt-secret-key-with-32-plus-chars")


@dataclass(slots=True)
class DeliveredEmail:
    html_body: str
    subject: str
    to: str


class CapturingEmailSender:
    def __init__(self) -> None:
        self.deliveries: list[DeliveredEmail] = []

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        self.deliveries.append(DeliveredEmail(to=to, subject=subject, html_body=html_body))


def _make_settings() -> SimpleNamespace:
    return SimpleNamespace(
        frontend_url="http://frontend.test",
        jwt_access_token_expire_minutes=15,
        jwt_refresh_token_expire_days=30,
        jwt_secret_key=TEST_JWT_SECRET,
    )


def _extract_token(delivery: DeliveredEmail, *, route_path: str) -> str:
    start = delivery.html_body.index('href="') + len('href="')
    end = delivery.html_body.index('"', start)
    url = delivery.html_body[start:end]
    parsed = urlparse(url)
    assert parsed.path == route_path
    token = parse_qs(parsed.query).get("token", [None])[0]
    assert token is not None
    return token


@pytest.mark.asyncio
async def test_register_returns_generic_message_when_insert_loses_uniqueness_race() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock(
        side_effect=IntegrityError("INSERT INTO users ...", {}, RuntimeError("duplicate key"))
    )
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.add_all = MagicMock()
    email_sender = SimpleNamespace(send=AsyncMock())

    auth_service = AuthService(
        session=session,
        settings=_make_settings(),
        email_sender=email_sender,
    )

    detail = await auth_service.register(
        email="race@example.com",
        password="Start123!",
        display_name="Race User",
    )

    assert detail == GENERIC_REGISTRATION_MESSAGE
    session.rollback.assert_awaited_once()
    email_sender.send.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_reset_password_revokes_existing_refresh_tokens(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    email_sender = CapturingEmailSender()
    password = "Start123!"
    new_password = "Updated123!"

    async with session_factory() as session:
        auth_service = AuthService(
            session=session,
            settings=_make_settings(),
            email_sender=email_sender,
        )

        detail = await auth_service.register(
            email="security@example.com",
            password=password,
            display_name="Security User",
        )
        assert detail == GENERIC_REGISTRATION_MESSAGE

        verify_token = _extract_token(
            email_sender.deliveries[-1],
            route_path="/auth/verify-email",
        )
        await auth_service.verify_email(token=verify_token)

        initial_tokens = await auth_service.sign_in(
            email="security@example.com",
            password=password,
        )

        await auth_service.forgot_password(email="security@example.com")
        reset_token = _extract_token(
            email_sender.deliveries[-1],
            route_path="/auth/reset-password",
        )
        await auth_service.reset_password(
            token=reset_token,
            new_password=new_password,
        )

        with pytest.raises(InvalidTokenError, match="Invalid or expired refresh token"):
            await auth_service.refresh(refresh_token=initial_tokens.refresh_token)

        replacement_tokens = await auth_service.sign_in(
            email="security@example.com",
            password=new_password,
        )
        assert replacement_tokens.access_token


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_cleanup_auth_tokens_deletes_consumed_tokens_older_than_24h_by_creation_time(
    session_factory: async_sessionmaker[AsyncSession],
    create_user,
) -> None:
    user = await create_user(email="cleanup@example.com")
    now = datetime.now(UTC)
    stale_created_token_id = uuid.uuid7()
    recent_created_token_id = uuid.uuid7()
    expired_token_id = uuid.uuid7()
    expired_refresh_token_id = uuid.uuid7()
    active_refresh_token_id = uuid.uuid7()

    async with session_factory() as session:
        session.add_all(
            [
                UserToken(
                    id=stale_created_token_id,
                    user_id=user.id,
                    token_hash="recent-used",
                    token_type=TokenType.EMAIL_VERIFICATION,
                    expires_at=now + timedelta(hours=1),
                    used_at=now - timedelta(hours=1),
                    created_at=now - timedelta(days=2),
                ),
                UserToken(
                    id=recent_created_token_id,
                    user_id=user.id,
                    token_hash="stale-used",
                    token_type=TokenType.PASSWORD_RESET,
                    expires_at=now + timedelta(hours=1),
                    used_at=now - timedelta(hours=1),
                    created_at=now - timedelta(hours=2),
                ),
                UserToken(
                    id=expired_token_id,
                    user_id=user.id,
                    token_hash="expired-token",
                    token_type=TokenType.PASSWORD_RESET,
                    expires_at=now - timedelta(minutes=5),
                    used_at=None,
                    created_at=now - timedelta(hours=2),
                ),
                UserRefreshToken(
                    id=expired_refresh_token_id,
                    user_id=user.id,
                    token_hash="expired-refresh",
                    device_info=None,
                    expires_at=now - timedelta(minutes=5),
                    created_at=now - timedelta(days=1),
                ),
                UserRefreshToken(
                    id=active_refresh_token_id,
                    user_id=user.id,
                    token_hash="active-refresh",
                    device_info=None,
                    expires_at=now + timedelta(days=1),
                    created_at=now - timedelta(hours=1),
                ),
            ]
        )
        await session.commit()

    await cleanup_auth_tokens({"session_factory": session_factory})

    async with session_factory() as session:
        remaining_tokens = {
            token.id for token in (await session.scalars(select(UserToken))).all()
        }
        remaining_refresh_tokens = {
            token.id for token in (await session.scalars(select(UserRefreshToken))).all()
        }

    assert stale_created_token_id not in remaining_tokens
    assert recent_created_token_id in remaining_tokens
    assert expired_token_id not in remaining_tokens
    assert active_refresh_token_id in remaining_refresh_tokens
    assert expired_refresh_token_id not in remaining_refresh_tokens
