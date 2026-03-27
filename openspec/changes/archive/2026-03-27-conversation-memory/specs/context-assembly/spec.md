## Purpose

Delta spec for S4-07 Conversation Memory: adds conversation summary layer (layer 6) to the system message, refactors `AssembledPrompt.messages` from 2-message to N-message multi-turn format, adds unified `conversation_memory` token accounting, accepts optional `MemoryBlock` parameter on `assemble()`, and removes the `TODO(S4-07)` placeholder.

## MODIFIED Requirements

### Requirement: Layer ordering in system message

The `ContextAssembler` SHALL build the system message by assembling layers in the following fixed order: safety, identity, soul, behavior, promotions, conversation_summary, citation_instructions, content_guidelines. Each layer SHALL be wrapped in XML tags (`<tag_name>...</tag_name>`). The layer order SHALL NOT be configurable -- it is a design invariant defined by the prompt engineering spec.

#### Scenario: All layers present in correct order

- **WHEN** `assemble()` is called with active promotions, retrieval chunks, and a `memory_block` containing `summary_text`
- **THEN** the system message SHALL contain XML tags in this order: `<system_safety>`, `<identity>`, `<soul>`, `<behavior>`, `<promotions>`, `<conversation_summary>`, `<citation_instructions>`, `<content_guidelines>`
- **AND** each opening tag SHALL have a corresponding closing tag

#### Scenario: Persona layers always present even when empty

- **WHEN** `assemble()` is called with empty identity, soul, and behavior persona content
- **THEN** the system message SHALL still contain `<identity>`, `<soul>`, and `<behavior>` tags (with empty content)
- **AND** `<system_safety>` SHALL always be present with the safety policy text

#### Scenario: Conversation summary placed between promotions and citation instructions

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text`
- **THEN** the `<conversation_summary>` tag SHALL appear after `<promotions>` (or after `<behavior>` if no promotions) and before `<citation_instructions>`
- **CI test:** deterministic, verify tag order in system message string

---

### Requirement: AssembledPrompt output type with metadata

The `assemble()` method SHALL return an `AssembledPrompt` dataclass containing: `messages` (list of OpenAI chat API format dicts), `token_estimate` (total estimated tokens), `included_promotions` (list of Promotion objects injected), `retrieval_chunks_used` (count of chunks that fit within budget), `retrieval_chunks_total` (total chunks available from retrieval), and `layer_token_counts` (dict mapping layer tag names to their individual token estimates). This metadata supports observability and debugging.

When `memory_block` is `None` or has no messages, `messages` SHALL be a list of 2 dicts (system + user), identical to the pre-S4-07 behavior. When `memory_block` contains history messages, `messages` SHALL be a list of N dicts: one system message, zero or more alternating user/assistant history messages, and one final user message containing the retrieval context and current query.

When `memory_block` is provided and has `total_tokens > 0`, `layer_token_counts` SHALL contain a `"conversation_memory"` key with value equal to `memory_block.total_tokens`. The `conversation_summary` layer tokens SHALL be tracked under `"conversation_memory"` (not as a separate `"conversation_summary"` entry) to avoid double-counting summary tokens that appear in the system prompt but are already accounted for in `memory_block.total_tokens`.

#### Scenario: All metadata fields populated

- **WHEN** `assemble()` is called with promotions, chunks, and a `memory_block`
- **THEN** `AssembledPrompt` SHALL have non-null values for all metadata fields
- **AND** `layer_token_counts` SHALL contain entries for `system_safety`, `identity`, `soul`, `behavior`, `promotions`, `citation_instructions`, `content_guidelines`, and `conversation_memory`

#### Scenario: Messages as 2 dicts when no memory block

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** `AssembledPrompt.messages` SHALL be a list of 2 dicts: one with `role=system` and one with `role=user`
- **AND** each dict SHALL have `role` and `content` string keys

#### Scenario: Messages as N dicts with memory block history

- **WHEN** `assemble()` is called with a `memory_block` containing 2 history messages (user + assistant)
- **THEN** `AssembledPrompt.messages` SHALL be a list of 4 dicts: system, user (history), assistant (history), user (current query)
- **AND** each dict SHALL have `role` and `content` string keys
- **CI test:** deterministic, verify message count and roles

#### Scenario: conversation_memory key in layer_token_counts

- **WHEN** `assemble()` is called with a `memory_block` having `total_tokens=50`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `50`
- **AND** `layer_token_counts` SHALL NOT contain a `"conversation_summary"` key
- **CI test:** deterministic, verify token accounting

#### Scenario: No conversation_memory key when memory_block is None

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** `layer_token_counts` SHALL NOT contain a `"conversation_memory"` key
- **CI test:** deterministic, verify absence of key

---

## REMOVED Requirements

### Requirement: Conversation memory slot reservation

**Reason:** The `TODO(S4-07)` placeholder is replaced by the actual conversation summary layer implementation. The placeholder was introduced by S4-05 as a forward reference; S4-07 fulfills it.

**Migration:** Remove the `TODO(S4-07)` comment from the layer assembly sequence and replace it with the `_build_layer("conversation_summary", ...)` call that conditionally includes the conversation summary in the system message.

---

## ADDED Requirements

### Requirement: Conversation summary layer conditional inclusion

The `<conversation_summary>` layer SHALL be included in the system message only when `memory_block` is provided and `memory_block.summary_text` is not `None` and not empty. The layer content SHALL be `"Earlier in this conversation:\n{summary_text}"` wrapped in `<conversation_summary>` XML tags. When no summary exists (first message, short session, or `memory_block=None`), the `<conversation_summary>` block SHALL be omitted entirely (not present as an empty tag).

#### Scenario: Summary included when present

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text="User asked about machine learning."`
- **THEN** the system message SHALL contain `<conversation_summary>` with text `"Earlier in this conversation:\nUser asked about machine learning."`
- **CI test:** deterministic, verify tag content

#### Scenario: Summary omitted when None

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text=None`
- **THEN** the system message SHALL NOT contain `<conversation_summary>` or `</conversation_summary>`
- **CI test:** deterministic, verify absence

#### Scenario: Summary omitted when memory_block is None

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** the system message SHALL NOT contain `<conversation_summary>` or `</conversation_summary>`
- **CI test:** deterministic, verify backward compatibility

---

### Requirement: Multi-turn message format

When `memory_block` contains history messages (`memory_block.messages` is a non-empty list), the messages SHALL be inserted between the system message and the final user message as alternating user/assistant dicts. Each history message dict SHALL have `role` (either `"user"` or `"assistant"`) and `content` (the message text). The final user message (containing retrieval context and current query) SHALL remain the last element in the messages list. This is backward compatible: when `memory_block` is `None` or `memory_block.messages` is empty, the output SHALL be the same 2-message format as before S4-07 (system + user).

#### Scenario: Multi-turn messages in correct order

- **WHEN** `assemble()` is called with a `memory_block` containing `[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}]`
- **THEN** `messages[0]` SHALL have `role=system`
- **AND** `messages[1]` SHALL have `role=user`, `content="Hello"`
- **AND** `messages[2]` SHALL have `role=assistant`, `content="Hi there!"`
- **AND** `messages[3]` SHALL have `role=user` (current query with retrieval context)
- **CI test:** deterministic, verify message structure

#### Scenario: Backward compatible when no memory

- **WHEN** `assemble()` is called with `memory_block=None`
- **THEN** `messages` SHALL have exactly 2 elements: system and user
- **AND** the output SHALL be identical to the pre-S4-07 format
- **CI test:** deterministic, verify 2-message output

#### Scenario: Empty history produces 2-message output

- **WHEN** `assemble()` is called with a `memory_block` containing `messages=[]` (summary only, no verbatim history)
- **THEN** `messages` SHALL have exactly 2 elements: system and user
- **AND** the summary SHALL still appear in the system message if `summary_text` is present
- **CI test:** deterministic, verify 2-message output with summary in system

---

### Requirement: Unified conversation memory token accounting

A single `"conversation_memory"` key in `layer_token_counts` SHALL cover the total tokens consumed by conversation memory (summary + history messages combined). The value SHALL equal `memory_block.total_tokens`. The `conversation_summary` layer is added to the system prompt for content rendering, but its token estimate SHALL NOT appear as a separate `"conversation_summary"` entry in `layer_token_counts`. Instead, when `memory_block` is not `None` and `memory_block.total_tokens > 0`, any `"conversation_summary"` entry SHALL be removed from `layer_token_counts` and replaced by the single `"conversation_memory"` entry. This prevents double-counting when summary tokens are already included in `memory_block.total_tokens`.

#### Scenario: Summary-only memory tracked under conversation_memory

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text` but `messages=[]` and `total_tokens=15`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `15`
- **AND** `layer_token_counts` SHALL NOT contain `"conversation_summary"`
- **CI test:** deterministic, verify single key

#### Scenario: History-only memory tracked under conversation_memory

- **WHEN** `assemble()` is called with a `memory_block` containing `summary_text=None`, non-empty `messages`, and `total_tokens=30`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `30`
- **CI test:** deterministic, verify token value

#### Scenario: Combined summary + history tracked under conversation_memory

- **WHEN** `assemble()` is called with a `memory_block` containing both `summary_text` and `messages` with `total_tokens=50`
- **THEN** `layer_token_counts["conversation_memory"]` SHALL be `50`
- **AND** `layer_token_counts` SHALL NOT contain `"conversation_summary"`
- **CI test:** deterministic, verify unified accounting

---

### Requirement: assemble() accepts optional memory_block parameter

The `assemble()` method signature SHALL accept an optional `memory_block` parameter of type `MemoryBlock | None`, defaulting to `None`. When `memory_block` is `None`, the method SHALL produce output identical to the pre-S4-07 behavior (backward compatible). When `memory_block` is provided, the method SHALL: (1) include the conversation summary layer in the system message if `summary_text` is present, (2) insert history messages between system and user messages, and (3) track memory tokens under the `"conversation_memory"` key.

#### Scenario: Default parameter provides backward compatibility

- **WHEN** `assemble()` is called without the `memory_block` argument
- **THEN** the method SHALL execute without error
- **AND** the output SHALL be identical to calling with `memory_block=None`
- **CI test:** deterministic, verify no-arg backward compat

#### Scenario: memory_block=None produces pre-S4-07 output

- **WHEN** `assemble(chunks=[...], query="...", source_map={...}, memory_block=None)` is called
- **THEN** the system message SHALL NOT contain `<conversation_summary>`
- **AND** `messages` SHALL be a list of 2 dicts
- **AND** `layer_token_counts` SHALL NOT contain `"conversation_memory"`
- **CI test:** deterministic, verify output structure

#### Scenario: memory_block with data produces multi-turn output

- **WHEN** `assemble()` is called with a `memory_block` containing summary and history
- **THEN** the system message SHALL contain `<conversation_summary>`
- **AND** `messages` SHALL contain history messages between system and user
- **AND** `layer_token_counts` SHALL contain `"conversation_memory"`
- **CI test:** deterministic, verify all three effects

---

## Stable Behavior for Test Coverage

The following stable behavior MUST be covered by tests before this change is archived:

1. **Layer order** -- conversation_summary appears between promotions and citation_instructions (CI unit test)
2. **Conditional summary inclusion** -- present when summary_text exists, absent otherwise (CI unit test)
3. **Multi-turn message format** -- correct message count and roles with history (CI unit test)
4. **Backward compatibility** -- memory_block=None produces identical output to pre-S4-07 (CI unit test)
5. **Unified token accounting** -- single conversation_memory key, no conversation_summary key (CI unit test)
6. **Summary-only and history-only edge cases** -- correct behavior for each (CI unit test)
