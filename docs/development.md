# ProxyMind Development Standards

This document is the single source of truth for code quality, design principles, and engineering discipline in ProxyMind. Every contributor — human or AI agent — MUST follow these standards. Violations found during code review block merge.

## Core Formula

**Good software = working value + simplicity + changeability + disciplined changes + security + observability + automation.**

Everything else is a derived technique or a local heuristic.

---

## Part 1: Code-Level Principles

### SOLID

Apply SOLID to all backend service and module boundaries. These are not academic ideals — they are the mechanism that keeps ProxyMind changeable as it grows from bootstrap to full RAG pipeline.

- **Single Responsibility.** Each module, class, or function has one reason to change. `retrieval.py` handles retrieval logic — not prompt assembly, not citation building, not audit logging. When a file grows beyond ~300 lines, that is a signal it is doing too much.
- **Open/Closed.** Extend behavior through composition, new implementations, and dependency injection — not by editing stable code. When adding a new ingestion path, create a new handler; do not branch inside the existing one.
- **Liskov Substitution.** If a function accepts a base type, every subtype MUST work without the caller knowing the difference. This matters for LiteLLM provider abstraction, store clients, and any protocol-based interface.
- **Interface Segregation.** Depend on narrow interfaces. A service that only reads from Qdrant should not receive a client that also writes. Use Protocols where appropriate.
- **Dependency Inversion.** High-level policy (retrieval, ingestion, chat) MUST NOT depend on low-level details (specific DB drivers, HTTP clients). Depend on abstractions. Inject concrete implementations via FastAPI dependencies or constructor arguments.

### KISS — Keep It Simple

Simplicity is not laziness. It is the discipline of doing the minimum that solves the problem correctly.

- Prefer flat over nested. Prefer explicit over clever. Prefer boring over novel.
- If a solution requires a comment explaining "why this works," it is probably too clever.
- Do not add configuration for things that have one correct value. Do not add feature flags for things that are not features.
- Three similar lines of code are better than a premature abstraction.

### DRY — Don't Repeat Yourself

Eliminate duplication of **knowledge**, not duplication of characters.

- If two pieces of code change for the same reason, they are duplicates — extract.
- If two pieces of code look similar but change for different reasons, they are not duplicates — leave them alone.
- DRY applied prematurely creates wrong abstractions that are harder to fix than the duplication they replaced. When in doubt, duplicate first, abstract later.

### YAGNI — You Aren't Gonna Need It

Do not build for hypothetical future requirements.

- Implement what is needed for the current story. Not the next story. Not "just in case."
- YAGNI works only when the code is easy to change. If the code is hard to change, the problem is not missing features — it is missing refactoring.
- YAGNI does not mean "never improve the design." Refactoring is not adding features — it is making the system easier to change. Refactoring and YAGNI are allies, not opponents.

---

## Part 2: Mocks, Fallbacks, and Stubs Policy

This section is non-negotiable. Violations are treated as bugs.

### Mocks: tests only

Mocks, fakes, and test doubles are allowed **only inside `tests/`**. Production code MUST NOT contain mock implementations, fake clients, or simulated responses.

### Fallbacks: real alternatives only

A fallback MUST be a working alternative, not a stub or dead code path.

- Acceptable: query rewriting times out — fall back to the original user query (both are real, working inputs).
- Acceptable: BM25 quality is insufficient — fall back to BGE-M3 sparse vectors (both are real retrieval methods).
- Not acceptable: Qdrant is unreachable — fall back to returning empty results. That is not a fallback; that is silent failure.
- Not acceptable: LiteLLM call fails — fall back to a hardcoded response. That is a mock in disguise.

### Stubs: only for planned work, always with TODO

A stub is permitted **only** when the plan (`docs/plan.md`) describes future functionality that belongs in this exact location. Every stub MUST include:

```python
# TODO(S2-01): Replace with arq task enqueue.
# The ingestion worker picks up the task from Redis and processes the file
# through the Docling pipeline (Path A or Path B based on format/size).
# See docs/plan.md S2-01 and docs/architecture.md § Knowledge circuit.
raise NotImplementedError("Ingestion task enqueue — implemented in S2-01")
```

Requirements for stubs:
- The TODO MUST reference a specific story ID from `docs/plan.md` (e.g., `S2-01`).
- The TODO MUST describe **what** the real implementation does and **how** it integrates.
- The stub MUST fail loudly (`raise NotImplementedError`) — never return fake data or silently succeed.
- If a story has no planned functionality for this location, no stub is allowed. Remove the code path entirely.

---

## Part 3: Engineering Principles

### 1. Working software over activity

The measure of progress is working software that delivers value — not the number of files created, meetings held, or stories in the backlog. The project MUST be able to respond to change rather than rigidly follow an initial plan.

### 2. Simplicity is a first-class concern

Complexity is a hidden tax on development, maintenance, onboarding, and operations. Simplicity applies to code, APIs, configuration, processes, and the system lifecycle. Maximize the amount of work not done.

### 3. Design for change

Good architecture is not the one that looks elegant at the start — it is the one that can be safely modified later. High cohesion and loose coupling: things that change together live together; independent parts do not break each other.

In ProxyMind terms: the three circuits (dialogue, knowledge, operational) are independent by design. A change to the ingestion pipeline MUST NOT require changes to the chat endpoint. A change to the prompt assembly MUST NOT require changes to the retrieval service.

### 4. Code MUST be readable and maintainable

Readability reduces effort, shortens iteration time, and improves stability. Write code for the next person who reads it — not for the compiler.

- Names describe intent, not implementation.
- Functions are short and do one thing.
- Control flow is obvious. No hidden side effects.
- If code requires a wall of comments to understand, rewrite the code.

### 5. Refactoring is normal work

Refactoring is not a luxury, not tech debt payoff, and not a separate task. It is part of every change. When touching code, leave it better than you found it — within the scope of the current work.

Do not propose unrelated refactoring. Stay focused on what serves the current goal. A bug fix does not need the surrounding code reorganized.

### 6. Every meaningful change MUST be verifiable

Tests exist for confidence in changes, not for coverage metrics.

- Tests MUST be stable, fail for real reasons, and help localize the problem.
- Flaky tests are bugs. Fix or delete them.
- Tests MUST NOT depend on execution order, external services (in CI), or wall-clock time.
- Deploy tests (CI) are deterministic — no external provider dependencies.
- Quality tests (evals) run separately — they use real models and do not block CI.

### 7. Changes go through code review before merge

Code review maintains codebase quality over time, catches problems early, and spreads knowledge across the team. No exception for "small" changes — small changes with subtle bugs are the hardest to debug later.

### 8. Integrate frequently, in small increments

Frequent small commits reduce merge conflicts, make bisecting easier, and surface problems early. Long-lived branches are a liability. If a change cannot be integrated within a few days, it is too large — decompose it.

### 9. Builds and releases MUST be reproducible

One codebase under version control. Explicit dependencies (lock files committed). Minimal gap between dev and production environments.

- `uv.lock` and `bun.lock` are committed and used in CI and Docker builds.
- Docker images are built from the same lock files.
- If it works on your machine but not in Docker, the bug is in the setup, not in "Docker being weird."

### 10. Security is designed in, not bolted on

Security controls are part of the architecture, not an afterthought. This applies from the first line of code.

- Never trust user input. Validate at system boundaries.
- Never generate URLs in LLM prompts — the citation protocol exists to prevent link hallucination.
- Secrets live in `.env` files, never in code, never in git.
- Admin API is authenticated. Chat API has rate limiting. These are not optional features — they are baseline security.

### 11. Secure defaults and least privilege

The system MUST be secure by default. On failure, fall into a safe state — not an open one.

- Default deny: if there is no explicit permission, access is denied.
- Least privilege: each component gets the minimum access it needs.
- Fail-safe: if a security check fails or is absent, the system denies access rather than allowing it.

### 12. The system MUST be observable

Observability is the ability to understand the system from the outside — to ask questions without knowing all the internals.

- Structured logging (structlog, JSON) from day one.
- Correlation IDs across the request lifecycle.
- Metrics for the things that matter (latency, error rate, queue depth).
- Tracing for the things that span services.
- If you cannot tell why a request failed by looking at logs and traces, observability is incomplete.

### 13. Automate repetitive work

If the team does the same thing manually more than twice, automate it. Manual processes are slow, inconsistent, and error-prone.

- CI runs on every push.
- Linting and formatting are automated, not manual.
- Database migrations are code, not manual SQL scripts.
- Docker Compose starts the full environment with one command.

### 14. Document architectural decisions

Architecture Decision Records are the project's memory. Without them, in 3-6 months nobody remembers why the system is built this way.

In ProxyMind, architectural decisions are captured in:
- `docs/architecture.md` — system-level architecture.
- `docs/spec.md` — tools, versions, contracts.
- Design specs in `docs/superpowers/specs/` — per-story decisions with rationale.
- OpenSpec artifacts — per-change proposals, designs, and specs.

Do not duplicate decisions across these files. Each decision has one canonical location.

### 15. Use precise language in specifications

Specifications use RFC 2119 keywords: MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, MAY. This eliminates ambiguity between analysts, developers, testers, and integrators.

OpenSpec spec files in this project already follow this convention.

### 16. Sustainable pace

The quality of the codebase reflects the sustainability of the process. Chronic overtime masks bad architecture, bad planning, or bad process. Rushing produces technical debt that compounds over time.

Write code you would be comfortable maintaining a year from now.

---

## Part 4: How SOLID/KISS/DRY/YAGNI Relate to the Bigger Picture

| Principle | Is a specific instance of | Works only together with |
|-----------|--------------------------|--------------------------|
| KISS | Simplicity (principle 2) | Readability (4), refactoring (5) |
| YAGNI | "Do not build what is not needed" (2) | Refactoring (5), changeability (3) |
| SOLID | Changeability and managed growth (3) | Simplicity (2) — over-applying SOLID creates unnecessary abstractions |
| DRY | Knowledge deduplication (4) | Simplicity (2) — premature DRY creates wrong abstractions |

These four are local heuristics. They are useful but insufficient on their own. The engineering principles in Part 3 are the foundation; SOLID/KISS/DRY/YAGNI are tools for applying them at the code level.

---

## Quick Reference

Before submitting code, verify:

- [ ] Does this change deliver working value for the current story?
- [ ] Is this the simplest solution that correctly solves the problem?
- [ ] Can this code be changed safely in the next story?
- [ ] Would another developer understand this code without asking me?
- [ ] Are there tests for the meaningful behavior introduced?
- [ ] Are there any mocks outside `tests/`?
- [ ] Are there any fallbacks to stubs or dead code?
- [ ] Are all stubs linked to a specific story in `docs/plan.md`?
- [ ] Do all dependencies come from lock files?
- [ ] Are secrets outside of code and git?

## Apply Workflow Hook

This document is not background reading. In ProxyMind OpenSpec workflow it is a required checkpoint.

For every `/opsx:apply` execution:

1. Before writing code, read this file.
2. After implementation, re-read this file and self-review the change against it.
3. In the completion report, explicitly state that both steps were completed.

If step 1 or step 2 was skipped, the apply workflow is incomplete even if the code and tests pass.
