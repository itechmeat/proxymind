# S7-03: End-User Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect all chat endpoints behind email-based end-user authentication while keeping admin auth separate.

**Architecture:** JWT access tokens (15 min, HS256) + refresh tokens (7 days, rotated, PostgreSQL). Pluggable email service (console for dev, Resend for prod). New `users`, `user_profiles`, `user_tokens`, `user_refresh_tokens` tables. FastAPI dependency `get_current_user` guards the chat router.

**Tech Stack:** PyJWT, argon2-cffi, resend (Python SDK), React Context for frontend auth state.

**Spec:** `docs/superpowers/specs/2026-04-04-s7-03-end-user-auth-design.md`

---

## File Map

### Backend — New Files

| File | Responsibility |
|------|---------------|
| `backend/app/db/models/auth.py` | User, UserProfile, UserToken, UserRefreshToken SQLAlchemy models |
| `backend/app/api/auth_schemas.py` | Pydantic request/response schemas for all auth endpoints |
| `backend/app/api/auth_router.py` | FastAPI router for `/api/auth/*` endpoints |
| `backend/app/api/auth_dependencies.py` | `get_current_user` dependency, JWT decode |
| `backend/app/services/auth.py` | Auth business logic: register, verify, sign-in, refresh, reset |
| `backend/app/services/email.py` | EmailSender protocol + ConsoleEmailSender + ResendEmailSender |
| `backend/app/services/password.py` | argon2id hash/verify wrapper |
| `backend/app/services/jwt.py` | JWT encode/decode helpers |
| `backend/migrations/versions/018_add_user_auth_tables.py` | Alembic migration: users, user_profiles, user_tokens, user_refresh_tokens, rename visitor_id |
| `backend/tests/unit/test_password.py` | Password hashing tests |
| `backend/tests/unit/test_jwt.py` | JWT encode/decode tests |
| `backend/tests/unit/test_email.py` | Email service tests |
| `backend/tests/unit/test_auth_service.py` | Auth service tests |
| `backend/tests/unit/test_auth_router.py` | Auth endpoint tests |
| `backend/tests/unit/test_auth_dependencies.py` | get_current_user tests |
| `backend/tests/unit/test_chat_auth.py` | Chat endpoint protection tests |

### Backend — Modified Files

| File | Changes |
|------|---------|
| `backend/app/db/models/enums.py` | Add `UserStatus`, `TokenType` enums |
| `backend/app/db/models/__init__.py` | Export new models |
| `backend/app/db/models/dialogue.py` | Rename `visitor_id` → `user_id`, add FK |
| `backend/app/core/config.py` | Add JWT + email settings |
| `backend/app/main.py` | Include auth_router, wire email service |
| `backend/app/api/chat.py` | Add `get_current_user` dependency, pass user to service |
| `backend/app/api/chat_schemas.py` | Add `user_id` to SessionResponse |
| `backend/app/services/chat.py` | Accept `user_id` in `create_session`, enforce ownership |
| `backend/app/api/dependencies.py` | Add `get_email_service` dependency |

### Frontend — New Files

| File | Responsibility |
|------|---------------|
| `frontend/src/contexts/AuthContext.tsx` | AuthProvider, useUserAuth hook, token management |
| `frontend/src/lib/auth-api.ts` | Auth API client (register, sign-in, refresh, etc.) |
| `frontend/src/pages/AuthPage/AuthPage.tsx` | AuthLayout wrapper |
| `frontend/src/pages/AuthPage/SignInPage.tsx` | Sign-in form |
| `frontend/src/pages/AuthPage/RegisterPage.tsx` | Registration form |
| `frontend/src/pages/AuthPage/ForgotPasswordPage.tsx` | Forgot password form |
| `frontend/src/pages/AuthPage/ResetPasswordPage.tsx` | Reset password form |
| `frontend/src/pages/AuthPage/VerifyEmailPage.tsx` | Email verification page |
| `frontend/src/pages/AuthPage/index.ts` | Barrel exports |
| `frontend/src/components/ProtectedRoute/ProtectedRoute.tsx` | Auth guard component |
| `frontend/src/components/ProtectedRoute/index.ts` | Barrel export |
| `frontend/src/pages/AdminPage/AdminSignInPage.tsx` | Dedicated admin API key sign-in page |

### Frontend — Modified Files

| File | Changes |
|------|---------|
| `frontend/src/App.tsx` | Add auth routes, wrap chat in ProtectedRoute, add AuthProvider, replace AdminRouteGuard modal with route |
| `frontend/src/lib/api.ts` | Add auth header to chat requests |
| `frontend/src/lib/transport.ts` | Add auth header to SSE requests |
| `frontend/src/main.tsx` | No auth changes needed (AuthProvider is in App.tsx) |
| `frontend/src/hooks/useSession.ts` | User-scoped session persistence: clear on logout, handle 403 |
| `frontend/src/tests/**` | Update existing tests for auth-protected endpoints |
| `backend/app/middleware/rate_limit.py` | Extend rate limiting to `/api/auth/*` |
| `backend/app/api/profile.py` | Protect twin profile chat endpoints with auth |

---

## Task 1: Backend Enums and Password Utility

**Files:**
- Modify: `backend/app/db/models/enums.py`
- Create: `backend/app/services/password.py`
- Create: `backend/tests/unit/test_password.py`

- [ ] **Step 1: Add UserStatus and TokenType enums**

In `backend/app/db/models/enums.py`, add after `AuditLogStatus` (after line 116):

```python
class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"


class TokenType(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
```

- [ ] **Step 2: Write failing tests for password hashing**

Create `backend/tests/unit/test_password.py`:

```python
import pytest

from app.services.password import hash_password, verify_password


def test_hash_password_returns_argon2id_hash():
    hashed = hash_password("mysecretpassword")
    assert hashed.startswith("$argon2id$")


def test_verify_password_correct():
    hashed = hash_password("mysecretpassword")
    assert verify_password("mysecretpassword", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("mysecretpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_hash_password_produces_different_hashes():
    hash1 = hash_password("same")
    hash2 = hash_password("same")
    assert hash1 != hash2  # different salts
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/unit/test_password.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.password'`

- [ ] **Step 4: Implement password service**

Create `backend/app/services/password.py`:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/unit/test_password.py -v`
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/enums.py backend/app/services/password.py backend/tests/unit/test_password.py
git commit -m "feat(auth): add UserStatus/TokenType enums and argon2id password hashing"
```

---

## Task 2: JWT Utility

**Files:**
- Create: `backend/app/services/jwt.py`
- Create: `backend/tests/unit/test_jwt.py`

- [ ] **Step 1: Write failing tests for JWT**

Create `backend/tests/unit/test_jwt.py`:

```python
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.services.jwt import JWTError, create_access_token, decode_access_token


def test_create_and_decode_access_token():
    user_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id,
        secret_key="test-secret",
        expires_delta=timedelta(minutes=15),
    )
    payload = decode_access_token(token, secret_key="test-secret")
    assert payload.user_id == user_id
    assert payload.jti is not None


def test_decode_expired_token():
    user_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id,
        secret_key="test-secret",
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(JWTError, match="expired"):
        decode_access_token(token, secret_key="test-secret")


def test_decode_invalid_token():
    with pytest.raises(JWTError):
        decode_access_token("not.a.token", secret_key="test-secret")


def test_decode_wrong_secret():
    user_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id,
        secret_key="correct-secret",
        expires_delta=timedelta(minutes=15),
    )
    with pytest.raises(JWTError):
        decode_access_token(token, secret_key="wrong-secret")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/unit/test_jwt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.jwt'`

- [ ] **Step 3: Implement JWT service**

Create `backend/app/services/jwt.py`:

```python
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt


class JWTError(Exception):
    pass


@dataclass(frozen=True)
class AccessTokenPayload:
    user_id: uuid.UUID
    jti: str
    exp: datetime


def create_access_token(
    *,
    user_id: uuid.UUID,
    secret_key: str,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(token: str, *, secret_key: str) -> AccessTokenPayload:
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise JWTError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise JWTError(f"Invalid token: {exc}") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise JWTError("Invalid token payload") from exc

    return AccessTokenPayload(
        user_id=user_id,
        jti=payload.get("jti", ""),
        exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/unit/test_jwt.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/jwt.py backend/tests/unit/test_jwt.py
git commit -m "feat(auth): add JWT access token creation and verification"
```

---

## Task 3: Email Service

**Files:**
- Create: `backend/app/services/email.py`
- Create: `backend/tests/unit/test_email.py`

- [ ] **Step 1: Write failing tests for email service**

Create `backend/tests/unit/test_email.py`:

```python
import pytest

from app.services.email import ConsoleEmailSender, build_email_sender


@pytest.mark.asyncio
async def test_console_email_sender_logs(caplog):
    sender = ConsoleEmailSender()
    with caplog.at_level("INFO"):
        await sender.send(
            to="user@example.com",
            subject="Test Subject",
            html_body="<p>Hello</p>",
        )
    assert "user@example.com" in caplog.text
    assert "Test Subject" in caplog.text


def test_build_email_sender_console():
    sender = build_email_sender(backend="console")
    assert isinstance(sender, ConsoleEmailSender)


def test_build_email_sender_resend():
    sender = build_email_sender(
        backend="resend",
        resend_api_key="re_test_key",
        email_from="noreply@example.com",
    )
    from app.services.email import ResendEmailSender

    assert isinstance(sender, ResendEmailSender)


def test_build_email_sender_unknown():
    with pytest.raises(ValueError, match="Unknown email backend"):
        build_email_sender(backend="unknown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/unit/test_email.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.email'`

- [ ] **Step 3: Implement email service**

Create `backend/app/services/email.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html_body: str) -> None: ...


class ConsoleEmailSender:
    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        logger.info(
            "email.sent_to_console",
            to=to,
            subject=subject,
            body_preview=html_body[:200],
        )


class ResendEmailSender:
    def __init__(self, *, api_key: str, email_from: str) -> None:
        import resend

        resend.api_key = api_key
        self._email_from = email_from
        self._resend = resend

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        self._resend.Emails.send(
            {
                "from": self._email_from,
                "to": [to],
                "subject": subject,
                "html": html_body,
            }
        )
        logger.info("email.sent_via_resend", to=to, subject=subject)


def build_email_sender(
    *,
    backend: str = "console",
    resend_api_key: str | None = None,
    email_from: str = "noreply@example.com",
) -> EmailSender:
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "resend":
        if not resend_api_key:
            raise ValueError("RESEND_API_KEY is required for resend backend")
        return ResendEmailSender(api_key=resend_api_key, email_from=email_from)
    raise ValueError(f"Unknown email backend: {backend}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/unit/test_email.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/email.py backend/tests/unit/test_email.py
git commit -m "feat(auth): add pluggable email service (console + Resend)"
```

---

## Task 4: Config Settings for Auth

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/unit/test_config.py` (if relevant assertions need updating)

- [ ] **Step 1: Add auth settings to config**

In `backend/app/core/config.py`, add the following fields to the `Settings` class after the `chat_rate_window_seconds` field (after line 102):

```python
    # Auth
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_access_token_expire_minutes: int = Field(default=15, ge=1)
    jwt_refresh_token_expire_days: int = Field(default=7, ge=1)
    email_backend: Literal["console", "resend"] = Field(default="console")
    resend_api_key: str | None = Field(default=None)
    email_from: str = Field(default="noreply@example.com")
    frontend_url: str = Field(default="http://localhost:5173")
```

Also add `"resend_api_key"` to the `normalize_empty_optional_strings` list.

Add a computed property for cookie security:

```python
@computed_field
@property
def cookie_secure(self) -> bool:
    return self.frontend_url.startswith("https://")
```

- [ ] **Step 2: Update .env.example files**

Add to `backend/.env.example`:

```
# Auth
JWT_SECRET_KEY=change-me-to-a-long-random-string-at-least-32-chars
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
EMAIL_BACKEND=console
RESEND_API_KEY=
EMAIL_FROM=noreply@example.com
FRONTEND_URL=http://localhost:5173
```

Add to root `.env.example` if relevant.

- [ ] **Step 3: Verify existing config tests still pass**

Run: `docker compose exec backend pytest tests/unit/test_config.py -v`
Expected: All existing tests pass (may need to add JWT_SECRET_KEY to test env).

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/config.py backend/.env.example .env.example
git commit -m "feat(auth): add JWT and email configuration settings"
```

---

## Task 5: Database Models

**Files:**
- Create: `backend/app/db/models/auth.py`
- Modify: `backend/app/db/models/__init__.py`

- [ ] **Step 1: Create auth models**

Create `backend/app/db/models/auth.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin
from app.db.models.enums import TokenType, UserStatus, pg_enum


class User(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, name="user_status_enum"),
        nullable=False,
        default=UserStatus.PENDING,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[UserRefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    tokens: Mapped[list[UserToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserProfile(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")


class UserToken(PrimaryKeyMixin, Base):
    __tablename__ = "user_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    token_type: Mapped[TokenType] = mapped_column(
        pg_enum(TokenType, name="token_type_enum"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=__import__("sqlalchemy").func.now(),
    )

    user: Mapped[User] = relationship(back_populates="tokens")


class UserRefreshToken(PrimaryKeyMixin, Base):
    __tablename__ = "user_refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    device_info: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=__import__("sqlalchemy").func.now(),
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
```

- [ ] **Step 2: Update model exports**

In `backend/app/db/models/__init__.py`, add imports:

```python
from app.db.models.auth import User, UserProfile, UserRefreshToken, UserToken
```

And add to `__all__`:

```python
    "User",
    "UserProfile",
    "UserRefreshToken",
    "UserToken",
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/auth.py backend/app/db/models/__init__.py
git commit -m "feat(auth): add User, UserProfile, UserToken, UserRefreshToken models"
```

---

## Task 6: Alembic Migration

**Files:**
- Create: `backend/migrations/versions/018_add_user_auth_tables.py`
- Modify: `backend/app/db/models/dialogue.py`

- [ ] **Step 1: Update Session model — rename visitor_id to user_id**

In `backend/app/db/models/dialogue.py`, replace line 41:

```python
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
```

with:

```python
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
```

Also add the import for `User` relationship if needed — or leave it as a simple FK without relationship for now (the Session model already has `messages` relationship, adding `user` is optional).

- [ ] **Step 2: Generate migration**

Run: `docker compose exec backend alembic revision --autogenerate -m "add user auth tables"`

Review the generated migration. It should contain:
- Create `users` table with `user_status_enum` PostgreSQL enum
- Create `user_profiles` table
- Create `user_tokens` table with `token_type_enum` PostgreSQL enum
- Create `user_refresh_tokens` table
- Rename `sessions.visitor_id` → `sessions.user_id`
- Add FK constraint `sessions.user_id → users.id`

**Important:** Autogenerate may not detect the column rename. If it generates DROP + ADD instead, manually edit to use `op.alter_column('sessions', 'visitor_id', new_column_name='user_id')` and then add the FK separately.

- [ ] **Step 3: Run migration**

Run: `docker compose exec backend alembic upgrade head`
Expected: Migration completes successfully.

- [ ] **Step 4: Verify migration**

Run: `docker compose exec backend alembic current`
Expected: Shows the new migration as current head.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/018_add_user_auth_tables.py backend/app/db/models/dialogue.py
git commit -m "feat(auth): add migration for user auth tables and rename visitor_id"
```

---

## Task 7: Auth Service

**Files:**
- Create: `backend/app/services/auth.py`
- Create: `backend/tests/unit/test_auth_service.py`

- [ ] **Step 1: Write failing tests for auth service**

Create `backend/tests/unit/test_auth_service.py`:

```python
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.auth import User, UserProfile, UserRefreshToken, UserToken
from app.db.models.enums import TokenType, UserStatus
from app.services.auth import AuthService


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_email_sender():
    return AsyncMock()


@pytest.fixture
def auth_service(mock_session, mock_email_sender):
    return AuthService(
        session=mock_session,
        email_sender=mock_email_sender,
        jwt_secret_key="test-secret-key-at-least-32-chars!!",
        access_token_expire_minutes=15,
        refresh_token_expire_days=7,
        frontend_url="http://localhost:5173",
    )


@pytest.mark.asyncio
async def test_register_creates_user_with_pending_status(auth_service, mock_session):
    # Simulate no existing user
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    await auth_service.register(
        email="test@example.com",
        password="StrongPass123!",
        display_name="Test User",
    )

    mock_session.add.assert_called()
    added_user = mock_session.add.call_args_list[0][0][0]
    assert isinstance(added_user, User)
    assert added_user.email == "test@example.com"
    assert added_user.status == UserStatus.PENDING


@pytest.mark.asyncio
async def test_register_duplicate_email_no_error(auth_service, mock_session):
    """Registration with existing email should silently succeed (enumeration protection)."""
    existing_user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="$argon2id$...",
        status=UserStatus.ACTIVE,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user
    mock_session.execute.return_value = mock_result

    # Should not raise
    await auth_service.register(
        email="test@example.com",
        password="StrongPass123!",
    )


@pytest.mark.asyncio
async def test_register_sends_verification_email(auth_service, mock_email_sender, mock_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    await auth_service.register(email="test@example.com", password="StrongPass123!")

    mock_email_sender.send.assert_called_once()
    call_kwargs = mock_email_sender.send.call_args[1]
    assert call_kwargs["to"] == "test@example.com"
    assert "verify" in call_kwargs["subject"].lower() or "verify" in call_kwargs["html_body"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/unit/test_auth_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.auth'`

- [ ] **Step 3: Implement auth service**

Create `backend/app/services/auth.py`:

```python
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import User, UserProfile, UserRefreshToken, UserToken
from app.db.models.enums import TokenType, UserStatus
from app.services.email import EmailSender
from app.services.jwt import JWTError, create_access_token, decode_access_token
from app.services.password import hash_password, verify_password

logger = structlog.get_logger(__name__)


class AuthError(Exception):
    pass


class InvalidCredentialsError(AuthError):
    pass


class AccountNotVerifiedError(AuthError):
    pass


class AccountBlockedError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        email_sender: EmailSender,
        jwt_secret_key: str,
        access_token_expire_minutes: int = 15,
        refresh_token_expire_days: int = 7,
        frontend_url: str = "http://localhost:5173",
        cookie_secure: bool = False,
    ) -> None:
        self._session = session
        self._email_sender = email_sender
        self._jwt_secret_key = jwt_secret_key
        self._access_token_expire_minutes = access_token_expire_minutes
        self._refresh_token_expire_days = refresh_token_expire_days
        self._frontend_url = frontend_url
        self.cookie_secure = cookie_secure

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> None:
        """Register a new user. Always succeeds silently (enumeration protection)."""
        email_lower = email.lower().strip()

        result = await self._session.execute(
            select(User).where(User.email == email_lower)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            logger.info("auth.register.duplicate_email", email=email_lower)
            return

        user = User(
            id=uuid.uuid7(),
            email=email_lower,
            password_hash=hash_password(password),
            status=UserStatus.PENDING,
        )
        self._session.add(user)

        profile = UserProfile(
            id=uuid.uuid7(),
            user_id=user.id,
            display_name=display_name,
        )
        self._session.add(profile)

        token_raw = secrets.token_urlsafe(32)
        token = UserToken(
            id=uuid.uuid7(),
            user_id=user.id,
            token_hash=_hash_token(token_raw),
            token_type=TokenType.EMAIL_VERIFICATION,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        self._session.add(token)
        await self._session.commit()

        verify_url = f"{self._frontend_url}/auth/verify-email?token={token_raw}"
        await self._email_sender.send(
            to=email_lower,
            subject="Verify your email — ProxyMind",
            html_body=(
                f"<p>Welcome to ProxyMind!</p>"
                f'<p><a href="{verify_url}">Click here to verify your email</a></p>'
                f"<p>This link expires in 24 hours.</p>"
            ),
        )

    async def verify_email(self, *, token: str) -> None:
        """Verify email with token. Activates user account."""
        token_hash = _hash_token(token)
        now = datetime.now(UTC)

        result = await self._session.execute(
            select(UserToken).where(
                UserToken.token_hash == token_hash,
                UserToken.token_type == TokenType.EMAIL_VERIFICATION,
                UserToken.used_at.is_(None),
                UserToken.expires_at > now,
            )
        )
        db_token = result.scalar_one_or_none()
        if db_token is None:
            raise InvalidTokenError("Invalid or expired verification token")

        db_token.used_at = now

        result = await self._session.execute(
            select(User).where(User.id == db_token.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise InvalidTokenError("User not found")

        user.status = UserStatus.ACTIVE
        user.email_verified_at = now
        await self._session.commit()

    async def sign_in(
        self,
        *,
        email: str,
        password: str,
        device_info: str | None = None,
    ) -> tuple[str, str]:
        """Sign in. Returns (access_token, refresh_token_raw)."""
        email_lower = email.lower().strip()

        result = await self._session.execute(
            select(User).where(User.email == email_lower)
        )
        user = result.scalar_one_or_none()

        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")

        if user.status == UserStatus.PENDING:
            raise AccountNotVerifiedError("Please verify your email first")

        if user.status == UserStatus.BLOCKED:
            raise AccountBlockedError("Account is blocked")

        access_token = create_access_token(
            user_id=user.id,
            secret_key=self._jwt_secret_key,
            expires_delta=timedelta(minutes=self._access_token_expire_minutes),
        )

        refresh_token_raw = secrets.token_urlsafe(32)
        refresh_token = UserRefreshToken(
            id=uuid.uuid7(),
            user_id=user.id,
            token_hash=_hash_token(refresh_token_raw),
            device_info=device_info,
            expires_at=datetime.now(UTC) + timedelta(days=self._refresh_token_expire_days),
        )
        self._session.add(refresh_token)
        await self._session.commit()

        return access_token, refresh_token_raw

    async def refresh(self, *, refresh_token_raw: str) -> tuple[str, str]:
        """Rotate refresh token. Returns (new_access_token, new_refresh_token_raw)."""
        token_hash = _hash_token(refresh_token_raw)
        now = datetime.now(UTC)

        result = await self._session.execute(
            select(UserRefreshToken).where(
                UserRefreshToken.token_hash == token_hash,
                UserRefreshToken.expires_at > now,
            )
        )
        db_token = result.scalar_one_or_none()
        if db_token is None:
            raise InvalidTokenError("Invalid or expired refresh token")

        result = await self._session.execute(
            select(User).where(User.id == db_token.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None or user.status != UserStatus.ACTIVE:
            raise InvalidTokenError("User not found or inactive")

        # Delete old refresh token (rotation)
        await self._session.delete(db_token)

        # Create new tokens
        access_token = create_access_token(
            user_id=user.id,
            secret_key=self._jwt_secret_key,
            expires_delta=timedelta(minutes=self._access_token_expire_minutes),
        )

        new_refresh_raw = secrets.token_urlsafe(32)
        new_refresh = UserRefreshToken(
            id=uuid.uuid7(),
            user_id=user.id,
            token_hash=_hash_token(new_refresh_raw),
            device_info=db_token.device_info,
            expires_at=datetime.now(UTC) + timedelta(days=self._refresh_token_expire_days),
        )
        self._session.add(new_refresh)
        await self._session.commit()

        return access_token, new_refresh_raw

    async def sign_out(self, *, refresh_token_raw: str) -> None:
        """Delete refresh token (logout)."""
        token_hash = _hash_token(refresh_token_raw)

        result = await self._session.execute(
            select(UserRefreshToken).where(UserRefreshToken.token_hash == token_hash)
        )
        db_token = result.scalar_one_or_none()
        if db_token is not None:
            await self._session.delete(db_token)
            await self._session.commit()

    async def forgot_password(self, *, email: str) -> None:
        """Send password reset email. Always succeeds (enumeration protection)."""
        email_lower = email.lower().strip()

        result = await self._session.execute(
            select(User).where(User.email == email_lower)
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.info("auth.forgot_password.unknown_email", email=email_lower)
            return

        token_raw = secrets.token_urlsafe(32)
        token = UserToken(
            id=uuid.uuid7(),
            user_id=user.id,
            token_hash=_hash_token(token_raw),
            token_type=TokenType.PASSWORD_RESET,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        self._session.add(token)
        await self._session.commit()

        reset_url = f"{self._frontend_url}/auth/reset-password?token={token_raw}"
        await self._email_sender.send(
            to=email_lower,
            subject="Reset your password — ProxyMind",
            html_body=(
                f"<p>You requested a password reset.</p>"
                f'<p><a href="{reset_url}">Click here to reset your password</a></p>'
                f"<p>This link expires in 1 hour. If you didn't request this, ignore this email.</p>"
            ),
        )

    async def reset_password(self, *, token: str, new_password: str) -> None:
        """Reset password using token."""
        token_hash = _hash_token(token)
        now = datetime.now(UTC)

        result = await self._session.execute(
            select(UserToken).where(
                UserToken.token_hash == token_hash,
                UserToken.token_type == TokenType.PASSWORD_RESET,
                UserToken.used_at.is_(None),
                UserToken.expires_at > now,
            )
        )
        db_token = result.scalar_one_or_none()
        if db_token is None:
            raise InvalidTokenError("Invalid or expired reset token")

        db_token.used_at = now

        result = await self._session.execute(
            select(User).where(User.id == db_token.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise InvalidTokenError("User not found")

        user.password_hash = hash_password(new_password)
        await self._session.commit()

    async def get_user_with_profile(self, *, user_id: uuid.UUID) -> User | None:
        """Load user with profile for /me endpoint."""
        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is not None:
            await self._session.refresh(user, ["profile"])
        return user

    async def update_profile(
        self,
        *,
        user_id: uuid.UUID,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> User:
        """Update user profile fields. Returns user with refreshed profile."""
        user = await self.get_user_with_profile(user_id=user_id)
        if user is None or user.profile is None:
            raise InvalidTokenError("User or profile not found")

        if display_name is not None:
            user.profile.display_name = display_name
        if avatar_url is not None:
            user.profile.avatar_url = avatar_url

        await self._session.commit()
        await self._session.refresh(user.profile)
        return user
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/unit/test_auth_service.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auth.py backend/tests/unit/test_auth_service.py
git commit -m "feat(auth): add AuthService with register, sign-in, refresh, password reset"
```

---

## Task 8: Auth Dependency (get_current_user)

**Files:**
- Create: `backend/app/api/auth_dependencies.py`
- Create: `backend/tests/unit/test_auth_dependencies.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_auth_dependencies.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.auth_dependencies import get_current_user
from app.db.models.auth import User
from app.db.models.enums import UserStatus


@pytest.mark.asyncio
async def test_get_current_user_valid_token(monkeypatch):
    user_id = uuid.uuid4()
    user = User(id=user_id, email="test@example.com", password_hash="hash", status=UserStatus.ACTIVE)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute.return_value = mock_result

    from app.services.jwt import AccessTokenPayload
    from datetime import datetime, UTC

    monkeypatch.setattr(
        "app.api.auth_dependencies.decode_access_token",
        lambda token, secret_key: AccessTokenPayload(
            user_id=user_id, jti="test-jti", exp=datetime.now(UTC)
        ),
    )

    result = await get_current_user(
        token="valid-token",
        session=mock_session,
        jwt_secret_key="test-secret",
    )
    assert result.id == user_id


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(monkeypatch):
    from app.services.jwt import JWTError

    monkeypatch.setattr(
        "app.api.auth_dependencies.decode_access_token",
        MagicMock(side_effect=JWTError("Invalid")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            token="bad-token",
            session=AsyncMock(),
            jwt_secret_key="test-secret",
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_blocked_user(monkeypatch):
    user_id = uuid.uuid4()
    user = User(id=user_id, email="blocked@test.com", password_hash="hash", status=UserStatus.BLOCKED)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_session.execute.return_value = mock_result

    from app.services.jwt import AccessTokenPayload
    from datetime import datetime, UTC

    monkeypatch.setattr(
        "app.api.auth_dependencies.decode_access_token",
        lambda token, secret_key: AccessTokenPayload(
            user_id=user_id, jti="test-jti", exp=datetime.now(UTC)
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            token="valid-token",
            session=mock_session,
            jwt_secret_key="test-secret",
        )
    assert exc_info.value.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend pytest tests/unit/test_auth_dependencies.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement auth dependency**

Create `backend/app/api/auth_dependencies.py`:

```python
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import User
from app.db.models.enums import UserStatus
from app.db.session import get_session
from app.services.jwt import JWTError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
    request: Request | None = None,
    *,
    # For testing only — override via direct call
    token: str | None = None,
    jwt_secret_key: str | None = None,
) -> User:
    """FastAPI dependency: extract and validate current user from JWT.

    Uses Depends(get_session) for DB access — same pattern as all other
    dependencies in dependencies.py.
    """
    if token is None:
        if credentials is not None:
            token = credentials.credentials
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if jwt_secret_key is None and request is not None:
        jwt_secret_key = request.app.state.settings.jwt_secret_key.get_secret_value()

    try:
        payload = decode_access_token(token, secret_key=jwt_secret_key)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await session.execute(select(User).where(User.id == payload.user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if user.status == UserStatus.BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is blocked",
        )

    if user.status != UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is not active",
        )

    return user
```

**Key:** Uses `Depends(get_session)` from `app.db.session` — the same session factory used
by all other dependencies in `dependencies.py`. No `request.state.db_session` magic.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend pytest tests/unit/test_auth_dependencies.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/auth_dependencies.py backend/tests/unit/test_auth_dependencies.py
git commit -m "feat(auth): add get_current_user FastAPI dependency with JWT validation"
```

---

## Task 9: Auth Router

**Files:**
- Create: `backend/app/api/auth_router.py`
- Create: `backend/app/api/auth_schemas.py`
- Create: `backend/tests/unit/test_auth_router.py`

- [ ] **Step 1: Create auth schemas**

Create `backend/app/api/auth_schemas.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    message: str


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    status: str
    email_verified_at: datetime | None
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)
```

- [ ] **Step 2: Create auth router**

Create `backend/app/api/auth_router.py`:

```python
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from app.api.auth_dependencies import get_current_user
from app.api.dependencies import get_auth_service
from app.api.auth_schemas import (
    ForgotPasswordRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SignInRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserProfileResponse,
    VerifyEmailRequest,
)
from app.db.models.auth import User
from app.services.auth import (
    AccountBlockedError,
    AccountNotVerifiedError,
    AuthService,
    InvalidCredentialsError,
    InvalidTokenError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str, *, secure: bool) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth",
    )


@router.post("/register", response_model=MessageResponse)
async def register(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    await auth_service.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    return MessageResponse(message="Please check your email to verify your account")


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    try:
        await auth_service.verify_email(token=payload.token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Email verified successfully")


@router.post("/sign-in", response_model=TokenResponse)
async def sign_in(
    payload: SignInRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        access_token, refresh_token_raw = await auth_service.sign_in(
            email=payload.email,
            password=payload.password,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AccountNotVerifiedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountBlockedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    _set_refresh_cookie(response, refresh_token_raw, secure=auth_service.cookie_secure)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    payload: RefreshRequest | None = None,
    refresh_token: str | None = Cookie(default=None),
) -> TokenResponse:
    token = None
    if payload and payload.refresh_token:
        token = payload.refresh_token
    elif refresh_token:
        token = refresh_token

    if not token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    try:
        access_token, new_refresh_raw = await auth_service.refresh(
            refresh_token_raw=token,
        )
    except InvalidTokenError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    _set_refresh_cookie(response, new_refresh_raw, secure=auth_service.cookie_secure)
    return TokenResponse(access_token=access_token)


@router.post("/sign-out", response_model=MessageResponse)
async def sign_out(
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    refresh_token: str | None = Cookie(default=None),
) -> MessageResponse:
    if refresh_token:
        await auth_service.sign_out(refresh_token_raw=refresh_token)
    _clear_refresh_cookie(response)
    return MessageResponse(message="Signed out")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    await auth_service.forgot_password(email=payload.email)
    return MessageResponse(message="If the email exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    try:
        await auth_service.reset_password(
            token=payload.token,
            new_password=payload.new_password,
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Password has been reset")


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    user = await auth_service.get_user_with_profile(user_id=current_user.id)
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.profile.display_name if user.profile else None,
        avatar_url=user.profile.avatar_url if user.profile else None,
        status=user.status.value,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
    )


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    user = await auth_service.update_profile(
        user_id=current_user.id,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
    )
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.profile.display_name if user.profile else None,
        avatar_url=user.profile.avatar_url if user.profile else None,
        status=user.status.value,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
    )
```

**Note:** The auth router uses `Depends(get_auth_service)` from `dependencies.py` — created in
Step 3 below. The `_set_refresh_cookie` helper derives `secure` flag from `settings.cookie_secure`.

- [ ] **Step 3: Add get_auth_service dependency**

In `backend/app/api/dependencies.py`, add a `get_auth_service` function following the same pattern
as `get_chat_service`:

```python
from app.services.auth import AuthService

async def get_auth_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthService:
    settings = request.app.state.settings
    return AuthService(
        session=session,
        email_sender=request.app.state.email_sender,
        jwt_secret_key=settings.jwt_secret_key.get_secret_value(),
        access_token_expire_minutes=settings.jwt_access_token_expire_minutes,
        refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
        frontend_url=settings.frontend_url,
        cookie_secure=settings.cookie_secure,
    )
```

- [ ] **Step 4: Create email sender in lifespan and include router**

In `backend/app/main.py`:

1. Add import: `from app.api.auth_router import router as auth_router`
2. Inside `lifespan`, after existing service creation (around line 200), add:

```python
from app.services.email import build_email_sender

app.state.email_sender = build_email_sender(
    backend=settings.email_backend,
    resend_api_key=settings.resend_api_key,
    email_from=settings.email_from,
)
```

3. After existing `app.include_router(...)` calls, add: `app.include_router(auth_router)`

- [ ] **Step 5: Write basic router tests**

Create `backend/tests/unit/test_auth_router.py` with tests for register, sign-in, and verify-email
endpoints using FastAPI TestClient. Mock the AuthService and verify HTTP status codes and response
shapes.

- [ ] **Step 6: Run tests and verify app starts**

Run: `docker compose exec backend pytest tests/unit/test_auth_router.py -v`
Expected: All PASSED

Run: `docker compose up -d backend && docker compose logs -f backend`
Expected: App starts without errors, new auth endpoints appear in OpenAPI docs at `/docs`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/auth_schemas.py backend/app/api/auth_router.py backend/app/api/dependencies.py backend/app/main.py backend/tests/unit/test_auth_router.py
git commit -m "feat(auth): add auth router, wire into app with dependency injection"
```

---

## Task 11: Protect Chat Endpoints

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat.py`
- Modify: `backend/app/api/chat_schemas.py`
- Create: `backend/tests/unit/test_chat_auth.py`

- [ ] **Step 1: Write failing tests for chat auth**

Create `backend/tests/unit/test_chat_auth.py`:

```python
import pytest
from fastapi.testclient import TestClient


def test_create_session_without_auth_returns_401(client):
    """POST /api/chat/sessions without auth should return 401."""
    response = client.post("/api/chat/sessions")
    assert response.status_code == 401


def test_send_message_without_auth_returns_401(client):
    """POST /api/chat/messages without auth should return 401."""
    response = client.post(
        "/api/chat/messages",
        json={"session_id": "00000000-0000-0000-0000-000000000001", "text": "hello"},
    )
    assert response.status_code == 401


def test_get_session_without_auth_returns_401(client):
    """GET /api/chat/sessions/:id without auth should return 401."""
    response = client.get("/api/chat/sessions/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 401


def test_get_other_users_session_returns_403(client, auth_headers_user_a, session_owned_by_user_b):
    """GET /api/chat/sessions/:id for another user's session should return 403."""
    response = client.get(
        f"/api/chat/sessions/{session_owned_by_user_b}",
        headers=auth_headers_user_a,
    )
    assert response.status_code == 403


def test_send_message_to_other_users_session_returns_403(
    client, auth_headers_user_a, session_owned_by_user_b
):
    """POST /api/chat/messages to another user's session should return 403."""
    response = client.post(
        "/api/chat/messages",
        json={
            "session_id": str(session_owned_by_user_b),
            "text": "hello",
        },
        headers=auth_headers_user_a,
    )
    assert response.status_code == 403
```

**Note:** The `client` fixture needs to be set up with the actual FastAPI app. The `auth_headers_user_a` and `session_owned_by_user_b` fixtures should create two different authenticated users and a session belonging to user B, then verify user A cannot access it. If a test fixture already exists (check `conftest.py`), use it. Otherwise create one.

- [ ] **Step 2: Add auth dependency to chat router**

In `backend/app/api/chat.py`, modify the router to require authentication:

```python
from app.api.auth_dependencies import get_current_user
from app.db.models.auth import User

router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    dependencies=[Depends(get_current_user)],
)
```

- [ ] **Step 3: Pass user to create_session**

In the `create_session` endpoint in `backend/app/api/chat.py`, add user parameter:

```python
@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    payload: CreateSessionRequest | None = Body(default=None),
) -> SessionResponse:
    session = await chat_service.create_session(
        channel=(payload or CreateSessionRequest()).channel,
        user_id=current_user.id,
    )
    return SessionResponse.from_session(session)
```

- [ ] **Step 4: Update ChatService.create_session to accept user_id**

In `backend/app/services/chat.py`, modify `create_session`:

```python
async def create_session(
    self,
    *,
    channel: SessionChannel = SessionChannel.WEB,
    user_id: uuid.UUID | None = None,
) -> Session:
    active_snapshot = await self._snapshot_service.get_active_snapshot(...)
    chat_session = Session(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        snapshot_id=active_snapshot.id if active_snapshot is not None else None,
        status=SessionStatus.ACTIVE,
        message_count=0,
        channel=channel,
        user_id=user_id,
    )
    ...
```

- [ ] **Step 5: Add session ownership check to get_session and send_message**

In `backend/app/api/chat.py`, for `get_session` and `send_message`, add the `current_user` parameter and verify that the session belongs to the user:

For `get_session`:
```python
@router.get("/sessions/{session_id}", response_model=SessionWithMessagesResponse)
async def get_session(
    session_id: uuid.UUID,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SessionWithMessagesResponse:
    try:
        session = await chat_service.get_session(session_id)
    except Exception as error:
        _raise_chat_http_error(error)

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your session")

    return SessionWithMessagesResponse.from_session(session)
```

Apply similar ownership check to `send_message` — load the session by `payload.session_id` and verify `session.user_id == current_user.id`.

- [ ] **Step 6: Run tests**

Run: `docker compose exec backend pytest tests/unit/test_chat_auth.py -v`
Expected: 3 PASSED (401 for unauthenticated requests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/chat.py backend/app/services/chat.py backend/tests/unit/test_chat_auth.py
git commit -m "feat(auth): protect chat endpoints with JWT auth and session ownership"
```

---

## Task 12: Token Cleanup Job

**Files:**
- Create: `backend/app/workers/tasks/cleanup_tokens.py`
- Modify: `backend/app/workers/main.py`

- [ ] **Step 1: Create cleanup task**

Create `backend/app/workers/tasks/cleanup_tokens.py`:

```python
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import UserRefreshToken, UserToken

logger = structlog.get_logger(__name__)


async def cleanup_expired_tokens(session: AsyncSession) -> dict[str, int]:
    """Delete expired tokens from user_tokens and user_refresh_tokens."""
    now = datetime.now(UTC)

    result_tokens = await session.execute(
        delete(UserToken).where(UserToken.expires_at < now)
    )
    result_refresh = await session.execute(
        delete(UserRefreshToken).where(UserRefreshToken.expires_at < now)
    )

    await session.commit()

    deleted_tokens = result_tokens.rowcount
    deleted_refresh = result_refresh.rowcount

    logger.info(
        "auth.cleanup_expired_tokens",
        deleted_user_tokens=deleted_tokens,
        deleted_refresh_tokens=deleted_refresh,
    )

    return {
        "deleted_user_tokens": deleted_tokens,
        "deleted_refresh_tokens": deleted_refresh,
    }
```

- [ ] **Step 2: Register in arq worker**

In `backend/app/workers/main.py`, add `cleanup_expired_tokens` to the cron jobs list. Schedule it every 6 hours:

```python
from arq.cron import cron

cron_jobs = [
    # ... existing cron jobs ...
    cron(cleanup_expired_tokens_job, hour={0, 6, 12, 18}, minute=0),
]
```

The `cleanup_expired_tokens_job` function should create a DB session and call `cleanup_expired_tokens`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/workers/tasks/cleanup_tokens.py backend/app/workers/main.py
git commit -m "feat(auth): add arq cron job for expired token cleanup (every 6h)"
```

---

## Task 13: Frontend Auth API Client

**Files:**
- Create: `frontend/src/lib/auth-api.ts`

- [ ] **Step 1: Create auth API client**

Create `frontend/src/lib/auth-api.ts`:

```typescript
import { buildApiUrl, parseJsonResponse } from "@/lib/api";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserProfile {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  status: string;
  email_verified_at: string | null;
  created_at: string;
}

export interface MessageResponse {
  message: string;
}

export async function register(
  email: string,
  password: string,
  displayName?: string,
): Promise<MessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName || null,
    }),
  });
  return parseJsonResponse<MessageResponse>(response);
}

export async function signIn(
  email: string,
  password: string,
): Promise<TokenResponse> {
  const response = await fetch(buildApiUrl("/api/auth/sign-in"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  return parseJsonResponse<TokenResponse>(response);
}

export async function refreshToken(): Promise<TokenResponse> {
  const response = await fetch(buildApiUrl("/api/auth/refresh"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({}),
  });
  return parseJsonResponse<TokenResponse>(response);
}

export async function signOut(): Promise<void> {
  await fetch(buildApiUrl("/api/auth/sign-out"), {
    method: "POST",
    credentials: "include",
  });
}

export async function forgotPassword(
  email: string,
): Promise<MessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/forgot-password"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return parseJsonResponse<MessageResponse>(response);
}

export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<MessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/reset-password"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  return parseJsonResponse<MessageResponse>(response);
}

export async function verifyEmail(
  token: string,
): Promise<MessageResponse> {
  const response = await fetch(buildApiUrl("/api/auth/verify-email"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return parseJsonResponse<MessageResponse>(response);
}

export async function getMe(
  accessToken: string,
): Promise<UserProfile> {
  const response = await fetch(buildApiUrl("/api/auth/me"), {
    method: "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: "application/json",
    },
  });
  return parseJsonResponse<UserProfile>(response);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/auth-api.ts
git commit -m "feat(auth): add frontend auth API client"
```

---

## Task 14: Frontend AuthContext

**Files:**
- Create: `frontend/src/contexts/AuthContext.tsx`

- [ ] **Step 1: Create AuthProvider and useUserAuth hook**

Create `frontend/src/contexts/AuthContext.tsx`:

```tsx
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { UserProfile } from "@/lib/auth-api";
import {
  getMe,
  refreshToken as refreshTokenApi,
  signIn as signInApi,
  signOut as signOutApi,
} from "@/lib/auth-api";

interface AuthContextValue {
  user: UserProfile | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshPromiseRef = useRef<Promise<string | null> | null>(null);

  const doRefresh = useCallback(async (): Promise<string | null> => {
    try {
      const response = await refreshTokenApi();
      setAccessToken(response.access_token);
      const profile = await getMe(response.access_token);
      setUser(profile);
      return response.access_token;
    } catch {
      setAccessToken(null);
      setUser(null);
      return null;
    }
  }, []);

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    if (accessToken) return accessToken;

    // Deduplicate concurrent refresh calls
    if (!refreshPromiseRef.current) {
      refreshPromiseRef.current = doRefresh().finally(() => {
        refreshPromiseRef.current = null;
      });
    }
    return refreshPromiseRef.current;
  }, [accessToken, doRefresh]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const response = await signInApi(email, password);
      setAccessToken(response.access_token);
      const profile = await getMe(response.access_token);
      setUser(profile);
    },
    [],
  );

  const signOut = useCallback(async () => {
    await signOutApi();
    setAccessToken(null);
    setUser(null);
  }, []);

  // Silent refresh on mount
  useEffect(() => {
    doRefresh().finally(() => setIsLoading(false));
  }, [doRefresh]);

  const value = useMemo(
    () => ({
      user,
      accessToken,
      isAuthenticated: user !== null && accessToken !== null,
      isLoading,
      signIn,
      signOut,
      getAccessToken,
    }),
    [user, accessToken, isLoading, signIn, signOut, getAccessToken],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useUserAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useUserAuth must be used within AuthProvider");
  }
  return context;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/contexts/AuthContext.tsx
git commit -m "feat(auth): add AuthProvider with silent refresh and token management"
```

---

## Task 15: Frontend Auth Pages

**Files:**
- Create: `frontend/src/pages/AuthPage/AuthPage.tsx`
- Create: `frontend/src/pages/AuthPage/SignInPage.tsx`
- Create: `frontend/src/pages/AuthPage/RegisterPage.tsx`
- Create: `frontend/src/pages/AuthPage/ForgotPasswordPage.tsx`
- Create: `frontend/src/pages/AuthPage/ResetPasswordPage.tsx`
- Create: `frontend/src/pages/AuthPage/VerifyEmailPage.tsx`
- Create: `frontend/src/pages/AuthPage/index.ts`

- [ ] **Step 1: Create AuthLayout**

Create `frontend/src/pages/AuthPage/AuthPage.tsx`:

```tsx
import { Outlet } from "react-router";

import { appConfig } from "@/lib/config";

export function AuthPage() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: "2rem",
      }}
    >
      <div style={{ marginBottom: "2rem", textAlign: "center" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>
          {appConfig.twinName || "ProxyMind"}
        </h1>
      </div>
      <div style={{ width: "100%", maxWidth: "400px" }}>
        <Outlet />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create SignInPage**

Create `frontend/src/pages/AuthPage/SignInPage.tsx`:

```tsx
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useUserAuth } from "@/contexts/AuthContext";

export function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { signIn } = useUserAuth();
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await signIn(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={{ marginBottom: "1rem" }}>Sign In</h2>
      {error && (
        <p style={{ color: "var(--color-error, red)", marginBottom: "1rem" }}>
          {error}
        </p>
      )}
      <div style={{ marginBottom: "1rem" }}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          style={{ width: "100%", padding: "0.5rem", marginTop: "0.25rem" }}
        />
      </div>
      <div style={{ marginBottom: "1rem" }}>
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          style={{ width: "100%", padding: "0.5rem", marginTop: "0.25rem" }}
        />
      </div>
      <button
        type="submit"
        disabled={loading}
        style={{ width: "100%", padding: "0.75rem", cursor: "pointer" }}
      >
        {loading ? "Signing in..." : "Sign In"}
      </button>
      <div style={{ marginTop: "1rem", textAlign: "center" }}>
        <Link to="/auth/register">Create account</Link>
        {" | "}
        <Link to="/auth/forgot-password">Forgot password?</Link>
      </div>
    </form>
  );
}
```

- [ ] **Step 3: Create RegisterPage, ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage**

Follow the same pattern as SignInPage for each:

**RegisterPage:** Form with email, password, confirm password, display_name (optional). On submit calls `register()` from auth-api. Shows "Check your email" message on success.

**ForgotPasswordPage:** Form with email. On submit calls `forgotPassword()`. Shows "If the email exists, a link has been sent".

**ResetPasswordPage:** Reads `token` from `useSearchParams()`. Form with new password + confirm. Calls `resetPassword(token, password)`. On success navigates to `/auth/sign-in`.

**VerifyEmailPage:** Reads `token` from `useSearchParams()`. Auto-calls `verifyEmail(token)` on mount. Shows success/error message. Link to `/auth/sign-in`.

- [ ] **Step 4: Create barrel export**

Create `frontend/src/pages/AuthPage/index.ts`:

```typescript
export { AuthPage } from "./AuthPage";
export { ForgotPasswordPage } from "./ForgotPasswordPage";
export { RegisterPage } from "./RegisterPage";
export { ResetPasswordPage } from "./ResetPasswordPage";
export { SignInPage } from "./SignInPage";
export { VerifyEmailPage } from "./VerifyEmailPage";
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AuthPage/
git commit -m "feat(auth): add frontend auth pages (sign-in, register, forgot/reset password, verify email)"
```

---

## Task 16: Frontend ProtectedRoute, Admin Sign-In Page, and Routing

**Files:**
- Create: `frontend/src/components/ProtectedRoute/ProtectedRoute.tsx`
- Create: `frontend/src/components/ProtectedRoute/index.ts`
- Create: `frontend/src/pages/AdminPage/AdminSignInPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Create ProtectedRoute component**

Create `frontend/src/components/ProtectedRoute/ProtectedRoute.tsx`:

```tsx
import { Navigate, Outlet } from "react-router";

import { useUserAuth } from "@/contexts/AuthContext";

export function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useUserAuth();

  if (isLoading) {
    return <div style={{ padding: "2rem", textAlign: "center" }}>Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate replace to="/auth/sign-in" />;
  }

  return <Outlet />;
}
```

Create `frontend/src/components/ProtectedRoute/index.ts`:

```typescript
export { ProtectedRoute } from "./ProtectedRoute";
```

- [ ] **Step 2: Create AdminSignInPage**

Create `frontend/src/pages/AdminPage/AdminSignInPage.tsx`:

```tsx
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";

import { useAuth } from "@/hooks/useAuth";

export function AdminSignInPage() {
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const { login } = useAuth();
  const navigate = useNavigate();

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) {
      setError("API key is required");
      return;
    }
    login(apiKey.trim());
    navigate("/admin/sources");
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: "2rem",
      }}
    >
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600, marginBottom: "2rem" }}>
        Admin Access
      </h1>
      <form onSubmit={handleSubmit} style={{ width: "100%", maxWidth: "400px" }}>
        {error && (
          <p style={{ color: "var(--color-error, red)", marginBottom: "1rem" }}>
            {error}
          </p>
        )}
        <div style={{ marginBottom: "1rem" }}>
          <label htmlFor="api-key">Admin API Key</label>
          <input
            id="api-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            required
            style={{ width: "100%", padding: "0.5rem", marginTop: "0.25rem" }}
          />
        </div>
        <button
          type="submit"
          style={{ width: "100%", padding: "0.75rem", cursor: "pointer" }}
        >
          Sign In
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Update App.tsx with auth routes and route-based admin auth**

Replace the entire `frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/hooks/useAuth";
import { appConfig } from "@/lib/config";
import {
  AdminPage,
  AdminSignInPage,
  CatalogTab,
  SnapshotsTab,
  SourcesTab,
} from "@/pages/AdminPage";
import {
  AuthPage,
  ForgotPasswordPage,
  RegisterPage,
  ResetPasswordPage,
  SignInPage,
  VerifyEmailPage,
} from "@/pages/AuthPage";
import { ChatPage } from "@/pages/ChatPage";

function AdminRouteGuard() {
  const { isAuthenticated } = useAuth();

  if (!appConfig.adminMode) {
    return <Navigate replace to="/" />;
  }

  if (!isAuthenticated) {
    return <Navigate replace to="/admin/sign-in" />;
  }

  return <Outlet />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* User auth pages — public */}
        <Route element={<AuthPage />} path="/auth">
          <Route element={<SignInPage />} path="sign-in" />
          <Route element={<RegisterPage />} path="register" />
          <Route element={<ForgotPasswordPage />} path="forgot-password" />
          <Route element={<ResetPasswordPage />} path="reset-password" />
          <Route element={<VerifyEmailPage />} path="verify-email" />
        </Route>

        {/* Chat — protected by user auth */}
        <Route element={<ProtectedRoute />}>
          <Route element={<ChatPage />} path="/" />
        </Route>

        {/* Admin sign-in — dedicated page, separate from user auth */}
        <Route element={<AdminSignInPage />} path="/admin/sign-in" />

        {/* Admin — protected by admin API key */}
        <Route element={<AdminRouteGuard />} path="/admin">
          <Route element={<AdminPage />}>
            <Route element={<Navigate replace to="sources" />} index />
            <Route element={<SourcesTab />} path="sources" />
            <Route element={<SnapshotsTab />} path="snapshots" />
            <Route element={<CatalogTab />} path="catalog" />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
```

- [ ] **Step 3: Wrap routes in AuthProvider**

Add `AuthProvider` inside `App.tsx` itself (NOT in `main.tsx`) — this way integration tests
that render `<App />` get auth context automatically:

```tsx
// In App.tsx, wrap BrowserRouter contents:
import { AuthProvider } from "@/contexts/AuthContext";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* ... all routes ... */}
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
```

No changes needed in `main.tsx`.

- [ ] **Step 4: Verify the app compiles**

Run: `cd frontend && bun run build`
Expected: Build succeeds without type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProtectedRoute/ frontend/src/App.tsx frontend/src/main.tsx
git commit -m "feat(auth): add ProtectedRoute, auth routing, and AuthProvider wrapper"
```

---

## Task 17: Frontend API Auth Headers

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/transport.ts`

- [ ] **Step 1: Add auth header to chat API calls**

In `frontend/src/lib/api.ts`, modify `createSession()` and `getSession()` to accept an `accessToken` parameter and include `Authorization: Bearer` header:

```typescript
export async function createSession(accessToken: string): Promise<SessionResponse> {
  const response = await fetch(buildApiUrl("/api/chat/sessions"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ channel: "web" }),
  });
  return parseJsonResponse<SessionResponse>(response);
}

export async function getSession(
  sessionId: string,
  accessToken: string,
): Promise<SessionWithMessagesResponse> {
  const response = await fetch(
    buildApiUrl(`/api/chat/sessions/${encodeURIComponent(sessionId)}`),
    {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
    },
  );
  return parseJsonResponse<SessionWithMessagesResponse>(response);
}
```

- [ ] **Step 2: Add auth to SSE transport**

In `frontend/src/lib/transport.ts`, the `ProxyMindTransport` constructs a fetch request for SSE streaming. Modify it to include the access token. Since SSE via `EventSource` doesn't support custom headers, and the transport uses `fetch()` directly, add the `Authorization` header to the fetch call.

Find the `fetch()` call in `sendMessages()` and add:

```typescript
headers: {
  "Content-Type": "application/json",
  Authorization: `Bearer ${this._accessToken}`,
},
```

Add `accessToken` to `ProxyMindTransportOptions` and store it in the constructor.

- [ ] **Step 3: Update all callers**

Update `ChatPage`, `useSession` hook, and wherever `createSession`, `getSession`, or `ProxyMindTransport` are called to pass the access token from `useUserAuth().getAccessToken()`.

- [ ] **Step 4: Verify the app compiles**

Run: `cd frontend && bun run build`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/transport.ts frontend/src/pages/ChatPage/ frontend/src/hooks/
git commit -m "feat(auth): add JWT auth headers to chat API and SSE transport"
```

---

## Task 18: Update MSW Mocks

**Files:**
- Modify: `frontend/src/mocks/handlers/session.ts`
- Create: `frontend/src/mocks/handlers/auth.ts`
- Modify: `frontend/src/mocks/handlers/index.ts`

- [ ] **Step 1: Create auth mock handlers**

Create `frontend/src/mocks/handlers/auth.ts` with MSW handlers for:
- `POST /api/auth/register` → 200 with message
- `POST /api/auth/sign-in` → 200 with `{ access_token: "mock-jwt-token", token_type: "bearer" }`
- `POST /api/auth/refresh` → 200 with `{ access_token: "mock-jwt-token", token_type: "bearer" }`
- `POST /api/auth/sign-out` → 200
- `GET /api/auth/me` → 200 with mock user profile

- [ ] **Step 2: Export in handlers index**

In `frontend/src/mocks/handlers/index.ts`, import and spread the auth handlers.

- [ ] **Step 3: Verify mock mode works**

Run: `cd frontend && VITE_MOCK_MODE=true bun run dev`
Expected: App loads, auth pages work with mocked responses.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/mocks/handlers/auth.ts frontend/src/mocks/handlers/index.ts
git commit -m "feat(auth): add MSW mock handlers for auth endpoints"
```

---

## Task 19: Backend Integration Tests

**Files:**
- Create: `backend/tests/unit/test_auth_integration.py`

- [ ] **Step 1: Write end-to-end auth flow test**

Create `backend/tests/unit/test_auth_integration.py` testing the full flow:

1. Register → check user created with PENDING status
2. Verify email → check user status changed to ACTIVE
3. Sign in → check access token + refresh cookie returned
4. Refresh → check new tokens returned
5. Access protected endpoint with token → 200
6. Access protected endpoint without token → 401
7. Sign out → refresh token deleted
8. Forgot password → token created
9. Reset password → password changed, can sign in with new password

These tests should use the FastAPI TestClient or `httpx.AsyncClient` against the actual app, with a test database.

- [ ] **Step 2: Run all tests**

Run: `docker compose exec backend pytest -v`
Expected: All tests pass, including new auth tests and existing tests.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_auth_integration.py
git commit -m "test(auth): add end-to-end auth flow integration tests"
```

---

## Task 20: Add Dependencies to pyproject.toml

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add new packages**

Add to `[project.dependencies]` in `backend/pyproject.toml`:

```
"PyJWT>=2.10.0",
"argon2-cffi>=24.1.0",
"resend>=2.7.0",
"pydantic[email]>=2.12.5",
```

Note: `pydantic[email]` adds `email-validator` for `EmailStr` support in auth schemas.

- [ ] **Step 2: Rebuild container**

Run: `docker compose build backend`
Expected: Build succeeds with new dependencies.

- [ ] **Step 3: Verify all tests pass**

Run: `docker compose exec backend pytest -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore(auth): add PyJWT, argon2-cffi, resend, pydantic[email] dependencies"
```

**Important sequencing note:** This task should be executed FIRST in practice (before Task 1), because all other tasks depend on these packages being available. The plan lists it last for logical grouping, but the implementor should install dependencies before running any tests.

---

## Task 21: Update .env Files and Documentation

**Files:**
- Modify: `backend/.env.example`
- Modify: `.env.example`
- Modify: `frontend/.env.example`

- [ ] **Step 1: Update backend .env.example**

Add the auth configuration section as described in Task 4 Step 2.

- [ ] **Step 2: Update docker-compose.yml if needed**

Ensure `JWT_SECRET_KEY` is passed to the backend container environment. Add to `.env` for development.

- [ ] **Step 3: Commit**

```bash
git add backend/.env.example .env.example docker-compose.yml
git commit -m "chore(auth): update env examples with auth configuration"
```

---

## Task 22: Protect Twin Profile Endpoints

**Files:**
- Modify: `backend/app/api/profile.py`
- Modify: `backend/tests/unit/test_profile_api.py`

- [ ] **Step 1: Add auth dependency to twin chat endpoints**

In `backend/app/api/profile.py`, the `chat_router` is defined at line 25 without auth. Add the
`get_current_user` dependency at the router level:

```python
from app.api.auth_dependencies import get_current_user

chat_router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    dependencies=[Depends(get_current_user)],
)
```

This protects both `GET /api/chat/twin` and `GET /api/chat/twin/avatar`.

- [ ] **Step 2: Update twin profile tests**

In `backend/tests/unit/test_profile_api.py`, existing tests for `GET /api/chat/twin` and
`GET /api/chat/twin/avatar` assert 200 for public access. These must be updated:
- Tests without auth headers → expect 401
- Add new tests with valid auth headers → expect 200 (existing behavior)

The test file already has helper functions for making requests. Add auth headers
to the authenticated test cases (same pattern as admin auth tests in the file).

- [ ] **Step 3: Run tests**

Run: `docker compose exec backend pytest tests/unit/test_profile_api.py -v`
Expected: All tests pass — unauthenticated → 401, authenticated → 200.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/profile.py backend/tests/unit/test_profile_api.py
git commit -m "feat(auth): protect twin profile chat endpoints with auth dependency"
```

---

## Task 23: Extend Rate Limiting to Auth Brute-Force Targets

**Files:**
- Modify: `backend/app/middleware/rate_limit.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add auth rate limit settings**

In `backend/app/core/config.py`, add after the existing `chat_rate_window_seconds` field:

```python
    auth_sensitive_rate_limit: int = Field(default=10, ge=1)
    auth_sensitive_rate_window_seconds: int = Field(default=60, ge=1)
```

- [ ] **Step 2: Extend rate limiter with path-specific limits**

In `backend/app/middleware/rate_limit.py`, modify the middleware to apply strict limits only to
brute-force targets (`/api/auth/sign-in`, `/api/auth/forgot-password`, `/api/auth/register`),
while leaving `/api/auth/refresh` and other auth endpoints unthrottled (refresh is called on every
page load during silent refresh — throttling it would break UX):

```python
_CHAT_PREFIX = "/api/chat"
_AUTH_SENSITIVE_PATHS = frozenset({
    "/api/auth/sign-in",
    "/api/auth/forgot-password",
    "/api/auth/register",
    "/api/auth/reset-password",
})


class RateLimitMiddleware:
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path.startswith(_CHAT_PREFIX):
            limit = settings.chat_rate_limit
            window = settings.chat_rate_window_seconds
            key_prefix = "ratelimit"
        elif path in _AUTH_SENSITIVE_PATHS:
            limit = settings.auth_sensitive_rate_limit
            window = settings.auth_sensitive_rate_window_seconds
            key_prefix = "ratelimit:auth"
        else:
            await self.app(scope, receive, send)
            return

        # Use key_prefix to separate auth and chat counters in Redis
        # Rest of rate limit logic unchanged, just use key_prefix in Redis key
```

**Why not all of `/api/auth/*`:** Silent refresh (`POST /api/auth/refresh`) fires on every page
load/reload. A 10 req/min blanket limit would throttle legitimate users. Only sign-in,
register, forgot-password, and reset-password are brute-force targets.

- [ ] **Step 3: Run tests**

Run: `docker compose exec backend pytest tests/ -v -k "rate_limit"`
Expected: Existing rate limit tests pass, sensitive auth paths now rate-limited.

- [ ] **Step 4: Commit**

```bash
git add backend/app/middleware/rate_limit.py backend/app/core/config.py
git commit -m "feat(auth): rate-limit auth brute-force targets (sign-in, register, forgot-password)"
```

---

## ~~Task 24~~ (Merged into Task 16)

---

## Task 25: User-Scoped Session Persistence

**Files:**
- Modify: `frontend/src/hooks/useSession.ts`
- Modify: `frontend/src/contexts/AuthContext.tsx`

- [ ] **Step 1: Handle 403 in useSession**

In `frontend/src/hooks/useSession.ts`, modify `restoreOrCreateSession` to handle 403 the same as 404:

```typescript
} catch (error) {
  if (error instanceof ApiError && (error.status === 404 || error.status === 403)) {
    await createAndStoreSession();
    return;
  }
  throw error;
}
```

- [ ] **Step 2: Clear session on logout**

In `frontend/src/contexts/AuthContext.tsx`, modify the `signOut` callback to clear the stored
session ID:

```typescript
const signOut = useCallback(async () => {
  await signOutApi();
  setAccessToken(null);
  setUser(null);
  // Clear stored chat session so the next user starts fresh
  try {
    localStorage.removeItem("proxymind_session_id");
  } catch {
    // Ignore storage failures
  }
}, []);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useSession.ts frontend/src/contexts/AuthContext.tsx
git commit -m "feat(auth): user-scoped session persistence — clear on logout, handle 403"
```

---

## ~~Task 26~~ (Merged into Task 9 — cookie secure flag is part of auth router code)

---

## Task 27: Update Existing Frontend Tests

**Files:**
- Modify: `frontend/src/tests/integration/ChatPage.test.tsx`
- Modify: `frontend/src/tests/integration/AdminPage.test.tsx`
- Modify: `frontend/src/tests/lib/api.test.ts`
- Modify: `frontend/src/tests/lib/transport.test.ts`

**Important context:** Existing frontend tests use `vi.stubGlobal("fetch", fetchMock)` — they
stub `fetch` directly, NOT MSW. The AuthProvider's silent refresh also calls `fetch`. This means:
- Tests that render components with `AuthProvider` need the fetch mock to handle
  `POST /api/auth/refresh` and `GET /api/auth/me` in addition to their own endpoints
- Tests for `api.ts` and `transport.ts` are pure unit tests — they just need updated function
  signatures (add `accessToken` parameter)

- [ ] **Step 1: Update api.test.ts**

In `frontend/src/tests/lib/api.test.ts`, update calls to `createSession()` and `getSession()`
to pass the `accessToken` parameter:

```typescript
it("creates a session", async () => {
  fetchMock.mockResolvedValueOnce(jsonResponse({ /* ... */ }));
  const result = await createSession("mock-access-token");
  // Verify Authorization header was passed:
  expect(fetchMock).toHaveBeenCalledWith(
    expect.any(String),
    expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: "Bearer mock-access-token",
      }),
    }),
  );
  // ... rest of assertions
});
```

Same for `getSession()` — add the `accessToken` argument.

- [ ] **Step 2: Update transport.test.ts**

In `frontend/src/tests/lib/transport.test.ts`, update `ProxyMindTransport` construction to include
`accessToken` in options. Verify the fetch call includes the `Authorization` header.

- [ ] **Step 3: Update ChatPage integration test**

In `frontend/src/tests/integration/ChatPage.test.tsx`, the test renders `<App />` which now
includes `AuthProvider` (since we put it in App.tsx per Task 16). The existing tests use
`fetchMock.mockImplementation` with URL-based routing — add auth URL handlers to the same
`mockImplementation` callback:

```typescript
fetchMock.mockImplementation(async (input, init) => {
  const url = getRequestUrl(input);

  // Auth: silent refresh on mount
  if (url === buildApiUrl("/api/auth/refresh") && init?.method === "POST") {
    return jsonResponse({ access_token: "mock-jwt-token", token_type: "bearer" });
  }

  // Auth: get user profile after refresh
  if (url === buildApiUrl("/api/auth/me") && init?.method === "GET") {
    return jsonResponse({
      id: "user-1",
      email: "test@example.com",
      display_name: "Test User",
      avatar_url: null,
      status: "active",
      email_verified_at: "2026-01-01T00:00:00Z",
      created_at: "2026-01-01T00:00:00Z",
    });
  }

  // ... existing URL handlers for /api/chat/twin, /api/chat/sessions, etc.
});
```

Since `AuthProvider` lives in `App.tsx`, all integration tests that `render(<App />)` get auth
context automatically — no wrapper needed.

- [ ] **Step 4: Update AdminPage integration test**

In `frontend/src/tests/integration/AdminPage.test.tsx`, apply the same pattern — add
`/api/auth/refresh` and `/api/auth/me` handlers to the existing `fetchMock.mockImplementation`
callback. The admin tests set `appConfig.adminMode = true` directly (not via env) — this
doesn't change.

Note: `/api/chat/twin` is now auth-protected. The admin tests that call it must have the auth
mock handlers in place (from above) so the `AuthProvider` resolves before the admin page renders.

- [ ] **Step 5: Run all frontend tests**

Run: `cd frontend && bun run test`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/tests/
git commit -m "test(auth): update existing frontend tests for auth-protected endpoints"
```

---

## Task 28: Sync OpenSpec Canonical Specs

**Files:**
- Modify: `openspec/specs/chat-dialogue/spec.md`
- Modify: `openspec/specs/twin-profile/spec.md`
- Modify: `openspec/specs/chat-rate-limiting/spec.md`

The canonical OpenSpec specs for chat, twin-profile, and rate-limiting were written before S7-03
and describe endpoints as public ("No authentication SHALL be required"). After S7-03, these specs
conflict with the new auth requirements. This task adds MODIFIED requirements to bring them in sync.

- [ ] **Step 1: Update chat-dialogue spec**

In `openspec/specs/chat-dialogue/spec.md`, add a MODIFIED requirement section:

```markdown
## MODIFIED Requirements (S7-03)

### Requirement: Authentication required for all chat endpoints

All chat endpoints (`POST /api/chat/sessions`, `POST /api/chat/messages`,
`GET /api/chat/sessions/{id}`) SHALL require a valid JWT access token in the
`Authorization: Bearer` header. Unauthenticated requests SHALL receive 401 Unauthorized.

Session creation SHALL set `user_id` to the authenticated user's ID.
Session read and message send SHALL verify that `session.user_id` matches the
authenticated user, returning 403 Forbidden otherwise.
```

- [ ] **Step 2: Update twin-profile spec**

In `openspec/specs/twin-profile/spec.md`, add a MODIFIED requirement section:

```markdown
## MODIFIED Requirements (S7-03)

### Requirement: Twin profile endpoints require authentication

`GET /api/chat/twin` and `GET /api/chat/twin/avatar` SHALL require a valid JWT access token.
The twin name for unauthenticated UI (auth pages) is provided via the `VITE_TWIN_NAME`
environment variable, not via the API.
```

- [ ] **Step 3: Update chat-rate-limiting spec**

In `openspec/specs/chat-rate-limiting/spec.md`, add a MODIFIED requirement section:

```markdown
## MODIFIED Requirements (S7-03)

### Requirement: Rate limiting for auth brute-force targets

In addition to `/api/chat/*`, the rate limiter SHALL apply stricter limits to
`/api/auth/sign-in`, `/api/auth/register`, `/api/auth/forgot-password`, and
`/api/auth/reset-password` (default: 10 requests/minute per IP).
`/api/auth/refresh` SHALL NOT be rate-limited (called on every page load).
```

- [ ] **Step 4: Commit**

```bash
git add openspec/specs/chat-dialogue/spec.md openspec/specs/twin-profile/spec.md openspec/specs/chat-rate-limiting/spec.md
git commit -m "docs(auth): sync OpenSpec canonical specs with S7-03 auth requirements"
```

---

## Execution Order

**Critical dependency: Task 20 (dependencies) must run before all others.**

Recommended execution sequence:

1. **Task 20** — Install dependencies (PyJWT, argon2-cffi, resend, pydantic[email])
2. **Task 4** — Config settings (including cookie_secure computed property)
3. **Task 1** — Enums + password utility
4. **Task 2** — JWT utility
5. **Task 3** — Email service
6. **Task 5** — DB models
7. **Task 6** — Alembic migration
8. **Task 7** — Auth service
9. **Task 8** — Auth dependency (get_current_user)
10. **Task 9** — Auth router + wire into app (includes dependency injection, cookie secure flag)
11. **Task 11** — Protect chat endpoints
12. **Task 22** — Protect twin profile endpoints
13. **Task 23** — Rate-limit auth brute-force targets
14. **Task 12** — Token cleanup job
15. **Task 13** — Frontend auth API client
16. **Task 14** — Frontend AuthContext
17. **Task 15** — Frontend auth pages
18. **Task 16** — Frontend routing + ProtectedRoute + admin sign-in page
19. **Task 17** — Frontend API auth headers
20. **Task 25** — User-scoped session persistence
21. **Task 18** — MSW mocks
22. **Task 27** — Update existing frontend tests (fetch-stub pattern)
23. **Task 19** — Integration tests
24. **Task 28** — Sync OpenSpec canonical specs
25. **Task 21** — Env files + docs
