# S9-03 Design — BGE-M3 Sparse Fallback

> Story: S9-03 from `docs/plan.md`

## Goal

S9-03 SHOULD improve sparse retrieval quality for installations whose configured language performs poorly with Qdrant BM25 on evals. The story MUST preserve the current dense retrieval path based on Gemini Embedding 2 and MUST keep the existing hybrid retrieval shape (dense leg + sparse leg + RRF fusion) intact at the application level.

The story is intentionally narrow. It is a sparse retrieval upgrade, not a full retrieval redesign, not a multilingual routing platform, and not a local ML serving project.

## Success Criteria

From `docs/plan.md`:

1. BM25 sparse retrieval can be replaced with BGE-M3 sparse retrieval for target languages with insufficient BM25 quality.
2. Dense retrieval remains based on Gemini Embedding 2.
3. Reindexing is supported for the sparse backend switch.
4. Language-specific evals show improved retrieval metrics versus BM25.

## Scope

### In scope

- Installation-level sparse backend switch: `bm25` or `bge_m3`
- Sparse-provider abstraction boundary
- BGE-M3 integrated through an external provider boundary
- Indexing pipeline changes needed to build sparse data from the active sparse backend
- Retrieval pipeline changes needed to query the active sparse backend
- Explicit reindex requirement when sparse backend changes
- Language-specific eval comparison against BM25
- Operational metadata and logs needed to make the switch auditable and debuggable

### Out of scope

- Any change to Gemini dense embeddings
- Query-time adaptive routing between BM25 and BGE-M3
- Per-language mixed sparse backends within one installation
- Simultaneous dual sparse runtime as a first-class v1 feature
- Google-specific serving architecture for BGE-M3
- Local in-process or in-container heavy ML inference stacks
- Changes to parent-child retrieval semantics, citation building, prompt assembly, or chat behavior beyond the sparse leg swap

## Decisions

### Decision 1: Sparse backend selection — one active sparse backend per installation

**Chosen:** One installation SHOULD expose exactly one active sparse backend at a time:

- `bm25`
- `bge_m3`

**Why:**

This is the best match for the current architecture and operating model. ProxyMind already treats language-sensitive behavior as installation configuration rather than runtime negotiation. Keeping sparse selection at installation scope makes indexing, retrieval, eval interpretation, reindex operations, and support workflows much easier to reason about. It also keeps the mental model simple: one deployment has one sparse retrieval strategy.

This decision also keeps S9-03 aligned with KISS and YAGNI. The story is about replacing an underperforming sparse method for a target language, not about building a general multilingual routing engine.

**Rejected alternatives:**

- **Per-language switch inside one installation** — more flexible for highly multilingual deployments, but it requires routing rules, mixed index semantics, more complex testing, and more operational ambiguity than this story justifies.
- **Adaptive query-time fallback** — too research-heavy, too difficult to verify, and too large in scope for a focused retrieval upgrade story.

### Decision 2: Use BGE-M3 only for sparse output

**Chosen:** BGE-M3 SHOULD be used only as the sparse retrieval replacement. Gemini Embedding 2 MUST remain the dense embedding provider.

**Why:**

This matches the canonical project documents exactly: `docs/spec.md` and `docs/rag.md` both state that BGE-M3 is a sparse fallback while dense retrieval remains Gemini-based. Preserving Gemini dense keeps the blast radius small and makes the eval story clean. Any metric improvement can be attributed to the sparse replacement rather than to simultaneous dense-model changes.

This choice also protects retrieval continuity. Query rewriting, child-first ranking, parent-aware context expansion, citation construction, and prompt assembly can continue to assume the same dense behavior.

**Rejected alternatives:**

- **Use BGE-M3 for both sparse and dense while keeping Gemini too** — creates unnecessary complexity around multiple dense legs, fusion behavior, and reindex semantics.
- **Replace the full embedding stack with BGE-M3** — contradicts the current spec and expands the story far beyond its intended scope.

### Decision 3: BGE-M3 integration model — vendor-neutral external sparse provider

**Chosen:** BGE-M3 SHOULD be integrated through a narrow, vendor-neutral external sparse provider boundary.

**Why:**

The project has an explicit cheap-VPS-first rule and a strict prohibition against local heavyweight ML runtimes in project environments and Docker images. Treating BGE-M3 as an external sparse provider preserves that rule, keeps the backend and worker containers lightweight, and avoids turning S9-03 into a local inference platform project.

A vendor-neutral boundary also keeps this story focused on the knowledge contour contract rather than on one infrastructure vendor. The application should care that an external sparse provider can build document and query sparse representations; it should not care whether the underlying hosting is self-managed elsewhere, managed by another internal service, or changed later.

**Rejected alternatives:**

- **Inline/local integration in backend or worker containers** — incompatible with the project’s local ML runtime policy.
- **Google-specific serving path as the main design** — possible in principle, but it adds unnecessary infrastructure coupling and complexity for a story whose goal is to avoid overengineering at the current stage.
- **Optional sidecar in the same compose stack** — operationally simpler than inline integration, but still pushes heavyweight inference concerns into the project’s primary deployment surface.

### Decision 4: Google technologies are not the primary v1 path for BGE-M3

**Chosen:** S9-03 SHOULD NOT depend on a Google-specific BGE-M3 serving design in v1.

**Why:**

Google technologies are already a strong fit elsewhere in the project: Gemini Embedding 2 for dense retrieval, Gemini Batch API for bulk processing, and Document AI for complex parsing fallback. Those are natural extensions of the current architecture.

BGE-M3 sparse fallback is different. The available Google capabilities help with generation, embeddings, multimodal processing, and enterprise hosting patterns, but they do not produce a simple, low-complexity Google-native replacement path for BGE-M3 sparse retrieval. Making Vertex AI or another Google-specific serving layer the primary design would turn a focused retrieval story into a custom serving and operations story. That would violate the intent to avoid unnecessary complexity at this stage.

This decision does not reject Google from the broader architecture. It only states that Google-specific BGE-M3 hosting is not the preferred v1 design for this story.

### Decision 5: Sparse backend switch requires explicit reindexing

**Chosen:** Changing `sparse_backend` from `bm25` to `bge_m3` SHOULD be treated as an index contract change and MUST require explicit reindexing.

**Why:**

BM25 and BGE-M3 sparse representations are operationally different indexing methods. Even if the application-level retrieval contract remains “dense + sparse + RRF,” the stored sparse artifacts are provider-specific and should not be mixed silently. An explicit reindex rule keeps the state model honest, auditable, and debuggable.

This also preserves clarity in failure recovery and rollback. If an operator wants to revert from `bge_m3` to `bm25`, the rollback procedure is clear: restore the previous sparse backend configuration and rebuild the sparse index under that backend.

**Rejected alternatives:**

- **Hot toggle without reindex** — unsafe because indexed sparse data and query sparse data would no longer be guaranteed compatible.
- **Mixed-mode migration with multiple valid sparse states** — adds complexity, weakens invariants, and makes debugging harder for limited product value.

### Decision 6: Keep the hybrid retrieval contract stable

**Chosen:** S9-03 SHOULD preserve the current hybrid retrieval structure:

1. build Gemini dense query embedding
2. build sparse query representation from the active sparse backend
3. execute dense + sparse hybrid retrieval
4. fuse results with RRF
5. keep current scope filters, child-first ranking, and context assembly semantics

**Why:**

The existing retrieval system is already integrated with parent-child context expansion, citation building, snapshot scoping, and prompt assembly. Reworking those parts would create regression risk unrelated to the actual value of this story. The cleanest design is to swap the sparse leg while keeping the surrounding retrieval and application contracts stable.

## Technical Design

## Architecture

S9-03 SHOULD introduce a sparse-provider abstraction in the knowledge contour. The abstraction SHOULD be intentionally narrow and only cover the responsibilities needed for indexing and search.

Conceptually, the active sparse provider must support:

- building sparse document representation for indexing
- building sparse query representation for retrieval
- exposing provider identity and version metadata for observability and reindex coordination

The retrieval layer SHOULD continue to think in terms of:

- dense leg
- sparse leg
- hybrid fusion

It SHOULD NOT need provider-specific branching spread across multiple services.

## Indexing Flow

The ingestion pipeline SHOULD preserve its current high-level stages:

1. parse source into normalized chunks
2. enrich text when enrichment is enabled
3. generate Gemini dense embeddings from the existing dense text source
4. generate sparse representation from the active sparse backend
5. upsert child points into Qdrant
6. preserve existing payload contract, including parent-aware metadata when present

The sparse text source SHOULD remain aligned with current retrieval design:

- use `enriched_text` when available
- otherwise use `text_content`

This preserves parity with the current BM25 behavior introduced by S9-01 and avoids introducing a second, unrelated text-selection policy.

## Retrieval Flow

The retrieval path SHOULD remain structurally unchanged:

1. optionally rewrite the query
2. generate a Gemini dense query embedding
3. generate the sparse query representation using the active sparse backend
4. run hybrid search in Qdrant
5. fuse dense and sparse results via RRF
6. apply existing context expansion and response assembly rules

Parent-child behavior MUST remain unchanged:

- child chunks remain the primary ranked unit
- parent context expansion remains a post-retrieval enrichment of selected child results

Citation building and prompt layering SHOULD remain unchanged because they operate on retrieved chunks and metadata, not on the sparse-generation mechanism.

## Qdrant Contract

The installation SHOULD maintain one dense vector family and one active sparse vector family. From the application perspective, the retrieval contract remains the same: one dense leg and one sparse leg.

S9-03 SHOULD avoid turning Qdrant schema management into a dual-provider experiment platform in v1. The story should preserve the simplest operational model compatible with an eval-driven sparse replacement.

The exact low-level Qdrant representation may evolve during implementation, but the design intent is stable:

- the application must treat the active sparse backend as a single coherent index contract
- switching sparse backend invalidates the previous sparse index artifacts
- retrieval and diagnostics must always know which sparse backend produced the active index data

## Configuration

The system SHOULD expose an installation-level setting conceptually equivalent to:

- `sparse_backend = bm25 | bge_m3`

Supporting operational settings MAY include:

- external sparse provider URL or endpoint configuration
- timeout and retry settings for the external sparse provider
- provider model identifier for logs and audit

The configuration model SHOULD stay installation-level rather than per-request or per-language inside one runtime. This preserves deterministic behavior and reduces operational ambiguity.

## Reindex and Migration

Switching sparse backend MUST be treated as a reindex-triggering change.

The design SHOULD record enough metadata to make the index state explicit, such as:

- active sparse backend identity
- sparse provider model or implementation identifier
- pipeline version or contract version when relevant

Operators SHOULD be able to answer these questions unambiguously:

- Which sparse backend produced the currently indexed sparse data?
- Is reindex required after configuration changes?
- Which eval result justified the switch?
- How do we roll back to the previous sparse backend if needed?

Rollback SHOULD remain straightforward:

1. restore previous sparse backend configuration
2. reindex with that backend
3. verify retrieval behavior against the prior baseline or comparison eval

## Error Handling and Failure Modes

The system MUST fail clearly when `sparse_backend=bge_m3` is configured but the external sparse provider is unavailable or invalid.

Silent degradation to empty sparse results is NOT acceptable because `docs/development.md` explicitly rejects fake or silent fallbacks that hide real failures.

The system SHOULD instead:

- log the active sparse backend and provider identity
- raise a clear operational error when the configured sparse provider cannot build indexing or query representations
- keep failure semantics explicit in indexing jobs and retrieval diagnostics

Whether the online retrieval path should hard-fail or support a narrowly defined real fallback in specific edge cases can be settled in implementation planning, but this story MUST avoid silent data-quality degradation disguised as a fallback.

## Testing Strategy

### Deterministic deploy tests

Deploy-test coverage SHOULD focus on contract correctness rather than on real model quality:

- sparse backend selection chooses the correct provider
- indexing path uses the active sparse provider
- retrieval path uses the active sparse provider
- enriched text vs original text selection remains correct for sparse generation
- provider metadata and reindex-required state are recorded correctly
- explicit error behavior is preserved when the configured BGE-M3 provider is unavailable
- the retrieval service contract remains dense + sparse + hybrid without application-level regressions

### Eval verification

Story success MUST be demonstrated by language-specific evals comparing:

- Gemini dense + BM25 sparse
- Gemini dense + BGE-M3 sparse

The eval comparison SHOULD keep the following constant:

- same dense model
- same chunking strategy
- same enrichment setting
- same snapshot scope
- same retrieval top-K and fusion behavior

This isolates the sparse variable and makes the upgrade decision evidence-based.

The primary metrics remain:

- Precision@K
- Recall@K
- MRR

## Operational Notes

S9-03 SHOULD be treated as an eval-gated upgrade path rather than a default replacement of BM25 everywhere.

The recommended operational rule is:

1. keep BM25 as the default sparse backend
2. run retrieval evals for the installation’s configured language
3. switch to BGE-M3 only when evals show BM25 is insufficient and BGE-M3 improves the target-language metrics
4. reindex explicitly under the new sparse backend

This keeps the system conservative by default while still allowing data-driven upgrades where BM25 quality is inadequate.

## Final Recommendation

ProxyMind SHOULD implement S9-03 as a **minimal, installation-level sparse backend replacement** with the following final shape:

- one active sparse backend per installation
- Gemini dense retrieval unchanged
- BGE-M3 used only for sparse output
- BGE-M3 integrated through a vendor-neutral external sparse provider boundary
- no Google-specific BGE-M3 serving design in v1
- explicit reindex when sparse backend changes
- language-specific evals as the decision gate for switching

This design best satisfies the project constraints:

- **KISS** — smallest useful change surface
- **YAGNI** — avoids building a multi-provider retrieval platform prematurely
- **cheap-VPS-first** — avoids local heavyweight ML runtimes
- **changeability** — isolates sparse-provider concerns behind a narrow boundary
- **verifiability** — keeps the eval result attributable to the sparse replacement itself
