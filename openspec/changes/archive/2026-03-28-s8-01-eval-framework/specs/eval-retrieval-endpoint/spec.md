# eval-retrieval-endpoint

Admin API endpoint exposing raw retrieval results for use by the eval framework's scorers. Returns ranked chunks with full text to enable ground-truth matching.

## ADDED Requirements

### Requirement: Endpoint contract

A new endpoint `POST /api/admin/eval/retrieve` SHALL accept a JSON request body with the following fields:

- `query` (string, min_length=1) -- the search query to evaluate
- `snapshot_id` (UUID) -- the knowledge snapshot to search against
- `top_n` (integer, default=5, range 1-50) -- number of top chunks to return

The response SHALL be a JSON object with:

- `chunks` (list) -- each entry containing `chunk_id` (UUID), `source_id` (UUID), `score` (float), `text` (string, full chunk text), and `rank` (integer, 1-based sequential)
- `timing_ms` (float) -- elapsed time of the retrieval operation in milliseconds

Request and response models SHALL be defined as Pydantic schemas in `backend/app/api/eval_schemas.py`. The router SHALL be registered in `backend/app/main.py`.
The endpoint SHALL validate `snapshot_id` syntactically only; it SHALL NOT perform a separate existence lookup, so a syntactically valid UUID with no indexed chunks returns HTTP 200 with an empty `chunks` list rather than HTTP 404.

#### Scenario: Successful retrieval returns ranked chunks

- **WHEN** a valid request with query, snapshot_id, and top_n is sent
- **THEN** the response contains a `chunks` list with up to `top_n` entries, each having `chunk_id`, `source_id`, `score`, `text`, and `rank` fields, plus a `timing_ms` value

#### Scenario: Empty results are valid

- **WHEN** retrieval finds no matching chunks for a valid request
- **THEN** the endpoint returns HTTP 200 with `chunks=[]` and a `timing_ms` value

#### Scenario: Fewer chunks than top_n requested

- **WHEN** a request asks for `top_n=10` and retrieval returns only 3 chunks
- **THEN** the endpoint returns exactly 3 chunk entries with ranks 1, 2, and 3

#### Scenario: Chunks are ranked sequentially starting at 1

- **WHEN** the retrieval returns 3 chunks
- **THEN** the chunks have `rank` values of 1, 2, and 3 respectively

#### Scenario: Default top_n is 5

- **WHEN** a request omits the `top_n` field
- **THEN** the endpoint uses `top_n=5`

#### Scenario: top_n below 1 rejected

- **WHEN** a request sends `top_n=0`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: top_n above 50 rejected

- **WHEN** a request sends `top_n=100`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: Empty query rejected

- **WHEN** a request sends `query=""`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: Invalid snapshot_id rejected

- **WHEN** a request sends `snapshot_id="not-a-uuid"`
- **THEN** the endpoint returns HTTP 422 with a validation error

#### Scenario: Full chunk text included in response

- **WHEN** a retrieval returns chunks
- **THEN** each chunk's `text` field contains the full chunk text content (not truncated), enabling substring matching by eval scorers

---

### Requirement: Authentication

The endpoint MUST require admin authentication using the existing `verify_admin_key` dependency from S7-01. Unauthenticated or incorrectly authenticated requests SHALL be rejected.

#### Scenario: Valid admin key accepted

- **WHEN** a request includes a valid admin API key in the `Authorization: Bearer` header
- **THEN** the request is processed and a retrieval response is returned

#### Scenario: Missing admin key rejected

- **WHEN** a request does not include the `Authorization: Bearer` header
- **THEN** the endpoint returns HTTP 401

#### Scenario: Invalid admin key rejected

- **WHEN** a request includes an incorrect admin API key
- **THEN** the endpoint returns HTTP 401

---

### Requirement: Behavior

The endpoint SHALL call `RetrievalService.search()` directly, bypassing the LLM and chat session logic. It SHALL NOT create a chat session or invoke any LLM. The endpoint SHALL return full chunk text to enable `contains` substring matching in eval scorers. Chunks SHALL be ranked sequentially (1-based) in the order returned by the retrieval service (highest relevance first).

#### Scenario: No LLM invocation

- **WHEN** a retrieval eval request is processed
- **THEN** only `RetrievalService.search()` is called; no LLM provider or chat service is invoked

#### Scenario: Direct retrieval service call

- **WHEN** the endpoint receives a valid request
- **THEN** it calls `RetrievalService.search()` with the provided `query`, `snapshot_id`, and `top_n` parameters

#### Scenario: Timing measured accurately

- **WHEN** a retrieval is performed
- **THEN** the `timing_ms` field reflects the elapsed time of the `RetrievalService.search()` call in milliseconds

#### Scenario: Retrieval failure returns JSON 500 without timing_ms

- **WHEN** `RetrievalService.search()` throws an exception while handling a valid request
- **THEN** the endpoint returns HTTP 500 with a JSON payload containing an `error` field, does not include `timing_ms`, and still does not invoke any LLM or chat logic
