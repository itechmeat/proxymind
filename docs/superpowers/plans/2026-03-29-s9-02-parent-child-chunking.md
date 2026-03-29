# S9-02 Parent-Child Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structure-first parent-child chunking for qualifying long-form, book-like Path B/Path C documents so retrieval continues to rank child chunks while prompt assembly receives child + parent context.

**Architecture:** The implementation keeps the current child-centric ingestion and retrieval pipeline as the stable base, then layers in a persisted parent-section model for qualifying long-form documents. PostgreSQL becomes the canonical store for parent-child links, while Qdrant child payloads carry denormalized parent metadata so online retrieval and prompt assembly stay fast. Qualification is length-driven first; heading structure improves grouping quality but weakly structured long-form documents MUST still be able to use bounded fallback grouping.

**Tech Stack:** Python, FastAPI services, SQLAlchemy 2.x, Alembic, Qdrant, pytest, Docker Compose, Gemini Batch API, property-based testing (recommended for hierarchy invariants)

---

## File map

### Create
- `backend/app/services/chunk_hierarchy.py` — hierarchy qualification, structure-first parent building, bounded fallback grouping, child-to-parent mapping, qualification reason output
- `backend/tests/unit/services/test_chunk_hierarchy.py` — unit tests for qualification, structure grouping, weak-structure fallback grouping, and stable mapping invariants
- `backend/migrations/versions/<timestamp>_add_chunk_parents_for_s9_02.py` — Alembic migration for new parent table and `chunks.parent_id`

### Modify
- `backend/app/db/models/knowledge.py` — add `ChunkParent` model and `Chunk.parent_id`
- `backend/app/db/models/__init__.py` — export new model
- `backend/app/core/config.py` — add long-form thresholds and parent token bounds
- `backend/app/services/qdrant.py` — extend payload and `RetrievedChunk` with parent metadata
- `backend/app/services/retrieval.py` — preserve child ranking while returning hierarchy-aware results
- `backend/app/services/prompt.py` — add hierarchy-aware context formatting helpers
- `backend/app/services/context_assembler.py` — deduplicate shared parents, budget child + parent units, preserve child-grounded citations
- `backend/app/workers/tasks/handlers/path_b.py` — build/persist parents for qualifying documents, log qualification decisions, and enrich Qdrant payload inputs
- `backend/app/workers/tasks/handlers/path_c.py` — same as Path B after normalized parsing
- `backend/app/workers/tasks/pipeline.py` — accept parent-aware chunk rows when embedding/indexing in immediate and batch submission modes
- `backend/app/workers/tasks/batch_embed.py` — preserve child-based embedding submission while carrying the parent-aware ingestion contract through Gemini Batch mode
- `backend/app/services/batch_orchestrator.py` — rebuild parent-aware `QdrantChunkPoint` payloads from PostgreSQL during batch completion
- `backend/tests/unit/test_retrieval_service.py` — retrieval tests for hierarchy-aware results
- `backend/tests/unit/test_context_assembler.py` — prompt assembly tests for child + parent and parent deduplication
- `backend/tests/unit/services/test_qdrant.py` — payload tests for parent fields
- `backend/tests/integration/test_ingestion_worker.py` — end-to-end Path B hierarchy ingestion and observability tests
- `backend/tests/integration/test_path_c_ingestion.py` — end-to-end Path C hierarchy ingestion tests
- `backend/tests/integration/test_qdrant_roundtrip.py` — roundtrip test for parent-aware payload fields
- `backend/tests/unit/services/test_batch_orchestrator.py` — regression tests for batch completion payload parity
- `backend/tests/unit/workers/test_batch_embed.py` — regression tests for batch submission text/payload parity
- `docs/architecture.md` — mention parent-section persistence and child + parent context expansion
- `docs/rag.md` — update parent-child section from future concept to delivered story behavior
- `docs/plan.md` — mark story done only after implementation is verified and archived later, not during apply

---

## Commit policy for this plan

This repository forbids commits without explicit user permission. Therefore every “commit” step below is **optional** and MUST be skipped unless the user explicitly asks for a commit in the implementation session.

Use this exact wording at those checkpoints:

```text
Optional commit checkpoint. Skip by default. Only run git add/git commit if the user explicitly authorizes committing.
```

---

### Task 1: Add persistence model for parent sections

**Files:**
- Create: `backend/migrations/versions/<timestamp>_add_chunk_parents_for_s9_02.py`
- Modify: `backend/app/db/models/knowledge.py`
- Modify: `backend/app/db/models/__init__.py`
- Test: `backend/tests/integration/test_ingestion_worker.py`

- [ ] **Step 1: Write the failing integration assertion for parent persistence**

Add a new ingestion worker test that describes the target storage shape:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_persists_chunk_parents_for_long_markdown(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=SourceType.MARKDOWN,
        filename="book.md",
        title="Book source",
    )
    worker_ctx = _real_parser_worker_context(
        session_factory,
        file_bytes=_fixture_bytes("book_long.md"),
    )
    worker_ctx["settings"] = SimpleNamespace(
        bm25_language="english",
        parent_child_min_document_tokens=100,
        parent_child_min_flat_chunks=3,
        parent_child_parent_target_tokens=400,
        parent_child_parent_max_tokens=700,
    )

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        parents = (await session.scalars(select(ChunkParent).order_by(ChunkParent.parent_index.asc()))).all()
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert parents
    assert all(chunk.parent_id is not None for chunk in chunks)
    assert {chunk.parent_id for chunk in chunks} <= {parent.id for parent in parents}
```

- [ ] **Step 2: Run the new test to confirm the model is missing**

Run:
```bash
docker compose exec api python -m pytest tests/integration/test_ingestion_worker.py::test_worker_persists_chunk_parents_for_long_markdown -v
```
Expected: FAIL with import, model, or missing-column errors for `ChunkParent` / `parent_id`.

- [ ] **Step 3: Add the SQLAlchemy model and relationship fields**

Implement the parent entity in `backend/app/db/models/knowledge.py`:

```python
class ChunkParent(PrimaryKeyMixin, TenantMixin, KnowledgeScopeMixin, TimestampMixin, Base):
    __tablename__ = "chunk_parents"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "parent_index",
            name="uq_chunk_parents_document_version_id_parent_index",
        ),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id"), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    parent_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anchor_section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anchor_timecode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heading_path: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

class Chunk(...):
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunk_parents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
```

Export `ChunkParent` from `backend/app/db/models/__init__.py`.

- [ ] **Step 4: Add the Alembic migration**

Create the migration with explicit schema operations:

```python
def upgrade() -> None:
    op.create_table(
        "chunk_parents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_index", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("anchor_page", sa.Integer(), nullable=True),
        sa.Column("anchor_chapter", sa.String(length=255), nullable=True),
        sa.Column("anchor_section", sa.String(length=255), nullable=True),
        sa.Column("anchor_timecode", sa.String(length=64), nullable=True),
        sa.Column("heading_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_version_id", "parent_index", name="uq_chunk_parents_document_version_id_parent_index"),
    )
    op.add_column("chunks", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_chunks_parent_id_chunk_parents", "chunks", "chunk_parents", ["parent_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_chunks_parent_id", "chunks", ["parent_id"])
```

- [ ] **Step 5: Run migration and the targeted integration test**

Run:
```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m pytest tests/integration/test_ingestion_worker.py::test_worker_persists_chunk_parents_for_long_markdown -v
```
Expected: migration succeeds; test still fails later because hierarchy construction is not implemented yet.

- [ ] **Step 6: Optional commit checkpoint**

Optional commit checkpoint. Skip by default. Only run `git add` / `git commit` if the user explicitly authorizes committing.

---

### Task 2: Build hierarchy qualification, fallback grouping, and observability output

**Files:**
- Create: `backend/app/services/chunk_hierarchy.py`
- Test: `backend/tests/unit/services/test_chunk_hierarchy.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Write failing unit tests for qualification, fallback, and reasons**

Create tests for the three core behaviors:

```python
def test_qualifies_long_form_without_heading_structure_when_large_enough() -> None:
    builder = ChunkHierarchyBuilder(
        min_document_tokens=100,
        min_flat_chunks=3,
        parent_target_tokens=200,
        parent_max_tokens=350,
    )
    chunks = [_chunk("x " * 60, i, None, None) for i in range(3)]

    decision = builder.qualify(chunks)

    assert decision.qualifies is True
    assert decision.reason == "long_form_fallback"


def test_build_prefers_structure_boundaries_when_present() -> None:
    builder = ChunkHierarchyBuilder(...)
    chunks = [
        _chunk("a " * 60, 0, "Chapter 1", "Section A"),
        _chunk("b " * 60, 1, "Chapter 1", "Section A"),
        _chunk("c " * 60, 2, "Chapter 2", "Section B"),
    ]

    hierarchy = builder.build(chunks)

    assert len(hierarchy.parents) == 2
    assert [child.parent_index for child in hierarchy.children] == [0, 0, 1]


def test_build_uses_bounded_fallback_grouping_when_structure_missing() -> None:
    builder = ChunkHierarchyBuilder(...)
    chunks = [_chunk("x " * 80, i, None, None) for i in range(4)]

    hierarchy = builder.build(chunks)

    assert len(hierarchy.parents) >= 2
    assert all(parent.token_count <= 350 for parent in hierarchy.parents)
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run:
```bash
docker compose exec api python -m pytest tests/unit/services/test_chunk_hierarchy.py -v
```
Expected: FAIL because `ChunkHierarchyBuilder` and qualification result types do not exist.

- [ ] **Step 3: Implement the hierarchy service**

Create `backend/app/services/chunk_hierarchy.py` with focused dataclasses and deterministic logic:

```python
@dataclass(slots=True, frozen=True)
class HierarchyDecision:
    qualifies: bool
    reason: str
    has_structure: bool
    total_tokens: int
    chunk_count: int

@dataclass(slots=True, frozen=True)
class ParentChunkData:
    parent_index: int
    text_content: str
    token_count: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None
    heading_path: tuple[str, ...]

@dataclass(slots=True, frozen=True)
class ChildChunkLink:
    chunk_index: int
    parent_index: int

@dataclass(slots=True, frozen=True)
class ChunkHierarchy:
    parents: list[ParentChunkData]
    children: list[ChildChunkLink]
    decision: HierarchyDecision
```

Qualification MUST be length-driven first, not structure-gated:

```python
def qualify(self, chunks: list[ChunkData]) -> HierarchyDecision:
    total_tokens = sum(chunk.token_count for chunk in chunks)
    chunk_count = len(chunks)
    has_structure = any(chunk.anchor_chapter or chunk.anchor_section for chunk in chunks)
    if total_tokens < self._min_document_tokens or chunk_count < self._min_flat_chunks:
        return HierarchyDecision(False, "below_long_form_threshold", has_structure, total_tokens, chunk_count)
    if has_structure:
        return HierarchyDecision(True, "long_form_structure_first", has_structure, total_tokens, chunk_count)
    return HierarchyDecision(True, "long_form_fallback", has_structure, total_tokens, chunk_count)
```

Then implement:
- structure-first grouping by stable `(anchor_chapter, anchor_section)` boundaries
- bounded fallback grouping by cumulative token budget when structure is missing or sections exceed bounds
- deterministic child-to-parent mapping

- [ ] **Step 4: Add config settings for thresholds**

Extend settings in `backend/app/core/config.py`:

```python
parent_child_min_document_tokens: int = 1500
parent_child_min_flat_chunks: int = 6
parent_child_parent_target_tokens: int = 1200
parent_child_parent_max_tokens: int = 1800
```

- [ ] **Step 5: Run the hierarchy unit tests**

Run:
```bash
docker compose exec api python -m pytest tests/unit/services/test_chunk_hierarchy.py -v
```
Expected: PASS.

- [ ] **Step 6: Optional commit checkpoint**

Optional commit checkpoint. Skip by default. Only run `git add` / `git commit` if the user explicitly authorizes committing.

---

### Task 3: Persist parent rows during Path B and Path C ingestion and log decisions

**Files:**
- Modify: `backend/app/workers/tasks/handlers/path_b.py`
- Modify: `backend/app/workers/tasks/handlers/path_c.py`
- Test: `backend/tests/integration/test_ingestion_worker.py`
- Test: `backend/tests/integration/test_path_c_ingestion.py`

- [ ] **Step 1: Extend integration tests for Path B and Path C hierarchy behavior**

Add one Path B and one Path C test that assert:

```python
assert parents
assert all(chunk.parent_id is not None for chunk in chunks)
assert len({chunk.parent_id for chunk in chunks}) < len(chunks)
assert all(parent.snapshot_id == chunks[0].snapshot_id for parent in parents)
```

Add a weak-structure long-form test. Capture structured logs and assert the fallback reason through the emitted observability event:

```python
assert parents
assert all(chunk.parent_id is not None for chunk in chunks)
assert any(
    record["event"] == "worker.ingestion.parent_child_decision"
    and record["reason"] == "long_form_fallback"
    for record in captured_logs
)
```

Add a short-source negative test:

```python
assert parents == []
assert all(chunk.parent_id is None for chunk in chunks)
```

- [ ] **Step 2: Run the ingestion tests to confirm failure**

Run:
```bash
docker compose exec api python -m pytest tests/integration/test_ingestion_worker.py tests/integration/test_path_c_ingestion.py -v
```
Expected: FAIL because no parent rows or hierarchy logs are produced yet.

- [ ] **Step 3: Wire hierarchy building into Path B and Path C**

In both handlers, after `chunk_data` is produced and before child rows are created, build hierarchy for qualifying documents:

```python
hierarchy_builder = ChunkHierarchyBuilder.from_settings(services.settings)
decision = hierarchy_builder.qualify(chunk_data)
hierarchy = hierarchy_builder.build(chunk_data) if decision.qualifies else None
```

Persist parents and assign `parent_id` on child rows:

```python
parent_rows = []
parent_id_by_index: dict[int, uuid.UUID] = {}
if hierarchy is not None:
    for parent in hierarchy.parents:
        parent_id = uuid.uuid7()
        parent_rows.append(
            ChunkParent(
                id=parent_id,
                owner_id=source.owner_id,
                agent_id=source.agent_id,
                knowledge_base_id=source.knowledge_base_id,
                document_version_id=document_version.id,
                snapshot_id=snapshot_id,
                source_id=source.id,
                parent_index=parent.parent_index,
                text_content=parent.text_content,
                token_count=parent.token_count,
                anchor_page=parent.anchor_page,
                anchor_chapter=parent.anchor_chapter,
                anchor_section=parent.anchor_section,
                anchor_timecode=parent.anchor_timecode,
                heading_path=list(parent.heading_path) or None,
            )
        )
        parent_id_by_index[parent.parent_index] = parent_id
    session.add_all(parent_rows)
```

- [ ] **Step 4: Add required structured logging for rollout visibility**

Emit a structured log entry in both handlers:

```python
logger.info(
    "worker.ingestion.parent_child_decision",
    source_id=str(source.id),
    processing_path=ProcessingPath.PATH_B.value,
    qualifies=decision.qualifies,
    reason=decision.reason,
    total_tokens=decision.total_tokens,
    chunk_count=decision.chunk_count,
    has_structure=decision.has_structure,
    parent_count=len(hierarchy.parents) if hierarchy is not None else 0,
    fallback_used=(decision.reason == "long_form_fallback"),
)
```

- [ ] **Step 5: Keep flat ingestion unchanged for non-qualifying documents**

Use the explicit conditional branch:

```python
parent_id = None
if hierarchy is not None:
    parent_index = child_parent_index_by_chunk_index[chunk.chunk_index]
    parent_id = parent_id_by_index[parent_index]
```

Do not change chunk ordering, indexing order, or snapshot logic for short documents.

- [ ] **Step 6: Run the ingestion integration suite**

Run:
```bash
docker compose exec api python -m pytest tests/integration/test_ingestion_worker.py tests/integration/test_path_c_ingestion.py -v
```
Expected: PASS.

- [ ] **Step 7: Optional commit checkpoint**

Optional commit checkpoint. Skip by default. Only run `git add` / `git commit` if the user explicitly authorizes committing.

---

### Task 4: Extend immediate and batch embedding flows with parent-aware payloads

**Files:**
- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/app/workers/tasks/batch_embed.py`
- Modify: `backend/app/services/batch_orchestrator.py`
- Modify: `backend/app/services/qdrant.py`
- Test: `backend/tests/unit/services/test_qdrant.py`
- Test: `backend/tests/unit/test_retrieval_service.py`
- Test: `backend/tests/integration/test_qdrant_roundtrip.py`
- Test: `backend/tests/unit/services/test_batch_orchestrator.py`
- Test: `backend/tests/unit/workers/test_batch_embed.py`

- [ ] **Step 1: Write failing tests for parent-aware payload shape in both execution modes**

Add payload-focused tests that assert immediate indexing and batch completion both produce the same fields:

```python
def test_build_payload_includes_parent_fields() -> None:
    point = replace(
        _point(...),
        parent_id=uuid.uuid4(),
        parent_text_content="parent text",
        parent_token_count=90,
        parent_anchor_chapter="Chapter 1",
        parent_anchor_section="Section A",
    )

    payload = QdrantService._build_payload(point)

    assert payload["parent_text_content"] == "parent text"
    assert payload["parent_anchor_section"] == "Section A"
```

Add a batch-path regression test that mocks pending chunks with `parent_id` and asserts batch completion upserts points containing parent payload fields.

- [ ] **Step 2: Run the unit and integration tests to confirm failure**

Run:
```bash
docker compose exec api python -m pytest \
  tests/unit/services/test_qdrant.py \
  tests/unit/services/test_batch_orchestrator.py \
  tests/unit/workers/test_batch_embed.py \
  tests/unit/test_retrieval_service.py \
  tests/integration/test_qdrant_roundtrip.py -v
```
Expected: FAIL because the fields are missing from dataclasses, payload mapping, batch submission wiring, or batch completion.

- [ ] **Step 3: Extend Qdrant dataclasses and payload mapping**

Update `QdrantChunkPoint` and `RetrievedChunk`:

```python
@dataclass(slots=True, frozen=True)
class QdrantChunkPoint:
    ...
    parent_id: UUID | None = None
    parent_text_content: str | None = None
    parent_token_count: int | None = None
    parent_anchor_page: int | None = None
    parent_anchor_chapter: str | None = None
    parent_anchor_section: str | None = None
    parent_anchor_timecode: str | None = None

@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    ...
    parent_id: UUID | None = None
    parent_text_content: str | None = None
    parent_token_count: int | None = None
    parent_anchor_metadata: dict[str, int | str | None] | None = None
```

Map the fields in `_build_payload()` and `_to_retrieved_chunk()`.

- [ ] **Step 4: Keep immediate and batch embedding text selection consistent**

In `pipeline.py`, when building `texts_for_embedding`, continue to use:
- `chunk.enriched_text` when enrichment exists
- otherwise `chunk.text_content`

Do **not** replace child embedding text with parent text. Parent metadata affects retrieval payload and prompt context, not embedding rank semantics.

In `batch_embed.py` and `batch_orchestrator.py`, ensure the same text source and parent-aware payload reconstruction are used during Gemini Batch submission and completion.

- [ ] **Step 5: Keep hybrid search semantics child-only**

Do not change `dense_search()`, `hybrid_search()`, or `keyword_search()` ranking inputs. Only extend returned metadata and payload shape.

- [ ] **Step 6: Run the Qdrant, retrieval, and batch-aware tests**

Run:
```bash
docker compose exec api python -m pytest \
  tests/unit/services/test_qdrant.py \
  tests/unit/services/test_batch_orchestrator.py \
  tests/unit/workers/test_batch_embed.py \
  tests/unit/test_retrieval_service.py \
  tests/integration/test_qdrant_roundtrip.py -v
```
Expected: PASS.

- [ ] **Step 7: Optional commit checkpoint**

Optional commit checkpoint. Skip by default. Only run `git add` / `git commit` if the user explicitly authorizes committing.

---

### Task 5: Assemble hierarchy-aware prompt context with parent deduplication

**Files:**
- Modify: `backend/app/services/prompt.py`
- Modify: `backend/app/services/context_assembler.py`
- Test: `backend/tests/unit/test_context_assembler.py`

- [ ] **Step 1: Write failing prompt assembly tests**

Add tests for the intended behavior:

```python
def test_knowledge_context_includes_child_and_parent() -> None:
    chunk = replace(
        _chunk("child text"),
        parent_id=uuid.uuid4(),
        parent_text_content="parent text",
        parent_anchor_metadata={
            "anchor_page": 10,
            "anchor_chapter": "Chapter 1",
            "anchor_section": "Section A",
            "anchor_timecode": None,
        },
    )

    result = _assembler().assemble(
        chunks=[chunk],
        query="Q?",
        source_map={chunk.source_id: _source_info(chunk.source_id)},
    )

    assert "parent text" in result.messages[1]["content"]
    assert "child text" in result.messages[1]["content"]


def test_shared_parent_is_deduplicated_across_multiple_children() -> None:
    parent_id = uuid.uuid4()
    first = replace(_chunk("child one"), parent_id=parent_id, parent_text_content="shared parent", parent_anchor_metadata={"anchor_page": 10, "anchor_chapter": "Chapter 1", "anchor_section": "Section A", "anchor_timecode": None})
    second = replace(_chunk("child two"), parent_id=parent_id, parent_text_content="shared parent", parent_anchor_metadata={"anchor_page": 10, "anchor_chapter": "Chapter 1", "anchor_section": "Section A", "anchor_timecode": None})

    result = _assembler().assemble(chunks=[first, second], query="Q?", source_map={})

    assert result.messages[1]["content"].count("shared parent") == 1
```

- [ ] **Step 2: Run the context assembler tests to verify failure**

Run:
```bash
docker compose exec api python -m pytest tests/unit/test_context_assembler.py -v
```
Expected: FAIL because the current assembler only knows flat chunk text.

- [ ] **Step 3: Add hierarchy-aware formatting helpers**

In `backend/app/services/prompt.py`, add helpers such as:

```python
def format_parent_header(index: int, chunk: RetrievedChunk, source_map: dict[uuid.UUID, SourceInfo]) -> str:
    ...

def format_hierarchy_context(index: int, chunk: RetrievedChunk, source_map: dict[uuid.UUID, SourceInfo], *, include_parent: bool) -> str:
    if not chunk.parent_text_content or not include_parent:
        return f"{format_chunk_header(index, chunk, source_map)}\n{chunk.text_content}"
    return "\n".join([
        format_parent_header(index, chunk, source_map),
        chunk.parent_text_content,
        "",
        f"Matched excerpt: {format_chunk_header(index, chunk, source_map)}",
        chunk.text_content,
    ])
```

- [ ] **Step 4: Update `ContextAssembler` selection and rendering**

Change `_select_chunks()` and `_build_knowledge_context()` so that:
- token budgeting measures `child + parent` as one unit
- shared parent text is emitted once
- child evidence is always preserved when included

Use a parent-aware seen set:

```python
seen_parent_ids: set[uuid.UUID] = set()
if chunk.parent_id and chunk.parent_id in seen_parent_ids:
    include_parent = False
else:
    include_parent = True
    if chunk.parent_id:
        seen_parent_ids.add(chunk.parent_id)
```

- [ ] **Step 5: Run the context assembler unit tests**

Run:
```bash
docker compose exec api python -m pytest tests/unit/test_context_assembler.py -v
```
Expected: PASS.

- [ ] **Step 6: Optional commit checkpoint**

Optional commit checkpoint. Skip by default. Only run `git add` / `git commit` if the user explicitly authorizes committing.

---

### Task 6: Verify observability, end-to-end behavior, and update docs

**Files:**
- Modify: `docs/rag.md`
- Modify: `docs/architecture.md`
- Optional modify after verification only: `docs/plan.md` during archive, not now
- Test: `backend/tests/integration/test_qdrant_roundtrip.py`
- Test: `backend/tests/integration/test_ingestion_worker.py`
- Test: `backend/tests/unit/services/test_chunk_hierarchy.py`
- Test: `backend/tests/unit/test_context_assembler.py`
- Test: `backend/tests/unit/test_retrieval_service.py`
- Test: `backend/tests/unit/services/test_qdrant.py`

- [ ] **Step 1: Add an observability assertion for qualification logs**

In ingestion integration tests, capture logs and assert the new event is emitted:

```python
assert any(
    record["event"] == "worker.ingestion.parent_child_decision"
    and record["reason"] in {"below_long_form_threshold", "long_form_structure_first", "long_form_fallback"}
    for record in captured_logs
)
```

- [ ] **Step 2: Add a Qdrant roundtrip test for parent metadata**

Add an integration test that indexes a child point with parent payload and asserts retrieval returns it intact:

```python
assert response[0].parent_text_content == "Chapter 1 full section"
assert response[0].parent_anchor_metadata["anchor_section"] == "Section A"
```

- [ ] **Step 3: Run the focused verification suite**

Run:
```bash
docker compose exec api python -m pytest \
  tests/unit/services/test_chunk_hierarchy.py \
  tests/unit/services/test_qdrant.py \
  tests/unit/services/test_batch_orchestrator.py \
  tests/unit/workers/test_batch_embed.py \
  tests/unit/test_retrieval_service.py \
  tests/unit/test_context_assembler.py \
  tests/integration/test_ingestion_worker.py \
  tests/integration/test_path_c_ingestion.py \
  tests/integration/test_qdrant_roundtrip.py -v
```
Expected: PASS.

- [ ] **Step 4: Run the broader backend CI test command used by the repo**

Run the backend CI command in Docker. If the repo uses a Make target or scripted test target, use that. Otherwise use:

```bash
docker compose exec api python -m pytest tests/unit tests/integration -v
```
Expected: PASS.

- [ ] **Step 5: Update the canonical docs**

Update `docs/rag.md`:

```md
## Parent-child chunking

Delivered in S9-02 for qualifying long-form Path B/C documents, including weakly structured long-form documents that enter the bounded fallback grouping path.
Retrieval ranks child chunks; prompt assembly receives child + parent context.
Canonical hierarchy is stored in PostgreSQL; child payloads in Qdrant carry parent metadata in both immediate and batch embedding flows.
```

Update `docs/architecture.md` to mention:
- `chunk_parents` persisted in PostgreSQL
- child-only search with parent-assisted context expansion
- qualification/fallback logging for rollout visibility

- [ ] **Step 6: Re-read `docs/development.md` and self-review**

Checklist for the implementer before claiming completion:
- confirm the change stayed scoped to S9-02
- confirm no mocks leaked outside `tests/`
- confirm flat chunking remains a real fallback for non-qualifying documents
- confirm weakly structured long-form documents can still use bounded fallback grouping
- confirm immediate and batch embedding paths produce the same parent-aware payload contract
- confirm qualification decision logging is present and tested

- [ ] **Step 7: Optional commit checkpoint**

Optional commit checkpoint. Skip by default. Only run `git add` / `git commit` if the user explicitly authorizes committing.

---

## Self-review

### Spec coverage
- Scope limited to long-form Path B/C documents: covered in Tasks 2 and 3
- Weakly structured long-form fallback grouping: covered in Tasks 2 and 3
- PostgreSQL as source of truth: covered in Tasks 1 and 3
- Qdrant child-only retrieval with parent metadata: covered in Task 4
- Immediate and batch embedding parity, including existing batch-specific test suites: covered in Task 4
- Prompt receives child + parent: covered in Task 5
- Parent deduplication and budget handling: covered in Task 5
- Observability requirements: covered in Tasks 3 and 6
- CI/integration verification and docs: covered in Task 6

### Placeholder scan
- No `TODO`, `TBD`, or “implement later” placeholders remain in task instructions.
- All code-touching steps include concrete file paths and concrete code shapes.
- All verification steps include exact commands.

### Type consistency
- Parent table is consistently named `ChunkParent` / `chunk_parents`.
- Child link field is consistently named `parent_id`.
- Hierarchy builder is consistently named `ChunkHierarchyBuilder`.
- Qualification output is consistently named `HierarchyDecision`.
- Retrieval remains child-based through `RetrievedChunk` with additional parent metadata.

## Notes for the implementer
- All backend execution, migrations, and tests MUST run inside Docker containers per project policy.
- No waiting period may exceed 5 minutes; if a command runs longer, investigate and report before continuing.
- Do not mark `docs/plan.md` story checkbox until archive time.
- Do not commit unless explicitly authorized by the user in the implementation session.
