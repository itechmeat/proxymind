# S9-02 Design — Parent-Child Chunking

> Story: S9-02 from `docs/plan.md`
> 
> Goal: hierarchical indexing for books and other long-form, book-like documents, with retrieval by child and context expansion from parent.

## 1. Scope and behavior

### Purpose

S9-02 SHOULD improve answer quality on long-form, book-like documents by separating:

- **retrieval precision** at the child-chunk level
- **answer context richness** at the parent-section level

### In-scope behavior

For qualifying Path B and Path C long-form documents:

1. The ingestion pipeline SHOULD derive a **structure-first hierarchy** from the normalized parsing output.
2. A **parent unit** SHOULD represent a bounded semantic section, preferably aligned with document headings.
3. A **child unit** SHOULD remain the primary indexed retrieval fragment.
4. Retrieval SHOULD search and rank **children only**.
5. Context assembly SHOULD provide **child + parent** to the LLM.
6. Citations SHOULD remain grounded in the matched **child**, not replaced by the parent.

### Qualification rules

The first version SHOULD enable parent-child chunking only for documents that satisfy explicit long-form eligibility thresholds.

Eligibility SHOULD be deterministic and based on properties already available in the pipeline, such as:

- minimum parsed token count
- minimum chunk count
- presence of hierarchical structure or other stable section signals

Heading-rich structure SHOULD be preferred, but it is not a hard requirement for qualification. Weakly structured long-form documents MAY still qualify when they clearly exceed the long-form thresholds and can be grouped deterministically through bounded fallback logic.

Short documents SHOULD continue to use the existing flat chunking path. Weakly structured long-form documents SHOULD NOT be forced onto the flat path merely because heading extraction is shallow or absent.

### Non-goals

The following remain out of scope for S9-02:

- sibling expansion
- multi-level retrieval beyond one parent layer
- Path A hierarchy
- manual owner-controlled opt-in or opt-out
- citation protocol redesign
- admin UI changes except minimal debug visibility if later proven necessary

## 2. Key decisions and rationale

### D1. Canonical hierarchy model

**Decision:** Use a **structure-first parent-child model with bounded fallback grouping**.

**Rationale:**

Parent chunks SHOULD be derived from normalized document hierarchy first because this best matches book-like sources, preserves semantic boundaries, and aligns with the existing ProxyMind RAG architecture. A pure fixed-window strategy was rejected as the primary model because it is easier technically but weaker semantically and less explainable during debugging, citation inspection, and future admin tooling. At the same time, hierarchy extraction is not guaranteed to be equally reliable across all long-form documents and PDF quality levels. Therefore, the design SHOULD include a bounded fallback grouping strategy when the hierarchy is missing, too shallow, or produces oversized or undersized parent sections. This preserves robustness without changing the canonical mental model: **parent-child remains structure-led, not window-led**.

### D2. Source of truth for hierarchy

**Decision:** Store canonical parent-child hierarchy in **PostgreSQL**, with denormalized retrieval fields in **Qdrant payload**.

**Rationale:**

The canonical parent-child hierarchy SHOULD be stored in PostgreSQL because PostgreSQL is the system of record for business entities, lifecycle, snapshot semantics, recovery, and auditability. Qdrant SHOULD remain the retrieval index, not the only place where structural knowledge exists. Keeping hierarchy only in Qdrant would weaken reproducibility, complicate reindex flows, and blur the architectural boundary between the storage of record and the search index. At the same time, the retrieval hot path MUST stay efficient. Therefore, the design SHOULD denormalize the minimum parent-related fields into the Qdrant payload so that retrieval and context expansion do not require unnecessary database round-trips for every user query. This gives ProxyMind a clean source-of-truth model without sacrificing online retrieval performance.

### D3. Retrieval context model

**Decision:** Retrieval SHOULD rank and return **child chunks**, while prompt assembly SHOULD include **child + parent**.

**Rationale:**

The retrieval layer SHOULD continue to rank and select child chunks as the primary relevance unit, but the LLM context SHOULD include both the matched child and its parent. Passing only the parent was rejected because it weakens precision and may blur the exact evidence that made the result relevant in the first place. Passing child + parent preserves the strongest part of flat retrieval — exact fragment grounding — while adding the broader section-level context needed for long-form documents such as books. Sibling expansion was considered but deferred: it may improve some long-range answers, yet it increases token pressure, context deduplication complexity, and scope. For S9-02, child + parent is the best value-for-complexity boundary and creates a clean foundation for future neighborhood expansion if evals later justify it.

### D4. Rollout scope

**Decision:** Enable parent-child chunking only for **long-form, book-like documents** in v1.

**Rationale:**

Parent-child chunking SHOULD be enabled only for long-form, book-like documents in the first version of S9-02. This matches the explicit scope of the story ("hierarchical indexing for books"), keeps the rollout focused, and avoids imposing hierarchical complexity on short or simple sources where flat chunking is already sufficient. Applying the feature to all Path B/C documents was rejected as unnecessary expansion of scope: it would increase ingestion and retrieval complexity without clear evidence of benefit across all document types. Manual opt-in via source metadata was also rejected for v1 because it shifts a system-level decision onto the owner, expands API/UI surface area, and violates YAGNI. The system SHOULD instead use explicit structural and length thresholds to decide whether a document qualifies as long-form. This preserves a deterministic pipeline, keeps the blast radius small, and makes A/B evaluation against flat chunking significantly cleaner.

## 3. Approach options considered

### Approach A — Minimal hierarchical overlay

Keep the current child chunking model as intact as possible and add a parent layer only for qualifying long-form documents.

- Existing `Chunk` remains the retrieval unit.
- Parent records and parent-child links are added during ingestion.
- Retrieval continues to search children only.
- Context assembly expands results with parent text.

**Pros:**

- lowest risk to the working retrieval pipeline
- easy A/B comparison against flat chunking
- limited blast radius
- fits story scope well

**Cons:**

- hierarchy starts as an overlay rather than a fully native model
- some logic remains conditional
- future multi-level expansion may need additional refactoring

### Approach B — Native hierarchical ingestion model

Make hierarchy a first-class output of the normalized chunking contract.

- Parsing/chunking produces parent and child structures explicitly.
- PostgreSQL persists hierarchy directly.
- Qdrant indexes children with parent metadata embedded in payload.
- Retrieval and prompt assembly operate on a canonical hierarchy model.

**Pros:**

- clean architecture
- better base for future hierarchy upgrades
- clearer domain boundaries

**Cons:**

- larger ingestion refactor
- higher implementation risk
- easier to overshoot the story scope

### Approach C — Retrieval-side synthetic parents

Do not persist parents as first-class records. Instead, reconstruct parent context dynamically from grouped children during retrieval.

**Pros:**

- fewer schema changes
- fast prototype path

**Cons:**

- weaker auditability and reproducibility
- more hot-path complexity
- conflicts with PostgreSQL-as-source-of-truth decision

### Recommended delivery strategy

Use **Approach A as the delivery strategy**, but model the data shape in a way that remains compatible with Approach B.

In practice, this means:

- implement S9-02 as an evolutionary overlay over the existing child-based ingestion and retrieval flow
- define hierarchy concepts with stable naming and explicit persistence from day one
- avoid synthetic hierarchy logic in retrieval

This is the best balance between low-risk delivery and clean future evolution.

## 4. Data model design

### Existing model constraints

Current `Chunk` records already carry:

- `snapshot_id`
- `source_id`
- `document_version_id`
- `chunk_index`
- `text_content`
- anchor metadata
- enrichment fields
- indexing status

This MUST remain backward-compatible for existing flat-chunk stories and retrieval behavior.

### Proposed hierarchy persistence model

Add explicit parent metadata and linkability at the PostgreSQL layer.

Two acceptable schema shapes were considered:

1. add parent fields directly to `chunks`
2. introduce a dedicated parent table and link children to it

**Recommended shape:** introduce a dedicated **parent section table** plus a foreign key from child chunks.

#### Why a dedicated parent table is preferred

A dedicated parent entity keeps responsibilities clear:

- child chunks remain the retrieval/index units
- parent sections represent context-expansion units
- repeated parent data does not need to be copied into every child row in PostgreSQL
- future debugging, evals, and admin inspection become simpler

### Proposed entities

#### `chunk_parents` (new table)

Represents the semantic parent section for one or more child chunks.

Suggested fields:

- `id`
- tenant-ready and knowledge-scope fields matching chunk ownership semantics
- `document_version_id`
- `snapshot_id`
- `source_id`
- `parent_index`
- `text_content`
- `token_count`
- `anchor_page`
- `anchor_chapter`
- `anchor_section`
- `anchor_timecode`
- `structure_label` or `heading_path` if needed for diagnostics
- timestamps

#### `chunks` (existing table, extended)

Add nullable linkage fields:

- `parent_id` → FK to `chunk_parents.id`
- optional `hierarchy_level` only if needed for diagnostics

For non-qualifying documents, `parent_id` remains null and the pipeline behaves as today.

### Snapshot semantics

Parent records MUST follow the same snapshot semantics as children.

That means:

- parent rows are draft-bound during ingestion
- publishing locks their snapshot association just like child rows
- rollback and active snapshot switching work through existing `snapshot_id` filters
- child-parent links MUST NOT cross snapshots

## 5. Ingestion design

### Placement in pipeline

Hierarchy extraction SHOULD happen after normalized parsing and before final persistence/indexing.

For qualifying Path B/C documents:

1. parse source into normalized blocks
2. derive structure-aware child chunks using the existing chunking approach
3. derive parent sections from the same normalized structure
4. link each child to exactly one parent
5. persist parents and children in PostgreSQL
6. embed and index children in Qdrant with parent metadata in payload

### Qualification decision

The ingestion pipeline SHOULD evaluate long-form eligibility before hierarchy construction.

Suggested gating signals:

- total parsed token count exceeds threshold
- estimated flat chunk count exceeds threshold
- optional structure signals, when available, such as repeated headings or section boundaries

Qualification SHOULD be primarily length- and scale-driven. Structure signals improve parent construction quality, but MUST NOT be required for a document to enter the bounded fallback grouping path.

If the source does not qualify, ingestion MUST continue with the existing flat chunking path unchanged.

### Parent construction algorithm

#### Primary strategy: structure-first

Parents SHOULD be formed from heading-bounded semantic sections.

Examples:

- chapter-level section in a book
- section-level block under a chapter
- top-level heading group in markdown or HTML manuscript

#### Fallback strategy: bounded grouping

If heading extraction is missing, too shallow, or yields sections outside acceptable size bounds:

- group adjacent child chunks into bounded parent sections
- ensure each parent stays within a configured token range
- preserve the best available anchor metadata from the grouped children

This fallback MUST be deterministic and SHOULD prefer stable grouping over clever heuristics.

### Parent-child mapping rules

- every qualifying child chunk MUST map to exactly one parent
- every persisted parent MUST have at least one child
- parent boundaries MUST NOT cross document-version boundaries
- parent boundaries MUST NOT cross snapshot boundaries
- child order within a parent SHOULD remain stable and reproducible

### Path coverage

- **Path B:** supported in scope
- **Path C:** supported in scope after normalized output
- **Path A:** explicitly out of scope

## 6. Qdrant payload and retrieval design

### Indexing model

Qdrant SHOULD continue indexing **children only**.

Parent sections SHOULD NOT become retrieval-ranked points in S9-02.

This preserves:

- current dense and sparse retrieval design
- existing ranking logic
- clean metric comparison against flat chunking

### Payload additions on child points

Each indexed child point SHOULD include denormalized parent metadata sufficient for online context expansion.

Suggested payload additions:

- `parent_id`
- `parent_text_content`
- `parent_token_count`
- `parent_anchor_page`
- `parent_anchor_chapter`
- `parent_anchor_section`
- `parent_anchor_timecode`
- optional `parent_index`

### Why payload denormalization is justified

The retrieval hot path SHOULD avoid per-result PostgreSQL lookups where possible. Since S9-02 expands context from parent after child retrieval, storing minimal parent context in payload keeps online behavior efficient while PostgreSQL remains the canonical store.

### Retrieval semantics

Retrieval behavior SHOULD remain conceptually simple:

1. rewrite query as today
2. perform dense + sparse hybrid search against child points only
3. rank children as today
4. deduplicate identical parents if multiple retrieved children map to the same parent
5. pass child + parent pairs to context assembly

### Deduplication rules

If multiple top-ranked children belong to the same parent:

- the system SHOULD keep each matched child as an individual grounding unit
- the shared parent SHOULD appear only once in the assembled prompt context
- ordering SHOULD favor the highest-ranked child first

This prevents token waste while preserving retrieval evidence.

## 7. Prompt and context assembly design

### Context unit

The prompt builder SHOULD treat each retrieved result as a **hierarchical context unit**:

- **child evidence**: precise fragment that matched retrieval
- **parent context**: larger semantic section around that fragment

### Recommended prompt ordering

For each retrieved unit:

1. parent section summary header or label
2. parent text
3. highlighted child evidence or labeled child text

However, the exact formatting MAY be tuned as long as both units are clearly separated and grounding remains obvious.

### Budget policy

Because parent context adds tokens, budget management MUST become hierarchy-aware.

Recommended policy order:

1. keep the matched child whenever possible
2. include full parent when budget allows
3. if needed, truncate parent before dropping child
4. preserve the global retrieval context budget contract already used by prompt assembly

### Citation policy

Citations SHOULD continue referencing the **child source fragment** and its existing anchor metadata.

Parent context exists to improve answer completeness, not to replace the precise citation target.

## 8. Error handling and fallback behavior

### Ingestion fallback

If hierarchy extraction fails for a document that would otherwise qualify:

- ingestion SHOULD fail closed only if the failure indicates corrupted normalized output or broken invariants
- otherwise, ingestion SHOULD log the hierarchy degradation and fall back to flat chunking for that document version

This is a real fallback because flat chunking is already a working production path.

### Required invariants

The pipeline MUST enforce:

- no child with dangling `parent_id`
- no parent without at least one child
- no cross-document parent-child links
- no cross-snapshot parent-child links
- deterministic ordering for repeated ingestion of the same source version

## 9. Testing and evaluation design

### Deploy tests

CI-safe tests SHOULD cover:

#### Unit tests

- parent construction from heading-rich input
- bounded fallback grouping from weakly structured input
- child-to-parent linking invariants
- prompt assembly with child + parent
- parent deduplication in assembled retrieval context

#### Integration tests

- Path B long-form markdown or HTML source produces parents and linked children
- Path C normalized output produces parents and linked children
- non-qualifying source remains flat
- retrieval returns matched child plus parent-enriched context object
- citations still point to child anchors

### Property-oriented checks

Property-based tests SHOULD be considered for hierarchy invariants, especially:

- every child has exactly one parent in qualifying documents
- parent grouping preserves child order
- repeated deterministic input yields stable parent-child mapping

### Evals

A/B evals SHOULD compare:

- flat chunking baseline
- parent-child chunking on long-form datasets

Primary metrics:

- Precision@K
- Recall@K
- MRR
- groundedness
- citation accuracy
- answer completeness on book-like questions

## 10. Operational and migration considerations

### Reindexing

S9-02 SHOULD require reindexing only for qualifying long-form documents whose Qdrant payload needs parent metadata.

The design SHOULD avoid unnecessary forced reindex for short sources that remain flat.

Both immediate embedding and Gemini Batch embedding flows MUST produce the same parent-aware Qdrant payload shape for qualifying documents. Batch mode is not a separate product behavior; it is an execution mode of the same ingestion contract.

### Backward compatibility

The system MUST remain compatible with:

- existing flat-chunk rows
- existing snapshots that do not contain hierarchy
- current chat flow for non-qualifying documents

### Observability

The ingestion pipeline SHOULD emit structured logs indicating:

- whether hierarchy was enabled for the document
- qualification decision and reason
- parent count
- child count
- fallback strategy usage

This is important for validating rollout quality and debugging poor retrieval behavior.

## 11. Open implementation defaults to define in the plan

The implementation plan SHOULD pin concrete defaults for:

- minimum long-form token threshold
- minimum flat chunk count threshold
- parent target token range
- parent max token cap before forced fallback grouping
- prompt budget policy for parent truncation
- exact Qdrant payload shape for parent fields
- exact schema shape and naming for the parent table

These are implementation details, not unresolved product ambiguities.

## 12. Final recommendation

ProxyMind SHOULD implement S9-02 as a **low-risk hierarchical overlay for long-form, book-like Path B/C documents**, with the following final shape:

- structure-first parent construction
- bounded fallback grouping when structure is weak
- PostgreSQL as canonical hierarchy store
- Qdrant indexing children only
- child payload enriched with parent metadata
- retrieval by child
- prompt context assembled from child + parent
- citations remaining child-grounded

This design gives the project the retrieval and answer-quality benefits expected from hierarchical indexing without destabilizing the working flat pipeline or expanding scope beyond the story.
