from __future__ import annotations

import ipaddress
import secrets

import structlog
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

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

    if configured_key and credentials is not None and secrets.compare_digest(
        credentials.credentials.encode(),
        configured_key.encode(),
    ):
        return

    if _is_private_client(client_ip):
        return

    if configured_key:
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

    logger.warning(
        "metrics.access.denied",
        path=request.url.path,
        client_ip=client_ip or "unknown",
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Metrics endpoint is restricted to private network clients",
    )
