## Purpose

Layered prompt orchestration with XML tags, token budget management for retrieval context, and structured output for observability. Replaces the flat `build_chat_prompt()` function with a `ContextAssembler` class that builds the full LLM prompt from independently testable layers. Introduced by S4-05.

## ADDED Requirements

### Requirement: Layer ordering in system message

The `ContextAssembler` SHALL build the system message by assembling layers in the following fixed order: safety, identity, soul, behavior, promotions, citation instructions, content guidelines. Each layer SHALL be wrapped in XML tags (`<tag_name>...</tag_name>`). The layer order SHALL NOT be configurable — it is a design invariant defined by the prompt engineering spec.

#### Scenario: All layers present in correct order

- **WHEN** `assemble()` is called with active promotions and retrieval chunks
- **THEN** the system message SHALL contain XML tags in this order: `<system_safety>`, `<identity>`, `<soul>`, `<behavior>`, `<promotions>`, `<citation_instructions>`, `<content_guidelines>`
- **AND** each opening tag SHALL have a corresponding closing tag

#### Scenario: Persona layers always present even when empty

- **WHEN** `assemble()` is called with empty identity, soul, and behavior persona content
- **THEN** the system message SHALL still contain `<identity>`, `<soul>`, and `<behavior>` tags (with empty content)
- **AND** `<system_safety>` SHALL always be present with the safety policy text

---

### Requirement: XML tag wrapping

Each prompt layer SHALL be wrapped in an XML tag pair. The tag name SHALL match the layer purpose: `system_safety`, `identity`, `soul`, `behavior`, `promotions`, `citation_instructions`, `content_guidelines`, `knowledge_context`, `user_query`. The XML wrapping improves LLM comprehension of section boundaries and enables programmatic testing of tag presence and order.

#### Scenario: Each layer wrapped in named tags

- **WHEN** the assembled prompt is inspected
- **THEN** every layer's content SHALL be enclosed between `<tag_name>` and `</tag_name>`
- **AND** no layer content SHALL appear outside its tags

---

### Requirement: Promotions layer conditional inclusion

The `<promotions>` layer SHALL be included in the system message only when the `ContextAssembler` has active promotions. When no active promotions exist, the `<promotions>` block SHALL be omitted entirely (not present as an empty tag). This saves tokens and avoids confusing the LLM with an empty promotional section.

#### Scenario: Promotions omitted when none active

- **WHEN** `assemble()` is called with an empty promotions list
- **THEN** the system message SHALL NOT contain `<promotions>` or `</promotions>`

#### Scenario: Promotion content injected when active

- **WHEN** `assemble()` is called with one active promotion containing title "Special Offer" and body "Buy now"
- **THEN** the system message SHALL contain `<promotions>` with the promotion title, context hint (if present), and body details
- **AND** `AssembledPrompt.included_promotions` SHALL contain the promotion object

---

### Requirement: Citation instructions conditional inclusion

The `<citation_instructions>` layer SHALL be included in the system message only when retrieval chunks are available (at least one chunk selected after budget trimming). When no chunks are selected, the `<citation_instructions>` block SHALL be omitted entirely. Citation instructions without any knowledge context to cite are meaningless.

#### Scenario: Citation instructions present with chunks

- **WHEN** `assemble()` is called with at least one retrieval chunk that fits within budget
- **THEN** the system message SHALL contain `<citation_instructions>` with rules for `[source:N]` markers

#### Scenario: Citation instructions absent without chunks

- **WHEN** `assemble()` is called with an empty chunks list
- **THEN** the system message SHALL NOT contain `<citation_instructions>` or `</citation_instructions>`

---

### Requirement: Content guidelines always present

The `<content_guidelines>` layer SHALL always be included in the system message, regardless of whether promotions or retrieval chunks are present. The content guidelines instruct the LLM to distinguish between facts, inferences, and recommendations — this distinction is useful even when only inferences are possible.

#### Scenario: Guidelines present without promotions or chunks

- **WHEN** `assemble()` is called with no promotions and no chunks
- **THEN** the system message SHALL still contain `<content_guidelines>` describing fact/inference/recommendation distinctions

---

### Requirement: Retrieval context budget management

The `ContextAssembler` SHALL manage a token budget for the retrieval context (`retrieval_context_budget`, default 4096 tokens). The budget governs only the `<knowledge_context>` portion — persona, safety, promotions, and other layers are always included without budget checks. Chunks SHALL be processed in order (sorted by RRF relevance score, most relevant first). Each chunk SHALL be included as a whole unit — truncating a chunk mid-text is not allowed. When adding the next chunk would exceed the budget, the assembler SHALL stop including further chunks (drop from the tail). Token estimation SHALL use the shared `estimate_tokens()` function (CHARS_PER_TOKEN=3).

#### Scenario: All chunks fit within budget

- **WHEN** 3 short chunks totaling ~500 tokens are assembled with `retrieval_context_budget=4096`
- **THEN** `AssembledPrompt.retrieval_chunks_used` SHALL be 3
- **AND** `retrieval_chunks_total` SHALL be 3

#### Scenario: Chunks trimmed when over budget

- **WHEN** 3 chunks of ~333 tokens each are assembled with `retrieval_context_budget=500`
- **THEN** `retrieval_chunks_used` SHALL be less than 3
- **AND** `retrieval_chunks_total` SHALL be 3

#### Scenario: No knowledge context when zero chunks selected

- **WHEN** all chunks exceed the budget and `min_retrieved_chunks=0`
- **THEN** `retrieval_chunks_used` SHALL be 0
- **AND** the user message SHALL NOT contain `<knowledge_context>`

---

### Requirement: min_retrieved_chunks hard limit override

The `min_retrieved_chunks` setting SHALL act as a hard override on the retrieval context budget. When budget trimming would result in fewer chunks than `min_retrieved_chunks`, the assembler SHALL include chunks up to `min_retrieved_chunks` regardless of the token budget. This prevents budget settings from silently degrading answer quality below the minimum threshold. When even `min_retrieved_chunks` chunks exceed the budget, they are still included — `min_retrieved_chunks` takes priority over the budget. Budget exceedance in this case SHALL be logged as a warning.

#### Scenario: Hard limit forces inclusion despite budget

- **WHEN** one chunk of 3000 characters (~1000 tokens) is assembled with `retrieval_context_budget=100` and `min_retrieved_chunks=1`
- **THEN** `retrieval_chunks_used` SHALL be 1 (forced inclusion)

#### Scenario: min_retrieved_chunks=0 allows zero chunks

- **WHEN** chunks exceed budget and `min_retrieved_chunks=0`
- **THEN** the assembler SHALL produce a prompt with 0 retrieval chunks
- **AND** this is valid behavior (the LLM responds using persona and promotions only)

---

### Requirement: Conversation memory slot reservation

The `ContextAssembler` SHALL contain a `TODO(S4-06)` placeholder in the layer assembly sequence between the promotions layer and the citation instructions layer. This placeholder SHALL reference the future `_build_memory_layer()` method and the S4-06 story. No stub code or empty prompt block SHALL be generated — only a code comment.

#### Scenario: Memory slot is a code comment only

- **WHEN** the `ContextAssembler` source code is inspected
- **THEN** there SHALL be a `TODO(S4-06)` comment between the promotions and citation instructions layers
- **AND** no `<conversation_memory>` tag SHALL appear in any assembled prompt

---

### Requirement: Token estimation using CHARS_PER_TOKEN

All token estimation within the `ContextAssembler` SHALL use the shared `estimate_tokens()` function from `services/token_counter.py`, which applies the `CHARS_PER_TOKEN=3` constant. This ensures consistent token estimation across query rewriting and context assembly.

#### Scenario: Token estimate is positive for non-empty prompts

- **WHEN** `assemble()` is called with any non-empty persona and query
- **THEN** `AssembledPrompt.token_estimate` SHALL be greater than 0

#### Scenario: Token estimate equals sum of layer estimates

- **WHEN** `assemble()` is called
- **THEN** `AssembledPrompt.token_estimate` SHALL reflect the total estimated tokens across the system and user messages

---

### Requirement: AssembledPrompt output type with metadata

The `assemble()` method SHALL return an `AssembledPrompt` dataclass containing: `messages` (list of OpenAI chat API format dicts), `token_estimate` (total estimated tokens), `included_promotions` (list of Promotion objects injected), `retrieval_chunks_used` (count of chunks that fit within budget), `retrieval_chunks_total` (total chunks available from retrieval), and `layer_token_counts` (dict mapping layer tag names to their individual token estimates). This metadata supports observability and debugging.

#### Scenario: All metadata fields populated

- **WHEN** `assemble()` is called with promotions and chunks
- **THEN** `AssembledPrompt` SHALL have non-null values for all metadata fields
- **AND** `layer_token_counts` SHALL contain entries for `system_safety`, `identity`, `soul`, `behavior`, `promotions`, `citation_instructions`, and `content_guidelines`

#### Scenario: Messages in OpenAI chat API format

- **WHEN** `assemble()` is called
- **THEN** `AssembledPrompt.messages` SHALL be a list of 2 dicts: one with `role=system` and one with `role=user`
- **AND** each dict SHALL have `role` and `content` string keys

---

### Requirement: User message structure

The user message SHALL contain two optional sections: `<knowledge_context>` (present when retrieval chunks are selected) and `<user_query>` (always present, containing the original user question). When no retrieval chunks are selected, `<knowledge_context>` SHALL be omitted. The `<user_query>` tag wraps the user's original question text.

#### Scenario: User message with retrieval context

- **WHEN** `assemble()` is called with selected retrieval chunks and query "Tell me about AI"
- **THEN** the user message SHALL contain `<knowledge_context>` with formatted chunk text
- **AND** SHALL contain `<user_query>` wrapping "Tell me about AI"

#### Scenario: User message without retrieval context

- **WHEN** `assemble()` is called with no chunks (or all trimmed by budget with min=0)
- **THEN** the user message SHALL NOT contain `<knowledge_context>`
- **AND** SHALL contain only `<user_query>` wrapping the question
