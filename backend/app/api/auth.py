from __future__ import annotations

import secrets

import structlog
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_admin_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    configured_key: str | None = request.app.state.settings.admin_api_key

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
