## Story

**S4-01: Persona loader** (Phase 4: Dialog Expansion)

Verification criteria from plan.md:
- Change SOUL.md → restart → response style changed
- System safety policy cannot be bypassed via persona

Stable behavior that must be covered by tests:
- Persona files are loaded at startup and injected into the system prompt
- Safety policy is always first in the system message and cannot be overridden
- Config hashes (`config_commit_hash`, `config_content_hash`) are computed and logged with every response
- Missing/empty persona files degrade gracefully (empty string, warning logged)

## Why

The twin currently responds with a generic, impersonal system prompt. To fulfill the core product promise — "an AI agent that knows, thinks, and communicates like its prototype" — the dialogue circuit must load the owner's persona configuration (IDENTITY.md, SOUL.md, BEHAVIOR.md) and inject it into every LLM call. Additionally, every response must carry config hashes for audit reproducibility, and an immutable safety policy must prevent the persona from overriding security constraints.

## What Changes

- New `app/persona/` module with `PersonaLoader`, `PersonaContext` dataclass, and `SYSTEM_SAFETY_POLICY` constant
- Prompt builder (`app/services/prompt.py`) updated to accept persona context and assemble system message as: safety policy → identity → soul → behavior
- Old hardcoded `SYSTEM_PROMPT` removed from prompt.py and from `app/services/__init__.py` re-exports
- `ChatService` receives `PersonaContext` and logs `config_commit_hash` + `config_content_hash` via structlog with every response (both LLM and refusal paths). Hashes are NOT part of the API response payload — they are observability-only in S4-01. DB persistence (Message/AuditLog fields) is deferred to S7-03.
- FastAPI lifespan loads persona at startup via configurable `PERSONA_DIR` / `CONFIG_DIR` settings
- Docker: volume mounts for persona/config on API container, `GIT_COMMIT_SHA` build-arg in Dockerfile

## Capabilities

### New Capabilities
- `persona-loader`: Persona file loading, system safety policy, config hashing, and prompt injection

### Modified Capabilities
- `chat-dialogue`: System prompt assembly now includes persona layers; config hashes logged on every response path

## Impact

- **Code:** New `backend/app/persona/` package; modified `prompt.py`, `chat.py`, `dependencies.py`, `main.py`, `services/__init__.py`
- **Config:** New `PERSONA_DIR`, `CONFIG_DIR` settings; `GIT_COMMIT_SHA` build-arg
- **Docker:** API container gets persona/config volume mounts; Dockerfile accepts GIT_COMMIT_SHA
- **API:** No API contract changes. Internal prompt structure changes (invisible to clients).
- **Dependencies:** No new Python dependencies
