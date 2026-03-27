## Story

**S6-01: Commerce backend — catalog + recommendations**

Verification criteria from `docs/plan.md`:
- Citation of linked product shows store link
- Conversation about topic triggers relevant recommendation
- Not every response has a recommendation

Stable behavior that must be covered by tests: catalog CRUD, citation enrichment, product marker extraction, promotions SKU parsing, context assembly with product layers, SSE products event serialization and ordering, idempotency replay with products.

## Why

The twin currently serves knowledge-based answers with citations but has no structured commerce layer. Product recommendations exist only as free-text promotions in PROMOTIONS.md without purchase links, catalog structure, or tracking. S6-01 closes this gap by connecting the product catalog to both the citation pipeline and the recommendation mechanism, enabling the twin to naturally suggest products with actionable purchase links.

## What Changes

- Admin API gains full CRUD for `catalog_items` (list, get, create, update, soft-delete)
- `CatalogItem` model gains a `sku` field (unique, required) for human-readable identification
- Source PATCH endpoint enables linking/unlinking sources to catalog items
- Citations are automatically enriched with purchase links when the cited source has an active linked catalog item
- New `[product:N]` marker mechanism (analogous to `[source:N]`) lets the LLM reference products; backend enriches with real URLs
- PROMOTIONS.md gains optional `Catalog item:` metadata for SKU-based matching to catalog items
- `ContextAssembler` gains `available_products` and `product_instructions` prompt layers
- New SSE event `type: "products"` delivers recommended products to the frontend
- `Message` model gains `products: JSONB` for persistence alongside existing `citations`

## Capabilities

### New Capabilities
- `catalog-crud`: Admin API for catalog item management (CRUD, SKU uniqueness, source linking, soft-delete)
- `product-recommendation`: `[product:N]` marker extraction, prompt product layer, SSE products event, recommendation persistence
- `citation-enrichment`: Automatic purchase link injection into citations when source has active catalog item

### Modified Capabilities
- `promotions-parser`: Parse optional `Catalog item:` SKU metadata from PROMOTIONS.md sections
- `context-assembly`: Add `available_products` and `product_instructions` prompt layers; pass catalog items via DI
- `citation-builder`: Extend `SourceInfo` and `Citation` dataclasses with purchase fields; enrich in `extract()`
- `sse-streaming`: Add `ChatStreamProducts` event type between `citations` and `done`

## Impact

- **Backend models**: `CatalogItem` (add `sku`), `Source` (fix FK `ondelete`), `Message` (add `products` JSONB)
- **Migration**: Alembic 011 — add SKU with backfill, fix FK, add products column
- **Admin API**: 5 new catalog endpoints + 1 source PATCH endpoint
- **Services**: New `CatalogService`, `ProductRecommendationService`; extend `CitationService`, `PromotionsService`, `ContextAssembler`
- **DI layer**: `get_context_assembler()` in `dependencies.py` becomes async to load catalog items
- **SSE contract**: New event type `products` — frontend must handle it (deferred to S6-02)
- **Config**: `PROMOTIONS.md` gains optional `Catalog item:` field (backward-compatible)
