# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /app

ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-bookworm AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini entrypoint.sh ./
COPY app ./app
COPY migrations ./migrations

RUN chmod +x /app/entrypoint.sh \
	&& groupadd --system appuser \
	&& useradd --system --gid appuser --create-home --home-dir /home/appuser appuser \
	&& chown -R appuser:appuser /app

ENV PATH="/app/.venv/bin:${PATH}"
ENV VIRTUAL_ENV="/app/.venv"

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
