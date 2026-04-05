from __future__ import annotations

import time

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    from app.services.metrics import RATE_LIMIT_HITS_TOTAL
except ImportError:
    RATE_LIMIT_HITS_TOTAL = None

logger = structlog.get_logger(__name__)

_CHAT_PREFIX = "/api/chat"
_AUTH_SENSITIVE_PATHS = frozenset(
    {
        "/api/auth/sign-in",
        "/api/auth/register",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
    }
)


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        settings = request.app.state.settings
        rate_limit_config = _resolve_rate_limit_config(scope["path"], settings)
        if rate_limit_config is None:
            await self.app(scope, receive, send)
            return

        rate_limit_key, limit, window = rate_limit_config
        proxy_depth: int = settings.trusted_proxy_depth

        client_ip = _extract_client_ip(scope, proxy_depth)
        now = time.time()

        try:
            current_count, previous_count, window_start = await _get_counters(
                request,
                client_ip,
                now,
                window,
                rate_limit_key,
            )
        except Exception:
            logger.warning("rate_limit.redis_unavailable", client_ip=client_ip)
            await self.app(scope, receive, send)
            return

        elapsed_fraction = (now - window_start) / window
        weighted_count = previous_count * (1.0 - elapsed_fraction) + current_count
        remaining = max(0, int(limit - weighted_count))
        reset_at = int(window_start + window)

        if weighted_count > limit:
            retry_after = max(1, reset_at - int(now))
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                },
            )
            logger.warning(
                "rate_limit.exceeded",
                client_ip=client_ip,
                path=scope["path"],
                rate_limit_key=rate_limit_key,
                weighted_count=round(weighted_count, 1),
                limit=limit,
            )
            if RATE_LIMIT_HITS_TOTAL is not None:
                RATE_LIMIT_HITS_TOTAL.inc()
            await response(scope, receive, send)
            return

        rl_headers = {
            b"x-ratelimit-limit": str(limit).encode(),
            b"x-ratelimit-remaining": str(remaining).encode(),
            b"x-ratelimit-reset": str(reset_at).encode(),
        }

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(rl_headers.items())
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _extract_client_ip(scope: Scope, proxy_depth: int) -> str:
    xff_value: str | None = None
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            xff_value = value.decode("latin-1")
            break

    if xff_value:
        parts = [part.strip() for part in xff_value.split(",")]
        index = len(parts) - proxy_depth - 1
        if index >= 0:
            return parts[index]
        logger.warning(
            "rate_limit.xff_depth_mismatch",
            proxy_depth=proxy_depth,
            xff_entries=len(parts),
            fallback_ip=parts[0],
        )
        return parts[0]

    client = scope.get("client")
    if client is None:
        return "unknown"
    return client[0]


async def _get_counters(
    request: Request,
    client_ip: str,
    now: float,
    window: int,
    rate_limit_key: str,
) -> tuple[int, int, float]:
    redis = request.app.state.redis_client
    window_start = (int(now) // window) * window
    previous_window_start = window_start - window

    current_key = f"ratelimit:{rate_limit_key}:{client_ip}:{window_start}"
    previous_key = f"ratelimit:{rate_limit_key}:{client_ip}:{previous_window_start}"

    pipe = redis.pipeline(transaction=False)
    pipe.get(previous_key)
    pipe.incr(current_key)
    pipe.expire(current_key, window * 2)
    results = await pipe.execute()

    previous_count = int(results[0] or 0)
    current_count = int(results[1])
    return current_count, previous_count, float(window_start)


def _resolve_rate_limit_config(path: str, settings: object) -> tuple[str, int, int] | None:
    if path.startswith(_CHAT_PREFIX):
        return ("chat", settings.chat_rate_limit, settings.chat_rate_window_seconds)
    if path in _AUTH_SENSITIVE_PATHS:
        return (
            path.removeprefix("/api/").replace("/", ":"),
            settings.auth_sensitive_rate_limit,
            settings.auth_sensitive_rate_window_seconds,
        )
    return None
