## Purpose

Parsing, date filtering, priority sorting, and selection of promotions from `config/PROMOTIONS.md`. The twin owner manually edits this file to define promotional content that the digital twin may mention in conversations. Introduced by S4-05.

### Requirement: PROMOTIONS.md file format

The `PromotionsService` SHALL parse a markdown file where each promotion is a `## Title` section. Within each section, key-value metadata lines SHALL match the pattern `- **Key:** value`. The recognized metadata keys are `Priority` (high/medium/low), `Valid from` (YYYY-MM-DD), `Valid to` (YYYY-MM-DD), and `Context` (free text). Everything after the last metadata line SHALL be treated as the promotion body text. The parser SHALL split the file by `## ` headers into sections and process each section independently.

#### Scenario: Parse valid multi-section file

- **WHEN** `PromotionsService` is initialized with a markdown string containing two `## Title` sections, each with Priority, Valid from, Valid to, Context metadata, and body text
- **THEN** `parse()` SHALL return a list of 2 `Promotion` objects
- **AND** each object SHALL have `title`, `priority`, `valid_from`, `valid_to`, `context`, and `body` fields correctly populated

#### Scenario: Missing optional fields default gracefully

- **WHEN** a section has only `## Title`, `- **Priority:** low`, and body text (no Valid from, Valid to, or Context)
- **THEN** `valid_from` SHALL be `None`
- **AND** `valid_to` SHALL be `None`
- **AND** `context` SHALL be an empty string

#### Scenario: Body text extracted after metadata lines

- **WHEN** a section contains three metadata lines followed by two lines of body text
- **THEN** the `body` field SHALL contain the two lines of text after metadata, with metadata lines excluded

---

### Requirement: Date filtering

The `PromotionsService` SHALL provide a `get_active()` method that filters promotions by the current date. Promotions whose `valid_to` date is before today SHALL be excluded (expired). Promotions whose `valid_from` date is after today SHALL be excluded (not yet active). Promotions with no `valid_from` SHALL be treated as having no start bound (always active from the past). Promotions with no `valid_to` SHALL be treated as having no end bound (never expires).

#### Scenario: Expired promotion excluded

- **WHEN** today is 2025-06-15 and a promotion has `valid_to` of 2020-06-30
- **THEN** `get_active(today=2025-06-15)` SHALL NOT include that promotion

#### Scenario: Not-yet-active promotion excluded

- **WHEN** today is 2025-06-15 and a promotion has `valid_from` of 2099-01-01
- **THEN** `get_active(today=2025-06-15)` SHALL NOT include that promotion

#### Scenario: No date bounds means always active

- **WHEN** a promotion has no `valid_from` and no `valid_to`
- **THEN** `get_active()` SHALL include that promotion regardless of the current date

#### Scenario: Active promotion within date range included

- **WHEN** today is 2025-06-15 and a promotion has `valid_from` of 2020-01-01 and `valid_to` of 2099-12-31
- **THEN** `get_active(today=2025-06-15)` SHALL include that promotion

---

### Requirement: Priority sorting

Active promotions SHALL be sorted by priority: `high` before `medium` before `low`. Within the same priority level, the sort SHALL be stable, preserving the original file order. This ensures deterministic selection when multiple promotions share the same priority.

#### Scenario: High before medium before low

- **WHEN** three active promotions have priorities high, low, and medium respectively
- **THEN** after sorting, the order SHALL be high, medium, low

#### Scenario: Stable sort within same priority

- **WHEN** two active promotions both have priority `low` and appear in file order as "A" then "B"
- **THEN** after sorting, "A" SHALL appear before "B"

---

### Requirement: Top-N selection

The `get_active()` method SHALL accept a `max_promotions` parameter. After filtering and sorting, the method SHALL return at most `max_promotions` promotions. When `max_promotions` is `None`, all active promotions SHALL be returned. The selection algorithm supports arbitrary N for future extensibility, but the V1 prompt builder (`ContextAssembler._build_promotions_layer()`) uses only the first promotion from the returned list. If more than one promotion is returned (because `max_promotions > 1`), the assembler SHALL use the first and log a structlog warning.

#### Scenario: Select top-1 from multiple active

- **WHEN** three active promotions exist (high, medium, low) and `max_promotions=1`
- **THEN** `get_active()` SHALL return exactly 1 promotion
- **AND** it SHALL be the highest-priority one

#### Scenario: All returned when max_promotions is None

- **WHEN** three active promotions exist and `max_promotions` is not specified
- **THEN** `get_active()` SHALL return all three promotions

---

### Requirement: Fail-safe on missing or empty file

When the promotions file does not exist or is empty, the `PromotionsService` SHALL return an empty list without raising an error. A twin without promotions is a normal operational state.

#### Scenario: Empty file returns empty list

- **WHEN** `PromotionsService` is initialized with an empty string
- **THEN** `get_active()` SHALL return an empty list
- **AND** no error SHALL be raised

#### Scenario: File not found returns empty list

- **WHEN** `PromotionsService.from_file()` is called with a path to a non-existent file
- **THEN** a structlog warning SHALL be emitted
- **AND** `get_active()` SHALL return an empty list
- **AND** no error SHALL be raised

---

### Requirement: Invalid priority defaults to low

When a promotion section has a `Priority` value that is not one of `high`, `medium`, or `low`, the parser SHALL default the priority to `low` and emit a structlog warning. The promotion SHALL NOT be skipped.

#### Scenario: Unrecognized priority falls back to low

- **WHEN** a promotion section has `- **Priority:** urgent`
- **THEN** `parse()` SHALL return the promotion with `priority="low"`
- **AND** a structlog warning SHALL be emitted indicating the invalid priority

---

### Requirement: Invalid date skips the promotion

When a promotion section has a `Valid from` or `Valid to` value that cannot be parsed as a `YYYY-MM-DD` date, the entire promotion SHALL be skipped (not included in the parse result) and a structlog warning SHALL be emitted. This prevents malformed entries from affecting the prompt.

#### Scenario: Non-date string in Valid to

- **WHEN** a promotion section has `- **Valid to:** not-a-date`
- **THEN** `parse()` SHALL NOT include that promotion in the result
- **AND** a structlog warning SHALL be emitted

#### Scenario: Non-date string in Valid from

- **WHEN** a promotion section has `- **Valid from:** tomorrow`
- **THEN** `parse()` SHALL NOT include that promotion in the result

---

### Requirement: Empty body skips the promotion

When a promotion section has metadata but no body text (nothing after the metadata lines), the promotion SHALL be skipped and a structlog warning SHALL be emitted. A promotion without body text has no content to inject into the prompt.

#### Scenario: Section with only metadata and no body

- **WHEN** a promotion section contains `## No Body` and `- **Priority:** high` with no text after the metadata
- **THEN** `parse()` SHALL NOT include that promotion in the result
- **AND** a structlog warning SHALL be emitted
