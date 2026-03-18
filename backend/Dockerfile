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

COPY --from=builder /root/.local/share/uv /opt/uv
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini entrypoint.sh ./
COPY app ./app
COPY migrations ./migrations

RUN chmod +x /app/entrypoint.sh \
	&& python_bin="$(find /opt/uv/python -path '*/bin/python3.14' | head -n 1)" \
	&& if [ -z "$python_bin" ] || [ ! -x "$python_bin" ]; then python_bin="/usr/local/bin/python3.14"; fi \
	&& if [ ! -x "$python_bin" ]; then python_bin="/usr/local/bin/python3"; fi \
	&& [ -x "$python_bin" ] \
	&& ln -sf "$python_bin" /app/.venv/bin/python \
	&& ln -sf /app/.venv/bin/python /app/.venv/bin/python3 \
	&& ln -sf /app/.venv/bin/python /app/.venv/bin/python3.14 \
	&& groupadd --system appuser \
	&& useradd --system --gid appuser --create-home --home-dir /home/appuser appuser \
	&& chown -R appuser:appuser /app /opt/uv

ENV PATH="/app/.venv/bin:${PATH}"
ENV VIRTUAL_ENV="/app/.venv"

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
