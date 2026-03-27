# S6-01: Commerce Backend — Catalog + Recommendations — Design Spec

## Story

> Admin API: CRUD catalog_items. Source ↔ catalog_item linking. Citation enrichment with purchase links. PROMOTIONS.md + catalog integration for native delivery. Citation takes priority over commercial link. No more than one recommendation per response.

## Approach

**Full integration within story scope: CRUD + citation enrichment + product markers + PROMOTIONS.md ↔ catalog via SKU.** Two independent delivery mechanisms for commercial links: (1) automatic citation enrichment when a cited source has a linked catalog item, and (2) optional `[product:N]` markers for standalone product recommendations driven by PROMOTIONS.md + catalog integration. A new `ProductRecommendationService` handles product marker extraction, mirroring the existing `CitationService` pattern.

**Why this approach:**

- Two mechanisms serve different use cases: citation enrichment is automatic and knowledge-driven (source cited → purchase link added), while product recommendations are contextual and promotion-driven (PROMOTIONS.md + catalog → LLM decides if relevant).
- The `[product:N]` marker pattern is consistent with the existing `[source:N]` citation pattern — same architecture, same anti-hallucination guarantee (LLM never generates URLs).
- SKU-based matching between PROMOTIONS.md and catalog items is human-readable for manual file editing (v1) and more stable than name matching (SKU doesn't change when a product is renamed).
- Hybrid marker strategy (Option C from brainstorm): LLM decides whether to recommend — if it places `[product:N]`, the backend enriches it; if not, nothing is forced. This satisfies "not every response has recommendation" naturally.

**Rejected alternatives:**

- **Minimal integration (CRUD + citation enrichment only):** Does not fulfill "PROMOTIONS.md + catalog integration for native delivery." Recommendations would remain text-only without structured product links.
- **DB-first promotions (move promotions to database):** Scope creep. The plan states "files managed manually in v1." Migrating promotions to DB is a separate concern, not part of this story.
- **Name-based matching for PROMOTIONS.md ↔ catalog:** Fragile — product renames break the link silently. SKU is stable by design.
- **Mandatory `[product:N]` markers (Option A from brainstorm):** Forces LLM to always use markers when products are in the prompt, which may produce unnatural text. Hybrid approach gives LLM autonomy.
- **Pure metadata recommendations without markers (Option B from brainstorm):** No way to confirm LLM actually mentioned the product. May produce irrelevant product cards below a message that doesn't discuss the product.

## Design Decisions

| #   | Decision                                      | Choice                                                                                            | Rationale                                                                                                                                                                                                     |
| --- | --------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Catalog item identifier for PROMOTIONS.md     | `sku` field (String(64), required) on CatalogItem with per-agent uniqueness                       | Human-readable for manual editing, stable across renames, and scoped to the twin that owns the catalog. UUID is reliable but unreadable; name matching is fragile. SKU is the practical middle ground for v1. |
| D2  | Recommendation delivery mechanism             | Hybrid `[product:N]` markers — LLM optionally places marker if recommending                       | LLM decides if recommendation is appropriate. If marker present → backend enriches with URL. If absent → no forced product card. Consistent with `[source:N]` citation pattern.                               |
| D3  | Citation enrichment trigger                   | Automatic: source has active catalog_item with url → purchase_url in citation                     | Zero configuration needed. Source ↔ catalog_item link (existing FK) is the sole trigger. Inactive or expired items are excluded.                                                                              |
| D4  | "Citation takes priority" implementation      | Knowledge citation is primary; purchase link is supplementary metadata                            | Citation remains knowledge-first (source_title, anchor). Purchase link is an additional field, not a replacement. Frontend decides how to render (e.g., "Buy" button next to citation).                       |
| D5  | Max recommendations per response              | Enforced at two levels: prompt (max_promotions=1) + extraction (first marker only)                | Belt and suspenders. Prompt-level prevents LLM from seeing multiple promo contexts. Extraction-level prevents edge cases where LLM places multiple markers despite instructions.                              |
| D6  | Catalog items in prompt scope                 | All active, non-expired catalog items included                                                    | One twin = one prototype = small catalog (5–20 items). No filtering needed. Token overhead is ~200–400 tokens — negligible.                                                                                   |
| D7  | PROMOTIONS.md SKU not found in DB             | Warning in structlog, promotion works as text-only (no `[product:N]`)                             | Graceful degradation. Owner may have a typo or the item may not be created yet. The promotion still provides context hints to LLM.                                                                            |
| D8  | Catalog item soft-deleted with linked sources | Soft delete keeps FK intact; `ON DELETE SET NULL` is a safety net for hard deletes only           | Sources remain linked (restorable). Citation enrichment disabled by application-level `is_active`/`deleted_at` filtering. Published snapshots not affected.                                                   |
| D9  | SSE event for product recommendations         | New `type: "products"` event after `citations`, before `done`                                     | Separate from citations — different data structure, different frontend rendering. Consistent with existing SSE event pattern.                                                                                 |
| D10 | Source ↔ catalog linking API                  | Existing: `catalog_item_id` in source upload. New: `PATCH /api/admin/sources/{id}` for re-linking | Upload-time linking already works. PATCH enables linking existing sources without re-upload.                                                                                                                  |
| D11 | Catalog CRUD API style                        | PATCH semantics (partial update), soft delete, pagination with limit/offset                       | Matches existing admin API patterns (batch-jobs list, source list). No new patterns introduced.                                                                                                               |
| D12 | Product recommendation tracking in audit      | `recommended_product_ids: list[UUID]` in audit log metadata                                       | Enables analytics: which products are recommended, how often, in what contexts. Stored alongside existing `source_ids` and `snapshot_id`.                                                                     |

## Data Model Changes

### CatalogItem — new field

```text
sku: String(64), not null, indexed
UNIQUE(agent_id, sku)
```

Alembic migration adds the column with a plain index (`ix_catalog_items_sku`) plus a composite unique constraint on `(agent_id, sku)`. Existing rows (if any) MUST be backfilled with unique SKU values using the full UUID before the per-agent unique constraint is created (`sku = 'LEGACY-' || id::text` — full UUID guarantees uniqueness inside the existing default agent scope). Existing CatalogItem fields remain unchanged: `name`, `description`, `item_type`, `url`, `image_url`, `is_active`, `valid_from`, `valid_until`.

**Date type note:** The existing model stores `valid_from` and `valid_until` as `datetime` (not `date`). API schemas accept `date` for user convenience, but service-layer filtering MUST handle `datetime` ↔ `date` comparison safely (convert `datetime` to `date` before comparison).

### Source — FK behavior

```python
catalog_item_id: ForeignKey("catalog_items.id", ondelete="SET NULL")
```

The FK already exists. Ensure `ondelete="SET NULL"` is set (verify in migration; add if missing).

### Message — new JSONB field

```python
products: JSONB, nullable
```

Stores serialized `ProductRecommendation` list alongside existing `citations: JSONB`. Migration adds the column. Chat schemas (`MessageResponse`, `MessageInHistory`) gain an optional `products` field. Audit log metadata gains `recommended_product_ids: list[UUID]`.

### No new tables

All data fits existing tables. No new tables required.

## Admin API — Catalog CRUD

### Endpoints

| Method | Path                   | Description                              | Response |
| ------ | ---------------------- | ---------------------------------------- | -------- |
| GET    | /api/admin/catalog     | List catalog items (paginated, filtered) | JSON     |
| GET    | /api/admin/catalog/:id | Catalog item detail with linked sources  | JSON     |
| POST   | /api/admin/catalog     | Create catalog item                      | JSON     |
| PATCH  | /api/admin/catalog/:id | Update catalog item (partial)            | JSON     |
| DELETE | /api/admin/catalog/:id | Soft delete catalog item                 | JSON     |

### Schemas

**CatalogItemCreate** (request body for POST):

- `sku: str` — required, 1–64 chars, unique
- `name: str` — required, 1–255 chars
- `description: str | None`
- `item_type: CatalogItemType` — required (book / course / event / merch / other)
- `url: str | None` — purchase/store URL, max 2048 chars
- `image_url: str | None` — product image URL, max 2048 chars
- `valid_from: datetime | None` — matches the DB model type (`datetime`, not `date`)
- `valid_until: datetime | None` — matches the DB model type (`datetime`, not `date`)

**CatalogItemUpdate** (request body for PATCH):

- All fields optional. Only provided fields are updated.

**CatalogItemResponse** (list item):

- All model fields + `id`, `is_active`, `created_at`, `updated_at`, `linked_sources_count: int`

**CatalogItemDetail** (single item):

- CatalogItemResponse + `linked_sources: list[LinkedSourceInfo]`
- `LinkedSourceInfo`: `id`, `title`, `source_type`, `status`

### List endpoint query parameters

- `item_type: CatalogItemType | None` — filter by type
- `is_active: bool` — default `true`
- `limit: int` — default 20, max 100
- `offset: int` — default 0

### Source re-linking

**PATCH /api/admin/sources/:id** — new endpoint:

- Request body: `{ "catalog_item_id": "uuid | null" }`
- Uses `exclude_unset` Pydantic pattern: if `catalog_item_id` is absent from the body, it is not changed; if explicitly `null`, it unlinks the source from the catalog item; if a UUID, it links to that catalog item
- Returns updated `SourceListItem`

## Citation Enrichment

### Changes to `CitationService`

**Extended `SourceInfo` dataclass:**

```python
SourceInfo:
  id: UUID
  title: str
  public_url: str | None
  source_type: str
  + catalog_item_url: str | None
  + catalog_item_name: str | None
  + catalog_item_type: str | None
  + catalog_item_active: bool       # False if item is inactive or expired
```

**Extended `Citation` dataclass:**

```python
Citation:
  ... (existing fields unchanged)
  + purchase_url: str | None        # From catalog_item.url (only if active)
  + purchase_title: str | None      # From catalog_item.name
  + catalog_item_type: str | None   # book / course / event / merch / other
```

**Enrichment logic in `extract()`:**

- After building a Citation, check if `source_info.catalog_item_active` is True
- If yes → populate `purchase_title` and `catalog_item_type`
- If `catalog_item_url` is not None → also populate `purchase_url`
- If no → leave purchase fields as None

**Source map population (caller side):**

- Query: `SELECT sources.*, catalog_items.* FROM sources LEFT JOIN catalog_items ON sources.catalog_item_id = catalog_items.id WHERE sources.id IN (:source_ids)`
- Filter: `catalog_items.is_active = true AND (valid_from IS NULL OR valid_from <= today) AND (valid_until IS NULL OR valid_until >= today)`
- Build `source_map` with catalog item data included

## Product Recommendation Mechanism

### New service: `ProductRecommendationService`

Location: `backend/app/services/product_recommendation.py`

Stateless service with static methods, mirroring `CitationService`.

**Dataclass `ProductRecommendation`:**

```python
ProductRecommendation:
  index: int                     # 1-based position in available_products list
  catalog_item_id: UUID
  name: str
  sku: str
  item_type: CatalogItemType
  url: str | None
  image_url: str | None
  text_recommendation: str       # Formatted: "AI in Practice (book)"
```

**Method `extract(response_text: str, catalog_items: list[CatalogItemInfo]) -> list[ProductRecommendation]`:**

- Parse `[product:N]` markers using regex `\[product:(\d+)\]`
- Map indices to catalog_items list (1-based)
- Invalid indices (0, out-of-range) silently ignored
- Deduplicate by catalog_item_id (first occurrence wins)
- **Limit to first valid recommendation only** (max 1 per response)
- Return list (0 or 1 items)

**Method `strip_markers(response_text: str) -> str`:**

- Remove `[product:N]` markers from final response text
- Analogous to how `[source:N]` markers are stripped after extraction

### Dataclass `CatalogItemInfo` (prompt-time data)

```python
CatalogItemInfo:
  id: UUID
  sku: str
  name: str
  item_type: CatalogItemType
  url: str | None
  image_url: str | None
```

Used by ContextAssembler to build the `available_products` prompt block and by ProductRecommendationService to resolve `[product:N]` indices.

## PROMOTIONS.md ↔ Catalog Integration

### Extended PROMOTIONS.md format

```markdown
## New Book: "AI in Practice"

- **Priority:** high
- **Valid from:** 2026-01-15
- **Valid to:** 2026-06-30
- **Catalog item:** AI-PRACTICE-2026
- **Context:** When the conversation touches AI, machine learning, or practical applications.

My new book "AI in Practice" covers real-world applications of modern AI systems.
```

New optional metadata field: `Catalog item:` containing the SKU of a catalog item.

### Changes to `PromotionsService`

**Extended `Promotion` dataclass:**

```
Promotion:
  title: str
  priority: str
  valid_from: date | None
  valid_to: date | None
  context: str
  body: str
  + catalog_item_sku: str | None
```

**Parser changes:**

- Extract `Catalog item:` metadata line (case-insensitive key matching, consistent with existing parser)
- Store as `catalog_item_sku` (stripped, as-is)
- Missing field → `None` (backward-compatible)

### SKU resolution

Performed in `ContextAssembler` during prompt assembly:

1. Load all active, non-expired catalog items from DB → `dict[sku, CatalogItemInfo]`
2. For each active promotion with `catalog_item_sku`:
   - Look up in the dict
   - If found → associate the catalog item's `[product:N]` index with this promotion
   - If not found → log warning via structlog, promotion works as text-only
3. Promotions without `catalog_item_sku` work as before (text context hints, no product marker)

## Prompt Assembly (ContextAssembler Changes)

### New prompt layer: `available_products`

Placed after `promotions`, before `conversation_summary`:

```xml
<available_products>
The following products from the prototype's catalog are available.
If a promotion context suggests mentioning a product and it is relevant
to the current conversation, reference it using its [product:N] marker.
Only recommend when naturally appropriate. Never force a recommendation.
Maximum one product recommendation per response.

[product:1] "AI in Practice" (book) - SKU: AI-PRACTICE-2026
[product:2] "Tech Summit 2026 Ticket" (event) - SKU: TECHSUMMIT-2026
</available_products>
```

### New prompt layer: `product_instructions`

Placed after `citation_instructions`:

```xml
<product_instructions>
When recommending a product, place [product:N] after mentioning it.
Do NOT generate URLs - the system substitutes real links.
Do NOT recommend products not listed in available_products.
If no product is relevant to the conversation, do not recommend anything.
A recommendation should feel natural, like a real person mentioning
something they genuinely find relevant - not like an advertisement.
</product_instructions>
```

This block is only included when `available_products` is non-empty.

### Updated layer order in system message

1. `system_safety`
2. `identity`
3. `soul`
4. `behavior`
5. `promotions` (context hints — when to recommend)
6. `available_products` (what can be recommended + `[product:N]` indices)
7. `conversation_summary` (memory block)
8. `citation_instructions`
9. `product_instructions`
10. `content_guidelines`

### Token budget

- `available_products` is a fixed overhead (~200–400 tokens for 10–20 items)
- Does not compete with `retrieval_context_budget`
- Tracked in `layer_token_counts: {"available_products": N, "product_instructions": N}`

### ContextAssembler constructor changes

```python
ContextAssembler.__init__():
  ... (existing params)
  + catalog_items: list[CatalogItemInfo] | None = None
```

New attribute stored for use in prompt assembly and returned in `AssembledPrompt` for downstream services.

### AssembledPrompt extension

```python
AssembledPrompt:
  ... (existing fields)
  + catalog_items_used: list[CatalogItemInfo]   # Items included in prompt
```

## SSE Response Format

### New SSE event: `products`

Emitted after `citations`, before `done`. Only emitted if `[product:N]` markers were found.

```json
{
  "type": "products",
  "content": [
    {
      "index": 1,
      "catalog_item_id": "550e8400-...",
      "name": "AI in Practice",
      "sku": "AI-PRACTICE-2026",
      "item_type": "book",
      "url": "https://store.example.com/ai-practice",
      "image_url": "https://cdn.example.com/ai-practice.jpg",
      "text_recommendation": "AI in Practice (book)"
    }
  ]
}
```

### Enriched `citations` event

Existing citation objects gain optional fields:

```json
{
  "source_id": "...",
  "source_title": "Clean Architecture",
  "anchor": { "chapter": "5", "page": "42" },
  "url": "https://original-source.com/chapter-5",
  "text_citation": "Clean Architecture, Chapter 5, p. 42",
  "purchase_url": "https://store.com/clean-arch",
  "purchase_title": "Clean Architecture",
  "catalog_item_type": "book"
}
```

Fields `purchase_url`, `purchase_title`, `catalog_item_type` are `null` when the source has no linked catalog item.

### SSE event order

1. `token` — streaming tokens (existing)
2. `citations` — knowledge citations with optional purchase enrichment (existing, extended)
3. `products` — recommended products (new, optional)
4. `done` — completion signal (existing)

### Persisted message format (GET sessions/:id)

Extended with:

- `products: list[ProductRecommendation] | None` — recommended products (new)
- Citation objects gain `purchase_url`, `purchase_title`, `catalog_item_type` (nullable)

## Error Handling & Edge Cases

| Scenario                                     | Behavior                                                                                                                                                                   |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SKU in PROMOTIONS.md not found in DB         | Warning in structlog, promotion works as text-only (no `[product:N]`)                                                                                                      |
| Catalog item inactive (`is_active=false`)    | Excluded from prompt, excluded from citation enrichment                                                                                                                    |
| Catalog item expired (`valid_until < today`) | Same as inactive                                                                                                                                                           |
| Source soft-deleted but has catalog_item     | Catalog item remains. Link preserved in published snapshots                                                                                                                |
| Catalog item soft-deleted                    | `source.catalog_item_id` remains (FK NOT nullified). Enrichment disabled by `is_active` filtering. Links restorable.                                                       |
| LLM uses invalid `[product:N]` index         | Marker silently ignored (consistent with `[source:N]` behavior)                                                                                                            |
| LLM places multiple `[product:N]` markers    | Only first valid one is extracted (max 1 recommendation)                                                                                                                   |
| Catalog item has no `url`                    | Recommendation without link: name + type only (like offline citation)                                                                                                      |
| PROMOTIONS.md missing or empty               | No promotions layer; catalog items still in prompt as available_products for `[product:N]` mechanism; citation enrichment works independently at response processing level |
| No active catalog items                      | `available_products` layer omitted; `product_instructions` omitted                                                                                                         |
| Duplicate SKU on create                      | 409 Conflict with clear error message                                                                                                                                      |

## Testing Strategy

### Unit tests (CI, deterministic)

| Component                      | What to test                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------- |
| Catalog CRUD service           | Create with SKU, uniqueness violation, update (partial), soft delete, list + filters  |
| `ProductRecommendationService` | Parse `[product:N]`, invalid indices, max 1 limit, deduplication, strip_markers       |
| `CitationService` (extended)   | Purchase_url enrichment, inactive item → no enrichment, no catalog → null fields      |
| `PromotionsService` (extended) | Parse `Catalog item:` metadata, missing field → None, unknown SKU handling            |
| `ContextAssembler` (extended)  | `available_products` layer, `product_instructions`, token counting, empty catalog     |
| Source ↔ Catalog linking       | PATCH source with catalog_item_id, SET NULL on catalog delete                         |
| SSE serialization              | New `products` event, enriched `citations` event, event ordering                      |
| Pydantic schemas               | CatalogItemCreate validation (SKU format, required fields), CatalogItemUpdate partial |

### Integration tests (CI, in Docker)

- **Citation enrichment flow:** create catalog item → upload source with catalog_item_id → publish snapshot → chat → verify citation contains purchase_url
- **Product recommendation flow:** create catalog item with SKU → PROMOTIONS.md references SKU → chat about relevant topic → verify SSE `products` event with correct data
- **Soft delete cascade:** delete catalog item → verify source.catalog_item_id is NULL → verify citation enrichment no longer appears
- **Source re-linking:** PATCH source with new catalog_item_id → verify citation enrichment updates

### Quality tests (evals, separate from CI)

- LLM uses `[product:N]` when contextually appropriate
- LLM does NOT force recommendations in every response
- Recommendations sound natural and non-advertising
- LLM respects "maximum one product recommendation" instruction
