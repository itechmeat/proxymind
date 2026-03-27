## Purpose

Layered prompt orchestration with XML tags, token budget management for retrieval context, and structured output for observability. Replaces the flat `build_chat_prompt()` function with a `ContextAssembler` class that builds the full LLM prompt from independently testable layers. Introduced by S4-05. Extended by S6-01 with `available_products` and `product_instructions` prompt layers for catalog integration.

## ADDED Requirements

### Requirement: available_products prompt layer

The `ContextAssembler` SHALL build an `<available_products>` prompt layer listing all active, non-expired catalog items passed via the `catalog_items` parameter. Each item SHALL be formatted as `[product:N] "{name}" ({item_type}) - SKU: {sku}` where N is the 1-based index. The layer SHALL include introductory text instructing the LLM to use `[product:N]` markers when recommending. The layer SHALL be placed after `<promotions>` and before `<conversation_summary>` in the system message.

#### Scenario: available_products layer with items

- **WHEN** `assemble()` is called with `catalog_items` containing 2 items: "AI in Practice" (book, SKU: AI-PRACTICE-2026) and "Tech Summit 2026 Ticket" (event, SKU: TECHSUMMIT-2026)
- **THEN** the system message SHALL contain an `<available_products>` block
- **AND** the block SHALL list `[product:1] "AI in Practice" (book) - SKU: AI-PRACTICE-2026`
- **AND** the block SHALL list `[product:2] "Tech Summit 2026 Ticket" (event) - SKU: TECHSUMMIT-2026`
- **AND** the block SHALL include introductory text about using `[product:N]` markers

#### Scenario: available_products omitted when no catalog items

- **WHEN** `assemble()` is called with `catalog_items` as an empty list or `None`
- **THEN** the system message SHALL NOT contain `<available_products>` or `</available_products>`

#### Scenario: available_products placed after promotions

- **WHEN** `assemble()` is called with both active promotions and catalog items
- **THEN** `<available_products>` SHALL appear after `<promotions>` and before `<conversation_summary>`

---

### Requirement: product_instructions prompt layer

The `ContextAssembler` SHALL build a `<product_instructions>` prompt layer with rules for product recommendation behavior. The instructions SHALL tell the LLM to place `[product:N]` after mentioning a product, NOT to generate URLs, NOT to recommend unlisted products, to recommend only when naturally appropriate, and to make recommendations feel like genuine mentions rather than advertisements. This layer SHALL be placed after `<citation_instructions>` and before `<content_guidelines>`. It SHALL only be included when the `<available_products>` layer is non-empty.

#### Scenario: product_instructions present when products available

- **WHEN** `assemble()` is called with non-empty `catalog_items`
- **THEN** the system message SHALL contain `<product_instructions>` with recommendation rules
- **AND** the block SHALL appear after `<citation_instructions>` and before `<content_guidelines>`

#### Scenario: product_instructions omitted when no products

- **WHEN** `assemble()` is called with empty or null `catalog_items`
- **THEN** the system message SHALL NOT contain `<product_instructions>` or `</product_instructions>`

#### Scenario: product_instructions includes key behavioral rules

- **WHEN** the `<product_instructions>` block is present
- **THEN** it SHALL contain guidance to place `[product:N]` after mentioning a product
- **AND** it SHALL instruct not to generate URLs
- **AND** it SHALL instruct not to recommend products not in available_products
- **AND** it SHALL instruct to recommend only when naturally appropriate

---

### Requirement: catalog_items parameter on ContextAssembler

The `ContextAssembler.__init__()` SHALL accept an optional `catalog_items: list[CatalogItemInfo] | None = None` parameter. The catalog items SHALL be stored as an instance attribute for use during prompt assembly. When `None` or empty, no product-related layers SHALL be included.

#### Scenario: catalog_items parameter accepted

- **WHEN** `ContextAssembler` is constructed with `catalog_items=[item1, item2]`
- **THEN** the assembler SHALL store the items for use in prompt assembly
- **AND** `assemble()` SHALL include `<available_products>` and `<product_instructions>` layers

#### Scenario: catalog_items default is None

- **WHEN** `ContextAssembler` is constructed without the `catalog_items` argument
- **THEN** the default SHALL be `None`
- **AND** product-related layers SHALL be omitted from the assembled prompt

---

### Requirement: CatalogItemInfo in AssembledPrompt

The `AssembledPrompt` dataclass SHALL include a `catalog_items_used: list[CatalogItemInfo]` field containing the catalog items that were included in the prompt. When no catalog items are provided, this field SHALL be an empty list. This enables downstream services (e.g., `ProductRecommendationService`) to resolve `[product:N]` indices using the same item ordering.

#### Scenario: catalog_items_used populated

- **WHEN** `assemble()` is called with 2 catalog items
- **THEN** `AssembledPrompt.catalog_items_used` SHALL contain those 2 items in the same order

#### Scenario: catalog_items_used empty when no catalog

- **WHEN** `assemble()` is called with `catalog_items=None`
- **THEN** `AssembledPrompt.catalog_items_used` SHALL be an empty list

---

### Requirement: Token tracking for product layers

The `AssembledPrompt.layer_token_counts` SHALL include entries for `"available_products"` and `"product_instructions"` when those layers are present. Token estimation SHALL use the same `estimate_tokens()` function as all other layers. These tokens are a fixed overhead (~200-400 tokens for 10-20 items) and do NOT compete with `retrieval_context_budget`.

#### Scenario: Product layer tokens tracked

- **WHEN** `assemble()` is called with catalog items
- **THEN** `layer_token_counts` SHALL contain `"available_products"` with a positive token count
- **AND** `layer_token_counts` SHALL contain `"product_instructions"` with a positive token count

#### Scenario: Product layer tokens absent when no catalog

- **WHEN** `assemble()` is called without catalog items
- **THEN** `layer_token_counts` SHALL NOT contain `"available_products"` or `"product_instructions"`

---

## MODIFIED Requirements

### Requirement: Layer ordering in system message

The `ContextAssembler` SHALL build the system message by assembling layers in the following fixed order: safety, identity, soul, behavior, promotions, available_products, conversation_summary, citation instructions, product_instructions, content guidelines. Each layer SHALL be wrapped in XML tags (`<tag_name>...</tag_name>`). The layer order SHALL NOT be configurable.

#### Scenario: All layers present in correct order

- **WHEN** `assemble()` is called with active promotions, retrieval chunks, a `memory_block` containing `summary_text`, and catalog items
- **THEN** the system message SHALL contain XML tags in this order: `<system_safety>`, `<identity>`, `<soul>`, `<behavior>`, `<promotions>`, `<available_products>`, `<conversation_summary>`, `<citation_instructions>`, `<product_instructions>`, `<content_guidelines>`
- **AND** each opening tag SHALL have a corresponding closing tag

#### Scenario: Persona layers always present even when empty

- **WHEN** `assemble()` is called with empty identity, soul, and behavior persona content
- **THEN** the system message SHALL still contain `<identity>`, `<soul>`, and `<behavior>` tags (with empty content)
- **AND** `<system_safety>` SHALL always be present with the safety policy text

#### Scenario: Conversation summary placed between available_products and citation instructions

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text` and catalog items
- **THEN** the `<conversation_summary>` tag SHALL appear after `<available_products>` and before `<citation_instructions>`

#### Scenario: Order preserved when optional layers omitted

- **WHEN** `assemble()` is called with no promotions and no catalog items
- **THEN** the remaining layers SHALL still follow the defined order: `<system_safety>`, `<identity>`, `<soul>`, `<behavior>`, `<conversation_summary>` (if present), `<citation_instructions>` (if chunks), `<content_guidelines>`

---

### Requirement: AssembledPrompt output type with metadata

The `assemble()` method SHALL return an `AssembledPrompt` dataclass containing: `messages` (list of OpenAI chat API format dicts), `token_estimate` (total estimated tokens), `included_promotions` (list of Promotion objects injected), `retrieval_chunks_used` (count of chunks that fit within budget), `retrieval_chunks_total` (total chunks available from retrieval), `layer_token_counts` (dict mapping layer tag names to their individual token estimates), and `catalog_items_used` (list of CatalogItemInfo included in the prompt). When `memory_block` is `None` or has no messages, `messages` SHALL be a list of 2 dicts (system + current user message only). When `memory_block` contains history messages, `messages` SHALL be a list of N dicts: one system message, zero or more alternating user/assistant history messages, and one final user message containing the retrieval context and current query. When `memory_block` is provided and has `total_tokens > 0`, `layer_token_counts` SHALL contain a `"conversation_memory"` key with value equal to `memory_block.total_tokens`, and SHALL NOT contain a separate `"conversation_summary"` entry.

#### Scenario: All metadata fields populated

- **WHEN** `assemble()` is called with promotions, chunks, a `memory_block`, and catalog items
- **THEN** `AssembledPrompt` SHALL have non-null values for all metadata fields
- **AND** `layer_token_counts` SHALL contain entries for `system_safety`, `identity`, `soul`, `behavior`, `promotions`, `available_products`, `product_instructions`, `citation_instructions`, `content_guidelines`, and `conversation_memory`
- **AND** `catalog_items_used` SHALL contain the provided catalog items

#### Scenario: Messages as 2 dicts when no memory block

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** `AssembledPrompt.messages` SHALL be a list of 2 dicts: one with `role=system` and one with `role=user`
- **AND** each dict SHALL have `role` and `content` string keys

#### Scenario: Messages as N dicts with memory block history

- **WHEN** `assemble()` is called with a `memory_block` containing 2 history messages (user + assistant)
- **THEN** `AssembledPrompt.messages` SHALL be a list of 4 dicts: system, user (history), assistant (history), user (current query)
- **AND** each dict SHALL have `role` and `content` string keys

#### Scenario: conversation_memory key in layer_token_counts

- **WHEN** `assemble()` is called with a `memory_block` having `total_tokens=50`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `50`
- **AND** `layer_token_counts` SHALL NOT contain a `"conversation_summary"` key

#### Scenario: No conversation_memory key when memory_block is None

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** `layer_token_counts` SHALL NOT contain a `"conversation_memory"` key

---

## Existing Requirements (unchanged)

### Requirement: XML tag wrapping

Each prompt layer SHALL be wrapped in an XML tag pair. The tag name SHALL match the layer purpose: `system_safety`, `identity`, `soul`, `behavior`, `promotions`, `available_products`, `conversation_summary`, `product_instructions`, `citation_instructions`, `content_guidelines`, `knowledge_context`, `user_query`. The XML wrapping improves LLM comprehension of section boundaries and enables programmatic testing of tag presence and order.

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

The `ContextAssembler` SHALL manage a token budget for the retrieval context (`retrieval_context_budget`, default 4096 tokens). The budget governs only the `<knowledge_context>` portion — persona, safety, promotions, available_products, and other layers are always included without budget checks. Chunks SHALL be processed in order (sorted by RRF relevance score, most relevant first). Each chunk SHALL be included as a whole unit — truncating a chunk mid-text is not allowed. When adding the next chunk would exceed the budget, the assembler SHALL stop including further chunks (drop from the tail). Token estimation SHALL use the shared `estimate_tokens()` function (CHARS_PER_TOKEN=3).

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

### Requirement: Token estimation using CHARS_PER_TOKEN

All token estimation within the `ContextAssembler` SHALL use the shared `estimate_tokens()` function from `services/token_counter.py`, which applies the `CHARS_PER_TOKEN=3` constant. This ensures consistent token estimation across query rewriting and context assembly.

#### Scenario: Token estimate is positive for non-empty prompts

- **WHEN** `assemble()` is called with any non-empty persona and query
- **THEN** `AssembledPrompt.token_estimate` SHALL be greater than 0

#### Scenario: Token estimate equals sum of layer estimates

- **WHEN** `assemble()` is called
- **THEN** `AssembledPrompt.token_estimate` SHALL reflect the total estimated tokens across the system and user messages

---

### Requirement: Conversation summary layer conditional inclusion

The `<conversation_summary>` layer SHALL be included in the system message only when `memory_block` is provided and `memory_block.summary_text` is not `None` and not empty. The layer content SHALL be `"Earlier in this conversation:\n{summary_text}"` wrapped in `<conversation_summary>` XML tags. When no summary exists, the `<conversation_summary>` block SHALL be omitted entirely.

#### Scenario: Summary included when present

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text="User asked about machine learning."`
- **THEN** the system message SHALL contain `<conversation_summary>` with text `"Earlier in this conversation:\nUser asked about machine learning."`

#### Scenario: Summary omitted when None

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text=None`
- **THEN** the system message SHALL NOT contain `<conversation_summary>` or `</conversation_summary>`

#### Scenario: Summary omitted when memory_block is None

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** the system message SHALL NOT contain `<conversation_summary>` or `</conversation_summary>`

---

### Requirement: Multi-turn message format

When `memory_block` contains history messages, the messages SHALL be inserted between the system message and the final user message as alternating user/assistant dicts. The final user message SHALL remain the last element in the messages list. This is backward compatible: when `memory_block` is `None` or `memory_block.messages` is empty, the output SHALL be the same 2-message format as before S4-07.

#### Scenario: Multi-turn messages in correct order

- **WHEN** `assemble()` is called with a `memory_block` containing `[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]`
- **THEN** `messages[0]` SHALL have `role=system`
- **AND** `messages[1]` SHALL have `role=user`, `content="Hello"`
- **AND** `messages[2]` SHALL have `role=assistant`, `content="Hi there!"`
- **AND** `messages[3]` SHALL have `role=user` for the current query

#### Scenario: Backward compatible when no memory

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** `messages` SHALL have exactly 2 elements: system and user

#### Scenario: Empty history produces 2-message output

- **WHEN** `assemble()` is called with a `memory_block` containing `messages=[]`
- **THEN** `messages` SHALL have exactly 2 elements: system and user
- **AND** the summary SHALL still appear in the system message if `summary_text` is present

---

### Requirement: Unified conversation memory token accounting

A single `"conversation_memory"` key in `layer_token_counts` SHALL cover the total tokens consumed by conversation memory (summary + history messages combined). The value SHALL equal `memory_block.total_tokens`. The `conversation_summary` layer is added to the system prompt for content rendering, but its token estimate SHALL NOT appear as a separate `"conversation_summary"` entry in `layer_token_counts`.

#### Scenario: Summary-only memory tracked under conversation_memory

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text` but `messages=[]` and `total_tokens=15`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `15`
- **AND** `layer_token_counts` SHALL NOT contain `"conversation_summary"`

#### Scenario: History-only memory tracked under conversation_memory

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text=None`, non-empty `messages`, and `total_tokens=30`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `30`

#### Scenario: Combined summary + history tracked under conversation_memory

- **WHEN** `assemble()` is called with a `memory_block` containing both `summary_text` and `messages` with `total_tokens=50`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `50`
- **AND** `layer_token_counts` SHALL NOT contain `"conversation_summary"`

---

### Requirement: assemble() accepts optional memory_block parameter

The `assemble()` method signature SHALL accept an optional `memory_block` parameter of type `MemoryBlock | None`, defaulting to `None`. When `memory_block` is `None`, the method SHALL produce a two-message prompt (system + current user message). When `memory_block` is provided, the method SHALL include the conversation summary layer when `summary_text` is present, insert history messages between system and user messages, and track memory tokens under the `"conversation_memory"` key.

#### Scenario: Default parameter provides backward compatibility

- **WHEN** `assemble()` is called without the `memory_block` argument
- **THEN** the method SHALL execute without error
- **AND** the output SHALL be identical to calling with `memory_block=None`

#### Scenario: memory_block=None produces a two-message prompt

- **WHEN** `assemble(chunks=[...], query="...", source_map={...}, memory_block=None)` is called
- **THEN** the system message SHALL NOT contain `<conversation_summary>`
- **AND** `messages` SHALL be a list of 2 dicts
- **AND** `layer_token_counts` SHALL NOT contain `"conversation_memory"`

#### Scenario: memory_block with data produces multi-turn output

- **WHEN** `assemble()` is called with a `memory_block` containing summary and history
- **THEN** the system message SHALL contain `<conversation_summary>`
- **AND** `messages` SHALL contain history messages between system and user
- **AND** `layer_token_counts` SHALL contain `"conversation_memory"`

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
