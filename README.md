# ProxyMind

ProxyMind is a self-hosted open-source digital twin: an AI agent that knows, thinks, and communicates like its prototype.

One installation equals one twin. The twin combines three layers:

- Knowledge: a versioned knowledge base built from the prototype's materials
- Character: voice, tone, values, and communication style
- Behavior: boundaries, reactions, and dialogue rules

The product is designed to answer from a published knowledge snapshot, cite real source materials, and remain fully owned by the operator.

## Status

This repository is currently in the specification and planning stage.

At the moment, the repo contains:

- product documentation
- architecture and technical specifications
- development plan
- OpenSpec workflow configuration and change history

Application code is expected to be built story by story through the OpenSpec workflow described below.

## What ProxyMind Aims To Provide

- Self-hosted digital twin for a real person or character
- Versioned knowledge snapshots with publish, test, and rollback flow
- Persona-driven responses via `IDENTITY.md`, `SOUL.md`, and `BEHAVIOR.md`
- Retrieval-augmented answers with citations to source materials
- Native commercial recommendations via `PROMOTIONS.md`
- Multilingual support for retrieval and text processing
- Compatibility with open agent ecosystems through A2A and MCP
- Future support for external messaging and social platforms through channel connectors

## Core Product Principles

- One instance = one twin
- The published knowledge snapshot is the source of truth for answers
- If knowledge is missing, the twin should say so instead of inventing facts
- Citations are grounded in source metadata, not model-generated URLs
- Personality is configured through files, not a single prompt string
- Data, infrastructure, and configuration stay under the owner's control

## Repository Layout

Current top-level structure:

```text
.
├── docs/          # Product, architecture, RAG, agent, and plan documents
├── openspec/      # OpenSpec config, active changes, archived changes, specs
├── AGENTS.md      # Repository-specific agent instructions
├── CLAUDE.md      # Additional repository guidance
└── README.md
```

Important documents:

- [docs/about.md](docs/about.md): product vision and scope
- [docs/architecture.md](docs/architecture.md): system architecture and data flows
- [docs/spec.md](docs/spec.md): technical contracts, tools, and version requirements
- [docs/rag.md](docs/rag.md): retrieval and ingestion pipeline details
- [docs/agent.md](docs/agent.md): persona and configuration file model
- [docs/plan.md](docs/plan.md): phased story-based development plan

## Development Workflow

This project uses OpenSpec as the primary planning and execution workflow.

Rules of engagement:

- Each story in [docs/plan.md](docs/plan.md) maps to one OpenSpec change
- Work starts from specs and planning artifacts before implementation
- Repository context is captured in [openspec/config.yaml](openspec/config.yaml)
- After implementation, package versions must be checked against [docs/spec.md](docs/spec.md)
- After archiving a change, the corresponding story in [docs/plan.md](docs/plan.md) should be marked done

See [openspec/config.yaml](openspec/config.yaml) and the files under [openspec/](openspec/) for the project-specific workflow setup.

## Planned System Shape

ProxyMind is planned as a monorepo with separate backend and frontend parts.

Target stack:

- Backend: Python, FastAPI, SQLAlchemy, Alembic, asyncpg, arq, LiteLLM, structlog
- Data: PostgreSQL, Qdrant, SeaweedFS, Redis
- AI and processing: Gemini Embedding 2, Docling, Gemini Batch API
- Frontend: Bun, React, Vite, Biome
- Infra: Docker, Caddy, Prometheus, Grafana, OpenTelemetry

For exact minimum versions, use [docs/spec.md](docs/spec.md) as the single source of truth.

## Current Roadmap Shape

The development plan is organized as vertical slices. Early phases establish a runnable system and a first end-to-end knowledge-to-answer flow. Later phases expand retrieval quality, persona, frontend capabilities, evaluation, agent protocols, and future external channel support.

The current plan covers:

- Bootstrap and infrastructure
- Database and ingestion pipeline
- Knowledge snapshots and minimal chat
- Persona, citations, streaming, and memory
- Web UI and admin UI
- Commerce and promotions
- Operations, auth, audit, and observability
- Evals and RAG upgrades
- A2A and MCP support
- External channel connectors and implicit visitor identity in later stages

See [docs/plan.md](docs/plan.md) for the detailed story list.

## Notes For Contributors

- All source code and documentation are written in English
- Do not assume hardcoded single-language behavior; language-dependent components must remain configurable
- Do not introduce dependencies below the minimum versions in [docs/spec.md](docs/spec.md)
- Do not treat admin authentication and visitor identity as the same concern; future external channel support depends on that separation

## License

ProxyMind is distributed under the terms of the [LICENSE](LICENSE) file in this repository.
