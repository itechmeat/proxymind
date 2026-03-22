# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Date Context

It is March 2026. When searching for tools, libraries, versions, or best practices, always search with this date context. Use queries like "best X in 2026", "X vs Y 2026", "latest X 2026" to get up-to-date results. Do not rely on outdated knowledge — verify everything against current state.

## Version Policy

All tools and dependencies MUST be installed at versions equal to or greater than those specified in `docs/spec.md`. Never downgrade below the minimum versions listed in the spec. If a version is marked as "—" (dash), the exact version is not yet pinned — use the latest stable release available.

## Product Language Policy

ProxyMind is an open-source product designed for **English by default**, but MUST support multilingual usage. All language-dependent components (BM25 tokenization, stemming, stopwords, embedding task types, UI labels) must be configurable per installation. Never hardcode a specific language — always use a language setting. When implementing search, chunking, or text processing, ensure the solution works across popular languages (English, Russian, Spanish, German, French, Chinese, Japanese, Korean, etc.).

## Development Workflow

All project work is managed through OpenSpec. Each story from `docs/plan.md` = one OpenSpec change.

### Pre-apply checklist (before implementation)

Before writing code for an implementation (`/opsx:apply`), you MUST:

1. Before writing code, read `docs/development.md` and treat it as the binding implementation standard.

### Post-apply checklist (after implementation)

Before considering an implementation complete, you MUST:

1. Re-read `docs/development.md` and self-review the change against it.
2. In the final apply report, explicitly state that the pre-code read and post-code self-review against `docs/development.md` were completed.
3. Verify all installed package versions are not below minimums in `docs/spec.md`.
4. Run CI tests and confirm they pass.
5. For stories outside Phase 1, review stable implemented behavior and ensure it is covered by tests before considering the change complete.
6. If test coverage is missing or weak, propose and add the missing tests based on the most relevant repo skills (for example `vitest`, `react-testing-library`, `fastapi`, `postgresql`, `property-based-testing`) before archive.

### Post-archive checklist (after archiving)

After archiving a change (`/opsx:archive`), you MUST execute ALL steps below **before** presenting the archive summary to the user. The archive is NOT complete until every step is done. Do NOT output the archive summary and then "forget" the remaining steps.

1. Mark the corresponding story checkbox in `docs/plan.md` as done (`- [x]`).
2. Propose commit messages using the `commits` skill (conventional commits format). This step is MANDATORY — the archive summary MUST include the proposed commit message at the end.
3. Never commit without explicit user permission.
4. Do not archive non-Phase-1 changes as "complete" unless stable implemented behavior is already covered by tests or the gap is explicitly documented.

## Project Overview

ProxyMind is a self-hosted open-source digital twin — an AI agent that knows, thinks, and communicates like its prototype. One instance = one twin. See `docs/about.md` for full vision.

## Tech Stack

- Backend: Python, FastAPI, SQLAlchemy, Alembic, asyncpg, arq, LiteLLM, structlog
- Data: PostgreSQL, Qdrant, SeaweedFS, Redis
- AI: Gemini Embedding 2, Docling, Gemini Batch API
- Frontend: Bun, React, Vite, Biome
- Infra: Docker, Caddy, Prometheus, Grafana, OpenTelemetry

For versions, see `docs/spec.md`.

## Project Structure

Monorepo with separate backend and frontend. See `docs/architecture.md` for full structure.

## Language Policy

- All source code files: English (variable names, comments, logs)
- All documentation files (docs/\*.md, README.md, CLAUDE.md, AGENTS.md): English

## Git Policy

NEVER commit, amend, or push without explicit user permission. Only create commits when the user explicitly asks to commit.

## LLM Provider

Default provider is configured via `.env` (ZAI by default). Do not ask which provider to use — it is always determined by `.env` unless overridden in the API request body.

## Key Patterns

- Three system circuits: dialogue, knowledge, operational (see `docs/architecture.md`)
- Ingestion: Docling parsing → HybridChunker → Gemini Embedding 2 → Qdrant (see `docs/rag.md`)
- Retrieval: hybrid search (dense + BM25 sparse, RRF fusion), scoped by snapshot_id
- Chat: SSE streaming, citation builder (source_id → URL/text), query rewriting
- Persona: IDENTITY.md + SOUL.md + BEHAVIOR.md files, loaded into system prompt
- Knowledge snapshots: draft → published → active → archived lifecycle
- Audit: every response logged with snapshot_id + config_commit_hash + config_content_hash

## Skills & Docs Attribution

Every final report MUST include at the end:

- `Skills used: <list>` — if any skills were consulted
- `Docs used: <list>` — if any external documentation was fetched, on the new line of the report

## Delegation

When delegating to agents, pass raw intent — what needs to happen and why. Don't specify files, formats, or structure. Don't enumerate what to keep, remove, or add — describe the goal and constraints, let the agent decide. Preserve the user's original words and scope. Each agent owns its domain and knows its own guidelines. Micromanaging duplicates their built-in knowledge and risks contradicting it.

## Development workflow

When delegating work to subagents or spawning a team, use the `/team-lead` skill.

### Skills

Skills are ONLY for Claude Code. Install into the project (not globally):

```bash
npx skills add <owner/repo@skill> -y        # project-local, NO -g flag
```

### Skill discovery

After planning a story (or any development task), the agent MUST use the `find-skills` skill to
search for relevant skills matching the technologies and tools involved. Search priority sources
first, then fall back to general search:

**Priority sources (search in this order):**

1. `https://github.com/itechmeat/llm-code`
2. `https://github.com/ancoleman/ai-design-components`
3. `https://github.com/trailofbits/skills`
4. `https://skills.sh/antfu/skills`
5. `https://skills.sh/wshobson/agents`
6. `https://github.com/coreyhaines31/marketingskills`

Search queries should cover the key technologies of the current task (e.g., "FastAPI", "React",
"LiveKit", "PostgreSQL", "pgvector", "Docker", "Vite", "Bun", "SQLAlchemy", "Alembic").
Install any found skills **into the project** (not globally) before starting implementation:

```bash
npx skills add <owner/repo@skill> -y        # project-local (default)
# Do NOT use -g flag — keep skills scoped to this project
```
