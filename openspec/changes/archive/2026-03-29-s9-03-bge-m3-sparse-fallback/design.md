## Context

**Story:** S9-03 — BGE-M3 fallback.

ProxyMind already has a stable hybrid retrieval stack: Gemini dense embeddings, one sparse leg stored in Qdrant, and RRF fusion on top of child-ranked retrieval. The current implementation assumes Qdrant BM25 for the sparse leg and bakes that assumption into collection creation, point upsert, keyword diagnostics, and eval expectations.

This change affects the **knowledge circuit** only. The following areas are affected:

- sparse indexing and sparse query construction in `QdrantService`
- startup wiring for retrieval/indexing services
- ingestion-side sparse text preparation
- admin diagnostics for keyword search
- eval workflow for language-specific sparse comparison

The following areas remain unchanged by design:

- Gemini dense embedding generation
- parent-child retrieval semantics
- citation building
- prompt assembly and chat response behavior
- visitor-facing APIs

Project constraints are strong and shape the design:

- backend verification MUST run in containers only
- local heavyweight ML runtimes MUST NOT be added to backend containers
- the product remains multilingual and installation-configurable
- a sparse backend switch must be explicit and auditable rather than a silent runtime fallback

See also `docs/rag.md` for the existing retrieval architecture and `docs/superpowers/specs/2026-03-29-s9-03-bge-m3-fallback-design.md` for the full brainstorming design that this OpenSpec change operationalizes.

## Goals / Non-Goals

**Goals:**

- Add an installation-level sparse backend switch: `bm25` or `bge_m3`
- Introduce a narrow sparse-provider abstraction used by both indexing and retrieval
- Keep the current hybrid retrieval contract stable: Gemini dense + active sparse + RRF
- Make Qdrant schema lifecycle explicitly aware of the active sparse backend contract
- Require explicit reindexing when the sparse backend changes
- Expose active sparse backend metadata in keyword diagnostics
- Support language-specific sparse comparison through the existing eval suite format and a documented two-run workflow

**Non-Goals:**

- Replacing Gemini dense embeddings
- Building adaptive query-time routing between BM25 and BGE-M3
- Supporting multiple active sparse backends inside one installation at the same time
- Hosting BGE-M3 inside backend or worker containers
- Adding automatic report comparison tooling in the eval runner
- Redesigning prompt assembly, citation logic, or parent-child retrieval behavior

## Decisions

### 1. One active sparse backend per installation

The system will expose exactly one active sparse backend at a time:

- `bm25`
- `bge_m3`

This keeps the operating model simple and matches the rest of the product, where language-sensitive behavior is configured per installation rather than negotiated per query. It also keeps the change attributable in evals.

**Alternative rejected:** per-language or query-time sparse routing. That adds mixed index semantics, more testing complexity, and more operational ambiguity than this story warrants.

### 2. Keep the Qdrant retrieval slot stable, change the sparse producer behind it

At the application level, retrieval still has one dense leg and one sparse leg. The sparse slot in Qdrant remains the retrieval-time sparse leg used by:

- `upsert_chunks()` for indexing
- `keyword_search()` for diagnostics
- `hybrid_search()` for RRF fusion

The producer of that sparse representation becomes provider-aware:

- BM25 provider builds Qdrant `Document` inputs using `Bm25Config`
- BGE-M3 provider returns explicit sparse indices/values from an external service

This preserves the hybrid retrieval structure while allowing the sparse backend to change.

**Alternative rejected:** creating a full dual-sparse platform with separate runtime legs for BM25 and BGE-M3. That would be useful for experimentation but is too large for S9-03.

### 3. Treat sparse backend changes as index contract changes

The current Qdrant lifecycle logic is BM25-specific. S9-03 must not merely inject a provider into query/upsert paths while leaving BM25-only lifecycle assumptions in place. The active sparse backend becomes part of the Qdrant index contract.

That contract is represented through:

- provider metadata (`backend`, `model_name`, `contract_version`)
- provider-aware collection validation
- sparse backend metadata embedded in indexed payloads for diagnostics and auditability

Provider metadata uses the following schema:

- `backend`: required string enum. Allowed values in S9-03 are `bm25` and `bge_m3`.
- `model_name`: required non-empty string, 1-128 chars, pattern-compatible with provider identifiers such as `Qdrant/bm25` and `bge-m3`.
- `contract_version`: required non-empty string. S9-03 v1 uses `v1`, and validators MUST reject empty values or unknown major-version formats.

Example metadata objects:

```json
{ "backend": "bm25", "model_name": "Qdrant/bm25", "contract_version": "v1" }
```

```json
{ "backend": "bge_m3", "model_name": "bge-m3", "contract_version": "v1" }
```

Versioning semantics:

- bump `contract_version` whenever sparse payload format, provider response normalization, or sparse query semantics change in an incompatible way;
- backward-compatible refactors keep the same `contract_version`;
- validators compare all three fields and MUST treat any mismatch as reindex-required.

The compatibility check runs in `QdrantService.ensure_collection()` during startup. The implementation scans indexed child payload metadata page-by-page across the target collection, not just one sample point. If metadata is missing, mixed, or incompatible, the startup path raises `CollectionSchemaMismatchError` and refuses to proceed.

The concrete failure contract for the incompatible provider metadata case is:

- exception: `CollectionSchemaMismatchError`
- operator-facing message: `Index incompatible with active sparse provider configuration; explicit reindex is required.`
- check point: startup, inside `QdrantService.ensure_collection()` before the service is considered ready
- service behavior: API/worker startup fails and the process remains unready or exits non-zero rather than serving mixed-contract retrieval
- logging: operator-visible startup error log with collection name, configured sparse metadata, detected sparse metadata, and correlation id when one exists in the surrounding context

If the active provider metadata is incompatible with the existing index state, the system will fail explicitly and require reindexing rather than attempting a mixed-mode migration.

#### Detecting pre-change collections

Pre-change Qdrant collections are identified by the absence of the `active sparse backend` markers in payload metadata: `sparse_backend`, `sparse_model`, or `sparse_contract_version`. That missing sparse contract metadata means compatibility cannot be proven.

Migration options for S9-03 are intentionally conservative:

- legacy BM25 collections may continue to run only while the installation stays on `SPARSE_BACKEND=bm25` and the collection schema is otherwise valid;
- switching to `bge_m3`, or observing a mixed legacy/annotated state, requires a full reindex;
- S9-03 does not implement an in-place metadata stamping command because it cannot prove that historical sparse artifacts were produced by the current provider.

User-facing remediation template:

> Collection missing sparse metadata: explicit reindex required. Keep `SPARSE_BACKEND=bm25` only if you intend to keep serving the legacy BM25 index. Otherwise rebuild the index under the target sparse backend and republish the target snapshot.

**Alternative rejected:** silent reuse of an index built under a different sparse backend. That would undermine eval validity and violate the explicit reindex rule from the story design.

### 4. BGE-M3 remains an external sparse provider

The project already uses Google technologies for dense embeddings, batch processing, and document-intelligence fallback, but BGE-M3 itself is treated as an external sparse provider. The backend only knows the HTTP-level sparse provider contract.

This avoids introducing local heavy inference dependencies into backend containers and stays aligned with the cheap-VPS-first rule.

#### BGE-M3 HTTP-level sparse provider contract

The backend's HTTP-level sparse provider contract for BGE-M3 is synchronous and deliberately narrow:

- `POST /sparse/documents` with body `{ "text": string }` returns `{ "indices": number[], "values": number[] }` for indexing-time sparse vectors.
- `POST /sparse/queries` with body `{ "text": string }` returns `{ "indices": number[], "values": number[] }` for query-time sparse vectors.
- `indices` MUST be integer-compatible numbers, `values` MUST be float-compatible numbers, and both arrays MUST have the same length.
- S9-03 v1 supports one text per request only; batched behavior is out of scope for this story.
- recommended provider latency target is p95 <= 2s, while the backend timeout stays at 10s by default.
- non-2xx responses are treated as hard provider failures; a recommended error body is `{ "error_code": string, "message": string, "retryable": boolean }`, although the v1 client relies primarily on HTTP status + body.

#### BGE-M3 connectivity configuration contract

Configuration fields and semantics for external sparse-provider wiring:

| Field                                | Required           | Default / Current mapping            | Semantics                                                                                                              |
| ------------------------------------ | ------------------ | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `sparse_backend`                     | Yes                | `bm25`                               | Installation-level selector. Allowed values: `bm25`, `bge_m3`.                                                         |
| `service_endpoint_url`               | Conditional        | implemented as `BGE_M3_PROVIDER_URL` | Full URL or host:port for the BGE-M3 sparse provider. Required when `sparse_backend=bge_m3`.                           |
| `auth.type`                          | Optional, reserved | not implemented in S9-03 v1          | Planned values: `api_key` or `bearer_token`. Current deployment assumes network-trusted or pre-authenticated upstream. |
| `auth.credential_name`               | Optional, reserved | not implemented in S9-03 v1          | Secret or credential reference paired with `auth.type`.                                                                |
| `timeout_ms`                         | Optional           | `10000` via `BGE_M3_TIMEOUT_SECONDS` | Per-request timeout for sparse document/query calls.                                                                   |
| `retry_policy.max_retries`           | Optional, reserved | not implemented in S9-03 v1          | Client-side retry count for provider calls.                                                                            |
| `retry_policy.initial_backoff_ms`    | Optional, reserved | not implemented in S9-03 v1          | Initial backoff before retrying provider calls.                                                                        |
| `retry_policy.max_backoff_ms`        | Optional, reserved | not implemented in S9-03 v1          | Upper bound for exponential backoff.                                                                                   |
| `retry_policy.backoff_strategy`      | Optional, reserved | not implemented in S9-03 v1          | Expected values: `exponential`, `fixed`.                                                                               |
| `health_check.path`                  | Optional, reserved | not implemented in S9-03 v1          | Recommended readiness path such as `/health` or `/ready`.                                                              |
| `health_check.method`                | Optional, reserved | not implemented in S9-03 v1          | Recommended HTTP method, normally `GET`.                                                                               |
| `health_check.interval_seconds`      | Optional, reserved | not implemented in S9-03 v1          | Poll interval for health probes.                                                                                       |
| `health_check.timeout_seconds`       | Optional, reserved | not implemented in S9-03 v1          | Timeout for health probes.                                                                                             |
| `health_check.expected_status_codes` | Optional, reserved | not implemented in S9-03 v1          | Recommended acceptable codes, usually `[200]`.                                                                         |

**Alternative rejected:** hosting BGE-M3 in the backend or worker container. This conflicts with project policy.

### 5. Comparison workflow is two explicit eval runs

The current eval runner can load suites and execute retrieval/generation against one running system configuration at a time. It does not natively compare two sparse backends in a single invocation.

Therefore, S9-03 uses this workflow:

1. run the suite with `SPARSE_BACKEND=bm25`
2. switch configuration to `SPARSE_BACKEND=bge_m3`, set `BGE_M3_PROVIDER_URL`, and rebuild the sparse index
3. run the same suite again
4. compare the generated reports explicitly

The acceptance decision for this story is based on retrieval metrics only. The required comparison metrics are:

- Precision@5
- Precision@10
- Recall@5
- Recall@10
- MRR@10, where reciprocal rank is computed from the first relevant hit inside the top-10 results

The story is considered successful only when the BGE-M3 run improves the target-language retrieval baseline versus BM25 on the agreed comparison suite, while the dense-side and hybrid retrieval contract remains unchanged. S9-03 uses MRR@10 as the primary metric; acceptance also requires at least three of the four Precision/Recall metrics to be non-decreasing and no metric to regress by more than 0.02 absolute.

This keeps the story compatible with existing tooling and avoids inventing fake comparison automation.

**Alternative rejected:** claiming one eval run can automatically compare both sparse backends. That is not true with the current runner.

## Risks / Trade-offs

- **[Sparse contract metadata may be hard to infer from existing Qdrant collections]** → Make the active sparse backend explicit in payload metadata and fail loudly when compatibility cannot be proven.
- **[Keyword-search capability name is BM25-oriented while behavior becomes provider-aware]** → Keep the endpoint stable for diagnostics, but return explicit `sparse_backend` and `sparse_model` metadata so behavior is transparent.
- **[External BGE-M3 provider introduces network failure modes]** → Treat provider unavailability as an explicit operational failure, not a silent no-results fallback.
- **[Reindex requirement increases operational cost]** → Accept this cost because it preserves correctness, auditability, and eval validity.
- **[Eval comparison remains partly manual]** → Document the two-run workflow clearly and keep dataset format compatible with the current loader.

## Migration Plan

1. Add configuration for `sparse_backend` and BGE-M3 provider connectivity.
2. Introduce the sparse-provider abstraction and wire it into API and worker startup.
3. Refactor `QdrantService` so collection validation, point upsert, keyword search, and hybrid search all depend on the active sparse provider contract.
4. Add sparse backend diagnostics to the admin keyword-search response.
5. Add a language-specific eval dataset in the current suite format.
6. Validate behavior in containers with BM25 as the default sparse backend.
7. For an installation that needs BGE-M3, perform an explicit rebuild:
   - update `.env` / `backend/.env` with `SPARSE_BACKEND=bge_m3`, `BGE_M3_PROVIDER_URL=<service_endpoint_url>`, and optional `BGE_M3_MODEL_NAME` / `BGE_M3_TIMEOUT_SECONDS`;
   - create or confirm a draft snapshot via `POST /api/admin/snapshots`;
   - rebuild the corpus through the existing ingestion surface by re-uploading the source set with `POST /api/admin/sources` and polling `GET /api/admin/tasks/{task_id}` until each task reports `status=completed` and `progress=100`;
   - watch API/worker logs for `CollectionSchemaMismatchError`, BGE-M3 transport failures, and background-task failures;
   - publish and optionally activate the rebuilt draft via `POST /api/admin/snapshots/{snapshot_id}/publish?activate=true`;
   - run the second eval pass and compare reports.

Reindexing semantics and downtime:

- in a single deployment, switching from `bm25` to `bge_m3` may require collection recreation because the sparse vector slot configuration changes from BM25 IDF to raw sparse vectors;
- that means the v1 path is an in-place rebuild of the same logical Qdrant collection, not a shadow index inside the same service;
- expected downtime or degraded retrieval is therefore possible during a single-environment switch;
- recommended zero-downtime procedure is blue/green deployment (second environment or second Qdrant collection) followed by cutover after the BGE-M3 rebuild and eval validation succeed.

Post-reindex validation checklist:

- verify `POST /api/admin/search/keyword` reports `sparse_backend="bge_m3"`, the expected `sparse_model`, `language=null`, and the install-level `bm25_language`;
- verify the target draft snapshot publishes/activates successfully;
- run the target-language eval suite and compare `Precision@5`, `Precision@10`, `Recall@5`, `Recall@10`, and `MRR@10` against the BM25 baseline.

### Rollback

Rollback is configuration + reindex, not a hot toggle:

1. restore `SPARSE_BACKEND=bm25`
2. rebuild the sparse index under BM25
3. verify diagnostics and retrieval behavior against the BM25 report

## Open Questions

- Should a future story add explicit report-diff tooling for eval comparisons, or is manual comparison acceptable for this phase?

## Resolved Implementation Note

For S9-03 v1, payload-level sparse metadata is the required compatibility marker for indexed child points. The implementation may add collection-level markers later if Qdrant capabilities make that useful, but this change does not depend on them. Tasks are intentionally aligned with payload-level metadata as the explicit contract for compatibility checks and diagnostics.

The admin diagnostics surface does not add a `reindex_required` flag in S9-03 v1. Incompatibility is surfaced earlier as startup-time `CollectionSchemaMismatchError`; once the service is healthy, diagnostics report configured `sparse_backend`, configured `sparse_model`, the active `language` when BM25 is selected, and the install-level `bm25_language` for operator clarity.
