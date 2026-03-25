## Purpose

Heuristic post-processing to classify response sentences as fact (cited), promo (matches promotion keywords), or inference (default). Produces character-level spans stored in `message.content_type_spans` for frontend rendering. Introduced by S4-05.

## ADDED Requirements

### Requirement: Sentence-level classification

The `compute_content_type_spans()` function SHALL split the LLM response text into sentences and classify each sentence into one of three content types: `"fact"`, `"promo"`, or `"inference"`. Sentence boundaries SHALL be detected by punctuation heuristic (`.`, `!`, `?` followed by whitespace or end-of-string, respecting common abbreviations). The function SHALL return a list of `ContentTypeSpan` objects, each containing `start` (int), `end` (int), and `type` (str) representing character positions in the response text.

#### Scenario: Single fact sentence classified

- **WHEN** the response text is "The sky is blue [source:1]."
- **THEN** `compute_content_type_spans()` SHALL return one span with `type="fact"` covering the entire sentence

#### Scenario: Single inference sentence classified

- **WHEN** the response text is "I think this is interesting."
- **THEN** `compute_content_type_spans()` SHALL return one span with `type="inference"` covering the entire text
- **AND** `start` SHALL be 0 and `end` SHALL equal the length of the text

#### Scenario: Mixed types across sentences

- **WHEN** the response text contains a fact sentence, an inference sentence, and a promo sentence
- **THEN** `compute_content_type_spans()` SHALL return spans with the correct type for each sentence

---

### Requirement: Fact classification rule

A sentence SHALL be classified as `"fact"` when it contains the pattern `[source:N]` (where N is one or more digits). The presence of a citation marker is the sole criterion for fact classification.

#### Scenario: Citation marker triggers fact classification

- **WHEN** a sentence contains "[source:1]"
- **THEN** it SHALL be classified as `"fact"`

#### Scenario: Multiple citation markers still fact

- **WHEN** a sentence contains "[source:1]" and "[source:3]"
- **THEN** it SHALL be classified as `"fact"`

#### Scenario: No citation marker means not a fact

- **WHEN** a sentence does not contain any `[source:N]` pattern
- **THEN** it SHALL NOT be classified as `"fact"` (may be promo or inference)

---

### Requirement: Promo classification rule

A sentence SHALL be classified as `"promo"` when it matches 2 or more keywords (case-insensitive) extracted from the active promotions' `title` and `body` fields. Keywords are significant words from the promotion text (common stopwords excluded). The minimum threshold of 2 keyword matches reduces false positives from common words. When no promotions were included in the prompt, promo matching SHALL be skipped entirely and no sentences SHALL be classified as `"promo"`.

#### Scenario: Two keyword matches triggers promo

- **WHEN** a promotion has title "AI Book" and body "Buy the AI Book today"
- **AND** a sentence contains "the AI Book"
- **THEN** it SHALL be classified as `"promo"` (matches "AI" and "Book")

#### Scenario: Single keyword match not enough

- **WHEN** a promotion has title "AI Book" and body "Buy the AI Book today"
- **AND** a sentence contains only "AI is transforming the world"
- **THEN** it SHALL NOT be classified as `"promo"` (only 1 keyword match)

#### Scenario: No promotions skips promo matching

- **WHEN** `compute_content_type_spans()` is called with an empty promotions list
- **THEN** no sentences SHALL be classified as `"promo"` regardless of their content

---

### Requirement: Inference as default classification

Any sentence that is not classified as `"fact"` (no `[source:N]` pattern) and not classified as `"promo"` (fewer than 2 keyword matches or no promotions) SHALL be classified as `"inference"`. This is the default fallback type.

#### Scenario: Plain sentence classified as inference

- **WHEN** a sentence has no citation markers and no promotion keyword matches
- **THEN** it SHALL be classified as `"inference"`

---

### Requirement: Fact wins over promo on overlap

When a sentence qualifies as both `"fact"` (contains `[source:N]`) and `"promo"` (matches promotion keywords), the classification SHALL be `"fact"`. A cited statement is verifiable — labeling it as promo would undermine trust. The citation signal is the more useful one for the frontend.

#### Scenario: Citation plus promo keywords resolves to fact

- **WHEN** a sentence contains "[source:1]" and also matches 2+ promotion keywords
- **THEN** it SHALL be classified as `"fact"`, not `"promo"`

---

### Requirement: Adjacent same-type spans merged

After individual sentence classification, adjacent sentences with the same content type SHALL be merged into a single span. This reduces the number of spans in the output and simplifies frontend rendering.

#### Scenario: Two adjacent inference sentences merged

- **WHEN** the response text is "First inference. Second inference."
- **THEN** `compute_content_type_spans()` SHALL return 1 span of type `"inference"` covering the entire text

#### Scenario: Different types not merged

- **WHEN** the response text is "A fact [source:1]. An inference."
- **THEN** `compute_content_type_spans()` SHALL return 2 spans: one `"fact"` and one `"inference"`

---

### Requirement: Full text coverage with no gaps

The union of all returned spans SHALL cover every character in the response text. There SHALL be no gaps (uncovered characters) and no overlaps (characters covered by multiple spans). This invariant ensures the frontend can render the entire response with content type annotations.

#### Scenario: Full coverage verified

- **WHEN** `compute_content_type_spans()` is called with any non-empty text
- **THEN** the set of all character positions across all spans SHALL equal the set `{0, 1, ..., len(text)-1}`

#### Scenario: No overlapping spans

- **WHEN** `compute_content_type_spans()` is called
- **THEN** for any two spans `a` and `b`, the ranges `[a.start, a.end)` and `[b.start, b.end)` SHALL NOT overlap

---

### Requirement: Empty text produces empty spans

When the response text is empty, `compute_content_type_spans()` SHALL return an empty list. No spans SHALL be produced for empty input.

#### Scenario: Empty string returns empty list

- **WHEN** `compute_content_type_spans("")` is called
- **THEN** the return value SHALL be an empty list

---

### Requirement: Storage in message.content_type_spans

The content type spans SHALL be stored in the existing `message.content_type_spans` JSONB column on the messages table. The column is already present in the schema (nullable, currently unused). Each span SHALL be serialized as `{"start": int, "end": int, "type": str}`. The column SHALL be populated on assistant messages after the LLM response is received and content type classification completes.

#### Scenario: Spans persisted on assistant message

- **WHEN** an assistant message is finalized with `status=complete`
- **THEN** the `content_type_spans` column SHALL contain the serialized span array
- **AND** the array SHALL not be null for complete messages that went through content type classification

---

### Requirement: Spans observable via session history API

The persisted `content_type_spans` SHALL be returned to the frontend via the existing `GET /api/chat/sessions/:id` endpoint as the `content_types` field (defined in `docs/spec.md` saved message format). No new API endpoint is required — the existing session history response already includes this field.

#### Scenario: Session history returns content type spans

- **WHEN** the frontend calls `GET /api/chat/sessions/:id` after a complete assistant message
- **THEN** the response SHALL include the `content_types` field with the persisted spans
- **AND** the spans SHALL match the format `{spans: [{start, end, type}]}`
