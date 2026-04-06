from __future__ import annotations

import ipaddress
import secrets
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models.enums import UserStatus
from app.db.session import get_session
from app.services.jwt_tokens import InvalidAccessTokenError, decode_access_token

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_admin_key(value: str | SecretStr | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


async def verify_admin_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    configured_key = _extract_admin_key(request.app.state.settings.admin_api_key)

    if not configured_key:
        logger.warning(
            "admin.auth.key_not_configured",
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), configured_key.encode()
    ):
        logger.warning(
            "admin.auth.failed",
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _is_private_client(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


async def verify_metrics_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    configured_key = _extract_admin_key(request.app.state.settings.admin_api_key)
    client_ip = request.client.host if request.client else None

    if configured_key:
        if credentials is not None and secrets.compare_digest(
            credentials.credentials.encode(),
            configured_key.encode(),
        ):
            return
        logger.warning(
            "metrics.auth.failed",
            path=request.url.path,
            client_ip=client_ip or "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _is_private_client(client_ip):
        return

    logger.warning(
        "metrics.access.denied",
        path=request.url.path,
        client_ip=client_ip or "unknown",
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Metrics endpoint is restricted to private network clients",
    )


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(
            credentials.credentials,
            secret_key=request.app.state.settings.jwt_secret_key.get_secret_value(),
        )
    except InvalidAccessTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    user = await session.get(User, payload.user_id)
    if user is None or user.status is UserStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status is UserStatus.BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is blocked",
        )
    return user
