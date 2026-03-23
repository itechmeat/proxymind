## 0. TODO Stub Resolution

No existing `TODO(S4-01)` stubs found in the codebase. Nothing to resolve.

## 1. System Safety Policy

- [x] 1.1 Create `backend/app/persona/__init__.py` package with re-exports
- [x] 1.2 Create `backend/app/persona/safety.py` with `SYSTEM_SAFETY_POLICY` constant
- [x] 1.3 Write unit tests for safety policy (`backend/tests/unit/test_persona_safety.py`)
- [x] 1.4 Run tests, verify pass

## 2. PersonaLoader and PersonaContext

- [x] 2.1 Create `backend/app/persona/loader.py` with `PersonaContext` dataclass and `PersonaLoader` class
- [x] 2.2 Write unit tests for PersonaLoader (`backend/tests/unit/test_persona_loader.py`): all files present, missing files, empty files, missing dir, hash determinism, hash sensitivity, config_dir inclusion, commit hash env var priority, frozen dataclass
- [x] 2.3 Run tests, verify pass

## 3. Prompt Builder Update

- [x] 3.1 Update `backend/app/services/prompt.py`: add `persona: PersonaContext` parameter to `build_chat_prompt`, assemble system message as safety → identity → soul → behavior, remove old `SYSTEM_PROMPT`
- [x] 3.2 Remove `SYSTEM_PROMPT` from `backend/app/services/__init__.py` re-exports (`_EXPORTS` and `__all__`)
- [x] 3.3 Rewrite `backend/tests/unit/test_prompt_builder.py` for new signature: safety policy first, persona layers present, empty fields skipped, all-empty persona still has safety
- [x] 3.4 Run tests, verify pass

## 4. ChatService Integration

- [x] 4.1 Update `backend/app/services/chat.py`: add `persona_context: PersonaContext` to constructor, pass to `build_chat_prompt`, add config hash logging to both `chat.assistant_completed` and `chat.refusal_returned` log events
- [x] 4.2 Update `backend/tests/unit/test_chat_service.py`: add `persona_context` fixture, update all `ChatService` constructor calls, add structlog capture tests for config hashes on both response paths
- [ ] 4.3 Run tests, verify pass

## 5. DI Layer and Chat API

- [x] 5.1 Add `get_persona_context` dependency to `backend/app/api/dependencies.py`, update `get_chat_service` to inject `PersonaContext`
- [x] 5.2 Update `backend/tests/conftest.py`: add `PersonaContext` to `chat_app` fixture's `app.state`
- [ ] 5.3 Run full unit test suite, verify pass

## 6. Settings and Lifespan

- [x] 6.1 Add `persona_dir` and `config_dir` fields to `Settings` in `backend/app/core/config.py` with `REPO_ROOT`-based defaults
- [x] 6.2 Add persona loading to FastAPI lifespan in `backend/app/main.py` using `Path(settings.persona_dir)` and `Path(settings.config_dir)`
- [x] 6.3 Write lifespan happy-path test in `backend/tests/unit/test_app_main.py`: verify `app.state.persona_context` is populated with correct values
- [x] 6.4 Write "file change → restart" test in `backend/tests/unit/test_app_main.py`: verify changed persona file produces different PersonaContext on second lifespan run
- [ ] 6.5 Run tests, verify pass

## 7. Docker Configuration

- [x] 7.1 Add persona/config volume mounts and `PERSONA_DIR`/`CONFIG_DIR` env vars to `api` service in `docker-compose.yml` (NOT worker)
- [x] 7.2 Add `GIT_COMMIT_SHA` build-arg to `api` and `worker` build sections in `docker-compose.yml`
- [x] 7.3 Add `ARG GIT_COMMIT_SHA` and `ENV GIT_COMMIT_SHA` to `backend/Dockerfile`
- [x] 7.4 Add `GIT_COMMIT_SHA=` entry to `.env.example` with usage comment
- [x] 7.5 Verify `docker compose config --quiet` exits 0

## 8. End-to-End Persona Verification

- [x] 8.1 Write end-to-end test: send message via `chat_client` (real HTTP path through DI), inspect `mock_llm_service.complete.call_args` to verify system message contains safety policy + persona content from `app.state.persona_context`
- [ ] 8.2 Run full unit test suite: `cd backend && python -m pytest tests/unit/ -v`
- [ ] 8.3 Run integration tests: `cd backend && python -m pytest tests/integration/test_chat_api.py -v`
- [x] 8.4 Run linting: `cd backend && python -m ruff check app/ tests/`

## 9. Test Coverage Review

- [x] 9.1 Review test coverage for all stable behavior introduced by S4-01: persona loading, safety policy immutability, prompt assembly, config hash logging, graceful degradation on missing files, file-change-restart cycle
- [x] 9.2 Identify and fill any gaps — propose additional tests if needed

## 10. Dependency Version Verification

- [x] 10.1 Verify all installed package versions are ≥ minimums specified in `docs/spec.md`
