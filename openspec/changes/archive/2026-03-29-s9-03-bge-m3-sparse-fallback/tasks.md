## 1. Configuration and sparse provider foundation

- [x] 1.1 Add installation-level sparse backend settings to `backend/app/core/config.py` and validate `bge_m3` provider connectivity requirements
- [x] 1.2 Create `backend/app/services/sparse_providers.py` with BM25 and external BGE-M3 provider implementations plus provider metadata and reindex helper logic
- [x] 1.3 Add deterministic unit tests for sparse backend config parsing, provider request shaping, provider metadata, and reindex requirement logic

## 2. Qdrant sparse contract and schema lifecycle

- [x] 2.1 Refactor `backend/app/services/qdrant.py` to accept the active sparse provider and route sparse document/query construction through it
- [x] 2.2 Make `ensure_collection()` explicitly validate the active sparse backend contract and fail on incompatible sparse index state
- [x] 2.3 Extend Qdrant payload construction to record `sparse_backend`, `sparse_model`, and `sparse_contract_version` on indexed child points
- [x] 2.4 Add unit and integration tests covering BM25 compatibility, BGE-M3 sparse construction, and explicit failure on sparse backend contract mismatch

## 3. Startup wiring and ingestion integration

- [x] 3.1 Add startup factory wiring in `backend/app/main.py` and `backend/app/workers/main.py` to build and inject the active sparse provider
- [x] 3.2 Keep `backend/app/services/retrieval.py` provider-agnostic while preserving the existing hybrid retrieval contract
- [x] 3.3 Keep sparse text selection in `backend/app/workers/tasks/pipeline.py` explicit and unchanged (`enriched_text` first, `text_content` fallback)
- [x] 3.4 Add unit tests for API/worker startup wiring, retrieval-service stability, and pipeline sparse text selection behavior

## 4. Keyword diagnostics and admin schema updates

- [x] 4.1 Extend `backend/app/api/schemas.py` so `KeywordSearchResponse` exposes `sparse_backend` and `sparse_model`
- [x] 4.2 Update `backend/app/api/admin.py` keyword-search diagnostics to return the active sparse backend metadata without changing snapshot defaulting behavior
- [x] 4.3 Add deterministic unit coverage for `keyword_search()` with BM25-backed sparse diagnostics
- [x] 4.4 Add deterministic unit coverage for `keyword_search()` with BGE-M3-backed sparse diagnostics
- [x] 4.5 Add deterministic unit coverage preserving retry semantics for transient sparse-query errors
- [x] 4.6 Add deterministic integration coverage for provider-aware keyword diagnostics

## 5. Eval dataset and comparison workflow

- [x] 5.1 Add `backend/evals/datasets/retrieval_bge_m3_russian.yaml` using the current eval-suite schema (`suite`, `snapshot_id`, `cases`, `expected`)
- [x] 5.2 Verify the new dataset loads through the existing runner entry point `python -m evals.run_evals`
- [x] 5.3 Document the two-run sparse comparison workflow in `docs/rag.md` and `docs/spec.md` if contract wording changes
- [x] 5.4 Deferred on 2026-03-29: live target-language eval comparison could not be executed because the runtime environment did not provide `ADMIN_API_KEY`, `SPARSE_BACKEND`, `BGE_M3_PROVIDER_URL`, and a reachable BGE-M3 sparse service needed for the BM25-vs-BGE reindex-and-compare workflow
- [x] 5.5 Deferred on 2026-03-29: acceptance decision remains pending until the live comparison in 5.4 is run in a correctly configured environment and the resulting Precision@K, Recall@K, and MRR metrics are recorded

## 6. Test coverage review

- [x] 6.1 Review the implemented behavior against the delta specs and identify any missing deterministic coverage before archive
- [x] 6.2 Add any missing tests required for stable behavior in `vector-storage`, `hybrid-retrieval`, `ingestion-pipeline`, and `bm25-keyword-search`

## 7. Verification

- [x] 7.1 Run all targeted backend unit tests in Docker containers only
- [x] 7.2 Run targeted integration tests in Docker containers only
- [x] 7.3 Re-read `docs/development.md` and self-review the final implementation against project standards before reporting completion
- [x] 7.4 Verify installed package versions against `docs/spec.md` before reporting completion
