# eval-generate-endpoint

Debug-mode generation endpoint exposing the full RAG pipeline artifacts (answer, citations, retrieved chunks, rewritten query) as a synchronous JSON response for eval answer quality scoring.

## ADDED Requirements

### Requirement: Endpoint contract

A new endpoint `POST /api/admin/eval/generate` SHALL accept a JSON request body with the following fields:

- `query` (string, required, min_length=1 after trimming) -- the user question to generate an answer for
- `snapshot_id` (UUID, required) -- the knowledge snapshot for retrieval

The response SHALL be a JSON object with:

- `answer` (string) -- the full text of the twin's response
- `citations` (list of dicts) -- citations as JSON-serialized dicts from the backend Citation dataclass
- `retrieved_chunks` (list of objects) -- chunks fed to the LLM, each containing `chunk_id` (UUID), `source_id` (UUID), `score` (float), `text` (str), and `rank` (int, 1-based)
- `rewritten_query` (string) -- the reformulated query, or the original query if rewriting was skipped
- `timing_ms` (float) -- total generation time in milliseconds
- `model` (string) -- the model used for generation

Request and response models SHALL be defined as Pydantic schemas. The endpoint SHALL trim surrounding whitespace from `query`; a value that becomes empty after trimming SHALL be rejected with HTTP 422.

#### Scenario: Successful generation returns full artifacts

- **WHEN** a valid request with query and snapshot_id is sent
- **THEN** the response contains `answer`, `citations`, `retrieved_chunks`, `rewritten_query`, `timing_ms`, and `model` fields

#### Scenario: Empty query rejected

- **WHEN** a request sends `query=""`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: Whitespace-only query rejected

- **WHEN** a request sends `query="   "`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: Invalid snapshot_id rejected

- **WHEN** a request sends `snapshot_id="not-a-uuid"`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: Retrieved chunks include text and source_id

- **WHEN** the generation pipeline retrieves chunks
- **THEN** each entry in `retrieved_chunks` SHALL contain `chunk_id` (UUID), `source_id` (UUID), `score` (float), `text` (full chunk text), and `rank` (int, 1-based)

---

### Requirement: Pipeline reuse

The endpoint SHALL reuse the existing RAG pipeline components: query rewriter, retrieval service, prompt/context assembler, LLM service, and citation extractor. The endpoint SHALL NOT implement custom retrieval or generation logic. The only difference from the chat endpoint is the response format: synchronous JSON instead of SSE, and exposure of intermediate artifacts (`retrieved_chunks`, `rewritten_query`) in the response body.

#### Scenario: Pipeline stages executed in order

- **WHEN** a valid generation request is processed
- **THEN** the endpoint SHALL execute: query rewrite, retrieval, context assembly, LLM completion, and citation extraction in sequence

#### Scenario: No SSE streaming

- **WHEN** the endpoint returns a response
- **THEN** the response SHALL be a single JSON object with `Content-Type: application/json`, not a stream of SSE events

#### Scenario: Single-turn only

- **WHEN** a generation request is processed
- **THEN** no session_id is created or used; the endpoint operates in single-turn mode without conversation history

---

### Requirement: Authentication

The endpoint MUST require admin authentication using the existing `verify_admin_key` dependency. Unauthenticated or incorrectly authenticated requests SHALL be rejected with HTTP 401.

#### Scenario: Valid admin key accepted

- **WHEN** a request includes a valid admin API key in the `Authorization: Bearer` header
- **THEN** the request is processed and a generation response is returned

#### Scenario: Missing admin key rejected

- **WHEN** a request does not include the `Authorization: Bearer` header
- **THEN** the endpoint returns HTTP 401

#### Scenario: Invalid admin key rejected

- **WHEN** a request includes an incorrect admin API key
- **THEN** the endpoint returns HTTP 401

---

### Requirement: Error handling

If any pipeline stage (retrieval, query rewrite, LLM completion, citation extraction) fails with an exception, the endpoint SHALL return HTTP 500 with a JSON payload containing an `error` field describing the failure. The endpoint SHALL NOT surface raw tracebacks to the client.

#### Scenario: Retrieval failure returns 500

- **WHEN** `RetrievalService.search()` raises an exception during generation
- **THEN** the endpoint returns HTTP 500 with `{"error": "..."}`

#### Scenario: LLM failure returns 500

- **WHEN** the LLM completion step raises an exception
- **THEN** the endpoint returns HTTP 500 with `{"error": "..."}`
