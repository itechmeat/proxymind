## Story

**S9-03: BGE-M3 fallback** — Phase 9: RAG Upgrades (based on eval results).

Verification criteria from plan: eval on the target language shows improved retrieval metrics versus BM25.

Acceptance rule for this change: compare the same target-language retrieval suite across two explicit runs — BM25 baseline first, then BGE-M3 after reindex — and use `Precision@5`, `Precision@10`, `Recall@5`, `Recall@10`, and `MRR@10` as the decision metrics. `MRR@10` is the primary metric and MUST improve by at least `0.05` absolute or `10%` relative versus BM25. In addition, at least three of the four Precision/Recall metrics MUST be non-decreasing, and no metric may regress by more than `0.02` absolute. If metrics conflict, `MRR@10` wins, and the tie-breaker is whether the majority of Precision/Recall metrics improved while preserving the sparse backend hybrid-retrieval contract.

Stable behavior requiring test coverage: sparse backend selection, provider-aware Qdrant schema lifecycle, indexing via the active sparse backend, hybrid retrieval contract stability, explicit reindex requirement, keyword-search diagnostics, and language-specific eval dataset compatibility.

## Why

Qdrant BM25 works well enough as the default sparse retriever for English-first installations, but it is not guaranteed to perform well across all configured languages. The project already documents BGE-M3 as the fallback path for languages where BM25 quality is insufficient; this change is needed now because S8-02 established eval-driven upgrades as the mechanism for deciding which Phase 9 retrieval improvement should be applied.

Without an explicit sparse backend switch, the current system cannot promote a language-specific sparse upgrade without mixing incompatible index states or redesigning the retrieval stack. This story closes that gap while keeping Gemini dense retrieval unchanged.

## What Changes

- Add installation-level sparse backend selection: `bm25` or `bge_m3`
- Introduce a narrow sparse-provider abstraction so indexing and retrieval can use the active sparse backend without changing the surrounding hybrid retrieval contract
- Make Qdrant schema lifecycle provider-aware and treat sparse backend changes as explicit index contract changes
- Require explicit reindexing when switching the sparse backend. In S9-03 this migration is manual, not automatic: operators update `SPARSE_BACKEND`, rebuild the index through the existing Admin API ingestion flow, monitor background-task completion, and only then publish/activate the rebuilt snapshot. Single-environment switches may incur downtime because sparse-slot collection settings can change; the preferred zero-downtime path is blue/green rollout. During rebuild, production queries continue to use the previously active snapshot only until the operator flips configuration and starts the new rebuild. Rollback is the inverse checklist: restore `SPARSE_BACKEND=bm25`, rebuild, verify diagnostics/evals, and keep the prior active snapshot until the replacement baseline is healthy.
- Preserve Gemini dense embeddings, child-first retrieval, RRF fusion, and existing context assembly behavior
- Extend admin keyword-search diagnostics with active sparse backend metadata
- Add a language-specific eval dataset in the current eval-suite format and document the actual comparison workflow as two separate runs (BM25 baseline, then BGE-M3 after reindex)
- Make the acceptance decision explicit: compare `Precision@5`, `Precision@10`, `Recall@5`, `Recall@10`, and `MRR@10` between the two runs on the same target-language suite

## Capabilities

### New Capabilities

- None

### Modified Capabilities

- `vector-storage`: sparse indexing becomes provider-aware, carries explicit sparse backend metadata, and rejects incompatible index contracts when the sparse backend changes
- `hybrid-retrieval`: the sparse leg becomes installation-selectable while Gemini dense retrieval and RRF fusion remain unchanged
- `ingestion-pipeline`: chunk indexing uses the active sparse backend while preserving current enriched-text selection rules
- `bm25-keyword-search`: keyword diagnostics expose active sparse backend metadata rather than assuming BM25-only behavior

## Impact

- **Backend code:** sparse provider integration, Qdrant service, retrieval service, ingestion pipeline, startup wiring, admin diagnostics, and tests
- **APIs:** admin keyword-search response adds sparse backend metadata for diagnostics
- **Data/indexing:** sparse backend switch becomes an explicit reindex-triggering index contract change
- **Eval tooling:** new dataset file in the current suite format and documented two-run comparison workflow
- **Dependencies:** no new local ML runtime in backend containers; BGE-M3 remains an external sparse provider concern

Operator checklist for sparse backend migration:

- pre-check: capture the BM25 baseline report on the target suite and verify the current active snapshot id
- config change: set `SPARSE_BACKEND=bge_m3` and `BGE_M3_PROVIDER_URL=<service_endpoint_url>`
- rebuild: recreate the target draft snapshot and re-ingest the corpus through the existing Admin API upload/task flow
- monitor: poll `GET /api/admin/tasks/{task_id}`, watch API/worker logs, and verify diagnostics after startup
- rollback: if BGE-M3 underperforms or the rebuild fails, restore BM25 config, rebuild, and keep the old active snapshot in service until the replacement index is healthy
