## Purpose

Product recommendation mechanism using `[product:N]` markers in LLM output. The LLM optionally places markers when a product recommendation is contextually appropriate. The backend extracts markers, resolves them to catalog items, and delivers structured product data. Mirrors the `[source:N]` citation pattern. Max one recommendation per response. Introduced by S6-01.

## ADDED Requirements

### Requirement: Product marker format

The LLM SHALL reference products using `[product:N]` markers where N is a 1-based ordinal index corresponding to the product's position in the `available_products` prompt block. The marker format SHALL match the regex `\[product:(\d+)\]`.

#### Scenario: LLM output contains valid product marker

- **WHEN** the LLM generates text containing `[product:1]`
- **THEN** the marker SHALL match the regex `\[product:(\d+)\]`
- **AND** the extracted index SHALL be `1`

#### Scenario: Product markers do not collide with citation markers

- **WHEN** the LLM output contains both `[source:1]` and `[product:1]`
- **THEN** `[source:1]` SHALL be recognized only by the citation service
- **AND** `[product:1]` SHALL be recognized only by the product recommendation service

---

### Requirement: Product marker extraction

`ProductRecommendationService.extract()` SHALL parse all `[product:N]` markers from the LLM response text. The method SHALL accept `content: str` and `catalog_items: list[CatalogItemInfo]`. Invalid indices (N < 1 or N > length of `catalog_items`) SHALL be silently ignored. An empty `catalog_items` list SHALL produce an empty result.

#### Scenario: Valid marker extracted

- **WHEN** `extract()` is called with text `"Check out My Book [product:1]"` and `catalog_items` containing one item at index 1
- **THEN** the result SHALL contain 1 `ProductRecommendation` with the correct catalog item data

#### Scenario: Invalid index zero silently ignored

- **WHEN** the text contains `[product:0]` and `catalog_items` has items
- **THEN** the marker SHALL be silently ignored
- **AND** the result SHALL be empty

#### Scenario: Out-of-range index silently ignored

- **WHEN** the text contains `[product:5]` but `catalog_items` has only 2 items
- **THEN** the marker SHALL be silently ignored
- **AND** the result SHALL be empty

#### Scenario: Empty catalog items returns empty result

- **WHEN** `extract()` is called with text containing `[product:1]` but `catalog_items` is an empty list
- **THEN** the result SHALL be an empty list

#### Scenario: No markers in text returns empty result

- **WHEN** `extract()` is called with text containing no `[product:N]` markers
- **THEN** the result SHALL be an empty list

---

### Requirement: Max one recommendation per response

The `extract()` method SHALL return at most 1 `ProductRecommendation` per call. When the LLM places multiple `[product:N]` markers in a single response, only the first valid marker (by order of appearance in the text) SHALL be extracted. Subsequent valid markers SHALL be ignored.

#### Scenario: Multiple markers yields only first

- **WHEN** the text contains `[product:1]` followed by `[product:2]` and both indices are valid
- **THEN** the result SHALL contain exactly 1 recommendation
- **AND** it SHALL correspond to `[product:1]` (first valid marker)

#### Scenario: First marker invalid, second valid

- **WHEN** the text contains `[product:99]` (invalid) followed by `[product:1]` (valid)
- **THEN** the result SHALL contain exactly 1 recommendation corresponding to `[product:1]`

---

### Requirement: Deduplication by catalog_item_id

When the same product is referenced multiple times (same `catalog_item_id`), only the first occurrence SHALL be kept. Deduplication operates before the max-1 limit, so duplicate markers for the same product do not consume the limit.

#### Scenario: Same product referenced twice

- **WHEN** the text contains `[product:1]` at two different positions and both resolve to the same catalog item
- **THEN** the result SHALL contain exactly 1 recommendation (deduplicated)

---

### Requirement: strip_markers removes product markers from text

`ProductRecommendationService.strip_markers()` SHALL remove all `[product:N]` markers from the given text. This is analogous to how `[source:N]` markers are stripped after extraction.

#### Scenario: Single marker stripped

- **WHEN** `strip_markers()` is called with `"Check out My Book [product:1] for details."`
- **THEN** the result SHALL be `"Check out My Book  for details."`

#### Scenario: Multiple markers stripped

- **WHEN** `strip_markers()` is called with `"Book [product:1] and event [product:2]."`
- **THEN** the result SHALL be `"Book  and event ."`

#### Scenario: No markers unchanged

- **WHEN** `strip_markers()` is called with text containing no `[product:N]` markers
- **THEN** the result SHALL be identical to the input

---

### Requirement: ProductRecommendation dataclass

Each product recommendation SHALL be represented as a `ProductRecommendation` dataclass with the following fields:

- `index` — int, 1-based position in the `available_products` list
- `catalog_item_id` — UUID of the catalog item
- `name` — str, name of the catalog item
- `sku` — str, SKU of the catalog item
- `item_type` — CatalogItemType (book/course/event/merch/other)
- `url` — str or null, purchase/store URL
- `image_url` — str or null, product image URL
- `text_recommendation` — str, formatted as `"{name} ({item_type})"` (e.g., `"AI in Practice (book)"`)

#### Scenario: ProductRecommendation fields populated correctly

- **WHEN** a `ProductRecommendation` is created for a catalog item with name "AI in Practice", SKU "AI-PRACTICE-2026", item_type "book", url "https://store.example.com"
- **THEN** `text_recommendation` SHALL be `"AI in Practice (book)"`
- **AND** all other fields SHALL match the source catalog item data

#### Scenario: Catalog item without URL

- **WHEN** a `ProductRecommendation` is created for a catalog item with `url=None`
- **THEN** `url` SHALL be `None`
- **AND** `text_recommendation` SHALL still be formatted with name and type

---

### Requirement: to_dict serialization

The `ProductRecommendation` dataclass SHALL provide a `to_dict()` method that serializes the recommendation to a plain dict suitable for JSON persistence. The `catalog_item_id` SHALL be serialized as a string. The `item_type` SHALL be serialized as its string value (e.g., `"book"`).

#### Scenario: to_dict produces JSON-serializable dict

- **WHEN** `to_dict()` is called on a `ProductRecommendation`
- **THEN** the result SHALL be a dict with keys: `index`, `catalog_item_id` (string), `name`, `sku`, `item_type` (string value), `url`, `image_url`, `text_recommendation`
- **AND** all values SHALL be JSON-serializable primitives

---

### Requirement: Products persistence in Message JSONB

Resolved product recommendations SHALL be stored in the `Message.products` JSONB field as an array of product recommendation dicts (via `to_dict()`). When no recommendations are produced, the field SHALL store `None` (null). The `Message` model SHALL gain a `products: JSONB, nullable` column via Alembic migration.

#### Scenario: Product recommendation persisted to JSONB

- **WHEN** the LLM output produces 1 resolved product recommendation
- **THEN** `Message.products` SHALL contain a JSON array with 1 product recommendation dict
- **AND** the dict SHALL include `index`, `catalog_item_id`, `name`, `sku`, `item_type`, `url`, `image_url`, `text_recommendation`

#### Scenario: No recommendation persisted as None

- **WHEN** the LLM output contains no `[product:N]` markers
- **THEN** `Message.products` SHALL be `None` (null)

#### Scenario: Message response schemas include products

- **WHEN** `GET /api/chat/sessions/:id` returns message history
- **THEN** the `products` field of assistant messages SHALL be present (nullable)
- **AND** SHALL contain the persisted product recommendation array or null
