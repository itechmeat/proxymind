# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Date Context

It is March 2026. When searching for tools, libraries, versions, or best practices, always search with this date context. Use queries like "best X in 2026", "X vs Y 2026", "latest X 2026" to get up-to-date results. Do not rely on outdated knowledge — verify everything against current state.

## Version Policy

All tools and dependencies MUST be installed at versions equal to or greater than those specified in `docs/spec.md`. Never downgrade below the minimum versions listed in the spec. If a version is marked as "—" (dash), the exact version is not yet pinned — use the latest stable release available.

### Container-Only Backend Rule

- Backend dependencies, checks, tests, migrations, and runtime validation MUST run only inside Docker containers. Do not install or verify backend Python packages in the host operating system.
- Backend package, tool, runtime, and library installation is allowed only inside Docker containers. Do not install anything for the backend on the host machine unless the user has given explicit permission.
- Before any backend verification, use `docker compose` to build or run the relevant backend container and execute commands there.
- Local ML frameworks and heavyweight inference runtimes are strictly forbidden in the project and its Docker images. Do not install `torch`, `torchvision`, `transformers`, CUDA runtimes, OCR/vision ML stacks, or similar packages.

### Execution Timeout Discipline

- No single waiting period for a command, build, install, test run, service startup, migration, or log observation may exceed 5 minutes.
- If the operation is still progressing, the agent may continue in additional 5-minute waiting periods, but no more than 3 consecutive periods total for the same operation.
- Every time an operation does not complete within a 5-minute period, the agent MUST treat that as an investigation trigger and report the current blocker, the most likely causes, and probable repair options before continuing.

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
2. Consult the `commits` skill in the same turn and use it to propose a conventional commit message. Paraphrasing from memory does NOT satisfy this requirement. This step is MANDATORY.
3. Propose a branch name in the archive summary. Use the format `<type>/<change-name>` where `<type>` matches the primary conventional-commit intent (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`). For normal story delivery, default to `feat/<change-name>` unless a narrower type is clearly more accurate.
4. The archive summary MUST end with an explicit block containing both lines exactly in this form:
   `Proposed branch name: <type>/<change-name>`
   `Proposed commit message: <type>(<scope>): <description>`
5. Never commit without explicit user permission.
6. Do not archive non-Phase-1 changes as "complete" unless stable implemented behavior is already covered by tests or the gap is explicitly documented.

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

If a policy or workflow step explicitly names a skill, the agent MUST actually consult that skill in the current turn before claiming compliance. Remembering the skill's guidance from an earlier turn or from memory is not sufficient.

## Delegation

When delegating to agents, pass raw intent — what needs to happen and why. Don't specify files, formats, or structure. Don't enumerate what to keep, remove, or add — describe the goal and constraints, let the agent decide. Preserve the user's original words and scope. Each agent owns its domain and knows its own guidelines. Micromanaging duplicates their built-in knowledge and risks contradicting it.

## Development workflow

When delegating work to subagents or spawning a team, use the `/team-lead` skill.

### Skills

Skills MUST stay project-local. Never install skills globally.

- Before searching externally, first check whether a suitable skill is already available in the
  current agent context or in the project skill directories.

### Skill discovery

After planning a story (or any development task), the agent MUST resolve skills in this order:

1. Check the skills already exposed in the current agent/session context. If a suitable skill is
   already visible to the agent, use it directly and do not perform redundant external discovery.
2. Check the repo-local skill directories for a suitable existing skill (`.claude/skills`).
3. If no suitable repo-local skill exists, check user-global skill directories already available on
   the machine to the current agent runtime (for example user-level `.claude/skills`).

Only if no suitable in-context, repo-local, or user-global skill is found, the agent MAY use the
`find-skills` skill to search for relevant skills matching the technologies and tools involved.
Search priority sources first, then fall back to general search:

**Priority sources (search in this order):**

1. `https://github.com/itechmeat/llm-code`
2. `https://github.com/ancoleman/ai-design-components`
3. `https://github.com/trailofbits/skills`
4. `https://skills.sh/antfu/skills`
5. `https://skills.sh/wshobson/agents`
6. `https://github.com/coreyhaines31/marketingskills`

Search queries should cover the key technologies of the current task (e.g., "FastAPI", "React",
"LiveKit", "PostgreSQL", "pgvector", "Docker", "Vite", "Bun", "SQLAlchemy", "Alembic").
Install any found skills **into the project** before starting implementation, with `.agents/skills`
as the canonical install location, and also install or link the same skill in `.claude/skills`.
Never use a global install:

```bash
npx skills add <owner/repo@skill> -y        # project-local only
# Keep the installed skill in .agents/skills
# For Claude Code, also mirror or link it into .claude/skills
# Do NOT use -g flag
```
