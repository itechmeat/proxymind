from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt


class InvalidAccessTokenError(RuntimeError):
    """Raised when the supplied access token cannot be decoded or validated."""


@dataclass(slots=True, frozen=True)
class AccessTokenPayload:
    user_id: uuid.UUID
    exp: datetime
    iat: datetime
    jti: str


def create_access_token(
    *,
    user_id: uuid.UUID,
    secret_key: str,
    expires_minutes: int,
) -> str:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=expires_minutes)
    payload = {
        "sub": str(user_id),
        "exp": int(expires_at.timestamp()),
        "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(
    token: str,
    *,
    secret_key: str,
) -> AccessTokenPayload:
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise InvalidAccessTokenError("Invalid or expired access token") from error

    subject = payload.get("sub")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    jti = payload.get("jti")
    if not isinstance(subject, str) or not isinstance(jti, str):
        raise InvalidAccessTokenError("Access token payload is invalid")
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise InvalidAccessTokenError("Access token timestamps are invalid")

    try:
        user_id = uuid.UUID(subject)
    except ValueError as error:
        raise InvalidAccessTokenError("Access token subject is invalid") from error

    return AccessTokenPayload(
        user_id=user_id,
        iat=datetime.fromtimestamp(issued_at, UTC),
        exp=datetime.fromtimestamp(expires_at, UTC),
        jti=jti,
    )
