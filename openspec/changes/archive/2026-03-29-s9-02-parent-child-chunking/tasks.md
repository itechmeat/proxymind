## 1. Persistence and hierarchy core

- [x] 1.1 Add additive database support for `chunk_parents` and `chunks.parent_id`
- [x] 1.2 Implement the hierarchy qualification/builder service with structure-first grouping and deterministic bounded fallback grouping
- [x] 1.3 Add deterministic unit tests for long-form qualification, weak-structure fallback, parent sizing, and stable child-to-parent mapping

## 2. Ingestion pipeline integration

- [x] 2.1 Integrate hierarchy qualification and parent persistence into Path B ingestion
- [x] 2.2 Integrate hierarchy qualification and parent persistence into Path C ingestion
- [x] 2.3 Keep non-qualifying documents on the flat ingestion path with no parent rows or links
- [x] 2.4 Emit structured hierarchy decision logs for qualifying, fallback, and flat cases
- [x] 2.5 Fail the ingestion run when a qualifying document cannot complete hierarchy construction or parent persistence
- [x] 2.6 Add integration tests covering Path B, Path C, weak-structure fallback, qualifying-failure behavior, and flat fallback behavior

## 3. Vector storage and batch parity

- [x] 3.1 Extend Qdrant child payloads and retrieval result models with parent metadata
- [x] 3.2 Keep immediate embedding child-based while attaching parent-aware payload fields during upsert
- [x] 3.3 Update Gemini Batch submission/completion so batch mode preserves the same parent-aware child payload contract
- [x] 3.4 Add regression tests for Qdrant payload shape, retrieval metadata, batch submission, and batch completion parity

## 4. Context assembly

- [x] 4.1 Add hierarchy-aware prompt formatting helpers for child evidence plus parent context
- [x] 4.2 Update `ContextAssembler` to deduplicate shared parents and preserve child evidence under budget pressure
- [x] 4.3 Add unit tests for child + parent prompt units, shared-parent deduplication, and flat-chunk backward compatibility

## 5. Verification and documentation

- [x] 5.1 Update `docs/rag.md` and `docs/architecture.md` to reflect delivered parent-child behavior
- [x] 5.2 Run focused deterministic verification for hierarchy builder, ingestion, hierarchy decision observability, Qdrant payloads, batch parity, and context assembly
- [x] 5.3 Verify the hierarchy decision log contract explicitly in deterministic tests as part of the acceptance path
- [x] 5.4 Run the broader backend CI test suite in Docker and confirm it passes
- [x] 5.5 Re-read `docs/development.md` and self-review the implementation against the project standards before reporting completion
