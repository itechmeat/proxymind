from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.db.models import User, UserProfile, UserRefreshToken, UserToken
from app.db.models.enums import TokenType, UserStatus
from app.services.email import EmailSender
from app.services.jwt_tokens import create_access_token
from app.services.passwords import hash_password, verify_password

GENERIC_REGISTRATION_MESSAGE = "Check your email to verify your account."
GENERIC_FORGOT_PASSWORD_MESSAGE = "If the account exists, reset instructions have been sent."


class InvalidCredentialsError(RuntimeError):
    """Raised when sign-in credentials are invalid."""


class InvalidTokenError(RuntimeError):
    """Raised when a verification, reset, or refresh token is invalid."""


class UserNotVerifiedError(RuntimeError):
    """Raised when a user attempts to sign in before verification."""


class UserBlockedError(RuntimeError):
    """Raised when a blocked user attempts to authenticate."""


@dataclass(slots=True, frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        email_sender: EmailSender,
    ) -> None:
        self._session = session
        self._settings = settings
        self._email_sender = email_sender

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> str:
        normalized_email = self._normalize_email(email)
        existing_user = await self._find_user_by_email(normalized_email)
        if existing_user is not None:
            return GENERIC_REGISTRATION_MESSAGE

        verification_token = self._generate_raw_token()
        now = datetime.now(UTC)
        user = User(
            id=uuid.uuid7(),
            email=normalized_email,
            password_hash=hash_password(password),
            status=UserStatus.PENDING,
        )
        profile = UserProfile(
            id=uuid.uuid7(),
            user=user,
            display_name=self._normalize_display_name(display_name),
        )
        verification_record = UserToken(
            id=uuid.uuid7(),
            user=user,
            token_hash=self._hash_token(verification_token),
            token_type=TokenType.EMAIL_VERIFICATION,
            expires_at=now + timedelta(hours=24),
            used_at=None,
            created_at=now,
        )
        self._session.add_all([user, profile, verification_record])
        try:
            await self._session.flush()
        except IntegrityError as error:
            await self._session.rollback()
            if self._is_duplicate_registration_error(error):
                return GENERIC_REGISTRATION_MESSAGE
            raise

        try:
            await self._email_sender.send(
                to=normalized_email,
                subject="Verify your ProxyMind account",
                html_body=self._build_verification_email(verification_token),
            )
        except Exception:
            await self._session.rollback()
            raise

        await self._session.commit()
        return GENERIC_REGISTRATION_MESSAGE

    async def verify_email(self, *, token: str) -> None:
        token_record = await self._load_user_token(
            token=token,
            token_type=TokenType.EMAIL_VERIFICATION,
        )
        if token_record is None:
            raise InvalidTokenError("Invalid or expired verification token")

        user = await self._session.get(User, token_record.user_id)
        if user is None:
            raise InvalidTokenError("Invalid or expired verification token")

        now = datetime.now(UTC)
        user.status = UserStatus.ACTIVE
        user.email_verified_at = now
        token_record.used_at = now
        await self._session.commit()

    async def sign_in(
        self,
        *,
        email: str,
        password: str,
        device_info: str | None = None,
    ) -> TokenPair:
        user = await self._load_user_with_profile(self._normalize_email(email))
        if user is None or not verify_password(user.password_hash, password):
            raise InvalidCredentialsError("Invalid email or password")
        if user.status is UserStatus.PENDING:
            raise UserNotVerifiedError("Email address is not verified")
        if user.status is UserStatus.BLOCKED:
            raise UserBlockedError("User account is blocked")

        refresh_token = await self._create_refresh_token(
            user_id=user.id,
            device_info=device_info,
        )
        return TokenPair(
            access_token=self._create_access_token(user.id),
            refresh_token=refresh_token,
        )

    async def refresh(
        self,
        *,
        refresh_token: str,
        device_info: str | None = None,
    ) -> TokenPair:
        token_hash = self._hash_token(refresh_token)
        token_record = await self._session.scalar(
            select(UserRefreshToken).where(
                UserRefreshToken.token_hash == token_hash,
                UserRefreshToken.expires_at > datetime.now(UTC),
            )
        )
        if token_record is None or not secrets.compare_digest(token_record.token_hash, token_hash):
            raise InvalidTokenError("Invalid or expired refresh token")

        user = await self._session.get(User, token_record.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            await self._session.delete(token_record)
            await self._session.commit()
            raise InvalidTokenError("Invalid or expired refresh token")

        await self._session.delete(token_record)
        new_refresh_token = await self._create_refresh_token(
            user_id=user.id,
            device_info=device_info,
            commit=False,
        )
        await self._session.commit()
        return TokenPair(
            access_token=self._create_access_token(user.id),
            refresh_token=new_refresh_token,
        )

    async def sign_out(self, *, refresh_token: str | None) -> None:
        if not refresh_token:
            return

        token_hash = self._hash_token(refresh_token)
        token_record = await self._session.scalar(
            select(UserRefreshToken).where(UserRefreshToken.token_hash == token_hash)
        )
        if token_record is not None and secrets.compare_digest(token_record.token_hash, token_hash):
            await self._session.delete(token_record)
            await self._session.commit()

    async def forgot_password(self, *, email: str) -> str:
        user = await self._find_user_by_email(self._normalize_email(email))
        if user is None or user.status is not UserStatus.ACTIVE:
            return GENERIC_FORGOT_PASSWORD_MESSAGE

        raw_token = self._generate_raw_token()
        now = datetime.now(UTC)
        reset_token = UserToken(
            id=uuid.uuid7(),
            user_id=user.id,
            token_hash=self._hash_token(raw_token),
            token_type=TokenType.PASSWORD_RESET,
            expires_at=now + timedelta(hours=1),
            used_at=None,
            created_at=now,
        )
        self._session.add(reset_token)
        await self._session.flush()

        try:
            await self._email_sender.send(
                to=user.email,
                subject="Reset your ProxyMind password",
                html_body=self._build_reset_email(raw_token),
            )
        except Exception:
            await self._session.rollback()
            raise

        await self._session.commit()
        return GENERIC_FORGOT_PASSWORD_MESSAGE

    async def reset_password(self, *, token: str, new_password: str) -> None:
        token_record = await self._load_user_token(
            token=token,
            token_type=TokenType.PASSWORD_RESET,
        )
        if token_record is None:
            raise InvalidTokenError("Invalid or expired reset token")

        user = await self._session.get(User, token_record.user_id)
        if user is None:
            raise InvalidTokenError("Invalid or expired reset token")

        user.password_hash = hash_password(new_password)
        token_record.used_at = datetime.now(UTC)
        await self._session.execute(
            delete(UserRefreshToken).where(UserRefreshToken.user_id == user.id)
        )
        await self._session.commit()

    async def get_user_with_profile(self, *, user_id: uuid.UUID) -> tuple[User, UserProfile]:
        user = await self._session.scalar(
            select(User)
            .options(selectinload(User.profile))
            .where(User.id == user_id)
        )
        if user is None:
            raise InvalidCredentialsError("User not found")

        profile = user.profile or UserProfile(id=uuid.uuid7(), user_id=user.id)
        if user.profile is None:
            self._session.add(profile)
            await self._session.commit()
            await self._session.refresh(user)

        return user, profile

    async def update_profile(
        self,
        *,
        user_id: uuid.UUID,
        display_name: str | None = None,
        avatar_url: str | None = None,
        update_display_name: bool = False,
        update_avatar_url: bool = False,
    ) -> tuple[User, UserProfile]:
        user, profile = await self.get_user_with_profile(user_id=user_id)

        if update_display_name:
            profile.display_name = self._normalize_display_name(display_name)
        if update_avatar_url:
            profile.avatar_url = avatar_url.strip() if avatar_url is not None else None

        await self._session.commit()
        await self._session.refresh(user)
        await self._session.refresh(profile)
        return user, profile

    @staticmethod
    def _normalize_email(value: str) -> str:
        return value.strip().lower()

    @staticmethod
    def _normalize_display_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _generate_raw_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_duplicate_registration_error(error: IntegrityError) -> bool:
        message = " ".join(
            part.lower()
            for part in (
                error.statement or "",
                str(error.orig),
            )
        )
        return (
            getattr(error.orig, "sqlstate", None) == "23505"
            or "duplicate key" in message
            or "unique constraint" in message
        ) and "users" in message

    async def _find_user_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def _load_user_with_profile(self, email: str) -> User | None:
        return await self._session.scalar(
            select(User)
            .options(selectinload(User.profile))
            .where(User.email == email)
        )

    async def _load_user_token(
        self,
        *,
        token: str,
        token_type: TokenType,
    ) -> UserToken | None:
        token_hash = self._hash_token(token)
        token_record = await self._session.scalar(
            select(UserToken).where(
                UserToken.token_hash == token_hash,
                UserToken.token_type == token_type,
                UserToken.used_at.is_(None),
                UserToken.expires_at > datetime.now(UTC),
            )
        )
        if token_record is None:
            return None
        if not secrets.compare_digest(token_record.token_hash, token_hash):
            return None
        return token_record

    async def _create_refresh_token(
        self,
        *,
        user_id: uuid.UUID,
        device_info: str | None = None,
        commit: bool = True,
    ) -> str:
        now = datetime.now(UTC)
        refresh_token = self._generate_raw_token()
        refresh_record = UserRefreshToken(
            id=uuid.uuid7(),
            user_id=user_id,
            token_hash=self._hash_token(refresh_token),
            device_info=device_info,
            expires_at=now + timedelta(days=self._settings.jwt_refresh_token_expire_days),
            created_at=now,
        )
        self._session.add(refresh_record)
        await self._session.flush()
        if commit:
            await self._session.commit()
        return refresh_token

    def _create_access_token(self, user_id: uuid.UUID) -> str:
        return create_access_token(
            user_id=user_id,
            secret_key=self._settings.jwt_secret_key.get_secret_value(),
            expires_minutes=self._settings.jwt_access_token_expire_minutes,
        )

    def _build_verification_email(self, token: str) -> str:
        url = f"{self._settings.frontend_url.rstrip('/')}/auth/verify-email?token={token}"
        return (
            "<p>Welcome to ProxyMind.</p>"
            f"<p><a href=\"{url}\">Verify your email address</a></p>"
        )

    def _build_reset_email(self, token: str) -> str:
        url = f"{self._settings.frontend_url.rstrip('/')}/auth/reset-password?token={token}"
        return (
            "<p>Reset your ProxyMind password.</p>"
            f"<p><a href=\"{url}\">Choose a new password</a></p>"
        )


async def cleanup_auth_tokens(ctx: dict[str, object]) -> None:
    session_factory = ctx["session_factory"]
    now = datetime.now(UTC)
    used_tokens_before = now - timedelta(hours=24)

    async with session_factory() as session:
        await session.execute(
            delete(UserToken).where(
                (UserToken.expires_at < now)
                | (
                    UserToken.used_at.is_not(None)
                    & (UserToken.created_at < used_tokens_before)
                )
            )
        )
        await session.execute(delete(UserRefreshToken).where(UserRefreshToken.expires_at < now))
        await session.commit()
