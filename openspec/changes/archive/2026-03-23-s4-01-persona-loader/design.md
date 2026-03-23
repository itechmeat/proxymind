## Context

ProxyMind's dialogue circuit currently uses a hardcoded, generic system prompt (`SYSTEM_PROMPT` in `prompt.py`). The twin has no personality — every instance responds identically. To fulfill the core product promise ("an AI agent that knows, thinks, and communicates like its prototype"), the dialogue circuit must load the owner's persona configuration (`IDENTITY.md`, `SOUL.md`, `BEHAVIOR.md`) from the filesystem and inject it into every LLM call.

Additionally, the architecture requires every response to carry `config_commit_hash` and `config_content_hash` for audit reproducibility (architecture.md, operational circuit). The DB columns exist since S1-02 but remain NULL. This story computes the hashes and logs them via structlog; DB persistence is deferred to S7-03.

Affected circuit: **Dialogue** only. Knowledge and operational circuits are unchanged.

## Goals / Non-Goals

**Goals:**

- Load persona files (`IDENTITY.md`, `SOUL.md`, `BEHAVIOR.md`) at application startup and cache in memory
- Inject an immutable system safety policy as the first element of every system message, ahead of persona content
- Assemble system prompt in defined layer order: safety policy, identity, soul, behavior
- Compute `config_content_hash` (SHA-256 of `persona/` + `config/` contents) and `config_commit_hash` (git SHA) at startup
- Log both hashes with every chat response (both LLM-generated and code-level refusal paths) via structlog
- Degrade gracefully when persona files are missing or empty

**Non-Goals:**

- Hot-reload of persona files without restart (YAGNI for v1)
- Token budget management for persona content (S4-06)
- PROMOTIONS.md injection into prompt (S4-05)
- Conversation history in prompt (S4-07)
- Audit log persistence to PostgreSQL (S7-03)
- Worker persona loading (worker does not need persona for ingestion)

## Decisions

### D1: Load at startup, not hot-reload or file-watcher

Persona files are read once during FastAPI lifespan. Restart required to apply changes.

**Alternatives rejected:**
- *Lazy reload with TTL cache* — adds race conditions between API and worker, unpredictable hash for audit, violates KISS.
- *File-watcher (watchfiles)* — extra dependency, Docker volume/inotify complexity, overkill for v1.

**Rationale:** The plan's verification criterion explicitly says "change SOUL.md -> restart -> response style changed." Load-at-startup is the natural fit. The `PersonaLoader` interface does not preclude adding reload later.

### D2: Standalone PersonaLoader service, not inline in prompt builder

Dedicated `PersonaLoader` class in `app/persona/loader.py` returning a frozen `PersonaContext` dataclass. Prompt builder receives `PersonaContext` as an argument.

**Alternatives rejected:**
- *Inline in prompt builder* — violates SRP (prompt builder should not know filesystem). Module-level state complicates testing.
- *Part of Settings (pydantic-settings)* — Settings holds env vars and scalars, not large text blocks. Hashes don't fit the settings model.

**Rationale:** architecture.md already designates `app/persona/` for this purpose. Standalone service follows SRP, is trivially testable, and integrates via FastAPI dependency injection.

### D3: Missing files produce warning + empty string (fail-safe)

If a persona file is missing or empty at startup: log a warning via structlog, use an empty string for that field. The twin operates without that persona dimension but retains the safety policy.

**Rationale:** Fail-safe over fail-hard. A twin without personality is better than a twin that refuses to start. The safety policy is hardcoded and always present regardless.

### D4: config_content_hash covers persona/ + config/ (raw bytes, SHA-256)

Hash scope includes both directories even though `config/PROMOTIONS.md` is not injected until S4-05. All files are read as raw bytes (not text) to ensure deterministic hashing across platforms. Files are sorted by relative path, each entry is `relative_path_as_utf8_bytes + \x00 + file_bytes`, concatenated, then SHA-256 hashed.

**Rationale:** Per spec.md requirement. The hash reflects full configuration state for audit, not just what is currently used in the prompt.

### D5: config_commit_hash via GIT_COMMIT_SHA env var with fallback

Priority chain: `GIT_COMMIT_SHA` env var (set as Docker build-arg) -> `git rev-parse HEAD` subprocess (once at startup) -> `"unknown"`.

**Rationale:** In Docker, `.git` is typically absent, so the env var is the primary mechanism. Subprocess fallback covers local development. The Dockerfile MUST accept the build-arg and docker-compose MUST pass the current git SHA at build time.

### D6: Path resolution via configurable PERSONA_DIR / CONFIG_DIR

New `PERSONA_DIR` and `CONFIG_DIR` settings in pydantic-settings. Defaults use `REPO_ROOT / "persona"` and `REPO_ROOT / "config"` for local dev. Docker containers MUST set these explicitly (`/app/persona`, `/app/config`) because `REPO_ROOT` auto-detection overshoots in containers.

**Alternative rejected:** Hardcoded `REPO_ROOT`-relative paths — breaks in Docker where directory layout differs from dev.

### D7: System safety policy as immutable constant, not loaded from file

The safety policy is a hardcoded Python constant in `app/persona/safety.py`. It is always the first element in the system message. Ordering is an architectural guarantee, not a runtime check.

**Rationale:** The safety policy is an engineering invariant, not owner-configurable content. Loading it from a file would create a vector for accidental or deliberate bypass. Keeping it as a constant makes it version-controlled in code and visible in code review.

### D8: Audit scope — structlog only in S4-01

Config hashes are logged via structlog with every response. They are NOT written to `Message.config_commit_hash` / `Message.config_content_hash` or `AuditLog` DB fields — that persistence is S7-03. The DB columns already exist (from S1-02) but remain NULL.

**Rationale:** Minimizes scope. Structlog already provides observability for debugging and verification. DB persistence adds transactional complexity that belongs in the audit story.

## Risks / Trade-offs

**[Restart required for persona changes]** -> Acceptable for v1. Persona changes are infrequent, and the verification criterion explicitly expects restart. The PersonaLoader interface allows adding reload in a future story without breaking changes.

**[REPO_ROOT miscalculation in Docker]** -> Mitigated by making paths configurable via env vars. Docker containers MUST set `PERSONA_DIR` and `CONFIG_DIR` explicitly. Default values only serve local development.

**[GIT_COMMIT_SHA not set in Docker]** -> Falls back to `"unknown"`, which defeats audit purpose. Mitigated by wiring the build-arg in docker-compose.yml and documenting the usage in `.env.example`. For local dev, `"unknown"` is acceptable. For production, CI/CD pipelines SHOULD pass the SHA via `GIT_COMMIT_SHA=$(git rev-parse HEAD) docker compose build`.

**[config_content_hash includes config/ but PROMOTIONS.md is not used yet]** -> Intentional. Hash changes when any config file changes, even if the prompt does not use that file yet. This is correct for audit (tracks full config state) but may cause false positives in change detection. Acceptable trade-off for simplicity.

**[Old SYSTEM_PROMPT removal is a breaking internal change]** -> The hardcoded `SYSTEM_PROMPT` and its re-export in `app/services/__init__.py` are removed. Any code referencing the old constant will fail at import time (loud failure, easy to catch). No external API changes.

**[Safety policy bypass via persona content]** -> Mitigated by architectural ordering: safety policy is always first in the system message. LLM instruction-following prioritizes earlier system instructions. This is defense-in-depth, not a cryptographic guarantee — but it is the standard approach for system prompt layering.
