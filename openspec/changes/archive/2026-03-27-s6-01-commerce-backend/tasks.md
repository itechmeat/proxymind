## 1. Data Model + Migration

- [x] 1.1 Add `sku: String(64), unique, not null, indexed` field to `CatalogItem` model in `backend/app/db/models/core.py`
- [x] 1.2 Add `ondelete="SET NULL"` to `Source.catalog_item_id` FK in `backend/app/db/models/knowledge.py`
- [x] 1.3 Add `products: JSONB, nullable` field to `Message` model in `backend/app/db/models/dialogue.py`
- [x] 1.4 Create Alembic migration `011_add_catalog_sku_and_fk_ondelete.py`: add sku (nullable → backfill `LEGACY-` + full UUID → NOT NULL → unique index), fix FK ondelete, add products JSONB to messages
- [x] 1.5 Run migration in Docker, verify schema changes applied

## 2. Catalog Pydantic Schemas

- [x] 2.1 Create `backend/app/api/catalog_schemas.py` with `CatalogItemCreate`, `CatalogItemUpdate`, `CatalogItemResponse`, `CatalogItemDetail`, `LinkedSourceInfo`, `CatalogItemListResponse`, `SourceUpdateRequest` schemas (use `datetime` for valid_from/valid_until to match DB model)
- [x] 2.2 Add `catalog_item_id: uuid.UUID | None` to `SourceListItem` in `backend/app/api/source_schemas.py`

## 3. CatalogService

- [x] 3.1 Write unit tests for `CatalogService` in `backend/tests/unit/test_catalog_service.py`: filter_active (inactive, expired, future, no-dates), build_sku_map, datetime-to-date conversion
- [x] 3.2 Implement `CatalogService` in `backend/app/services/catalog.py`: create, get_by_id, list_items, update, soft_delete, get_active_items, filter_active (with `_to_date` helper), build_sku_map; define `CatalogItemInfo` dataclass
- [x] 3.3 Register `CatalogService` and `CatalogItemInfo` in `backend/app/services/__init__.py`
- [x] 3.4 Run tests, verify all pass

## 4. Catalog API Endpoints

- [x] 4.1 Add `get_catalog_service` dependency provider in `backend/app/api/dependencies.py`
- [x] 4.2 Add `GET /api/admin/catalog` endpoint — list with filtering (item_type, is_active) and pagination (limit/offset)
- [x] 4.3 Add `GET /api/admin/catalog/:id` endpoint — detail with linked sources
- [x] 4.4 Add `POST /api/admin/catalog` endpoint — create with SKU uniqueness (409 on conflict)
- [x] 4.5 Add `PATCH /api/admin/catalog/:id` endpoint — partial update with `exclude_unset`
- [x] 4.6 Add `DELETE /api/admin/catalog/:id` endpoint — soft delete
- [x] 4.7 Add `PATCH /api/admin/sources/:id` endpoint — link/unlink source to catalog item using `exclude_unset` pattern (absent = no change, null = unlink, UUID = link)
- [x] 4.8 Rebuild Docker, smoke-test endpoints manually

## 5. PromotionsService Extension

- [x] 5.1 Write unit tests for `Catalog item:` SKU parsing in `backend/tests/unit/test_promotions.py`: parses SKU, missing returns None, strips whitespace
- [x] 5.2 Extend `Promotion` dataclass with `catalog_item_sku: str | None` field
- [x] 5.3 Update `parse()` method to extract `Catalog item:` metadata (case-insensitive)
- [x] 5.4 Run all promotions tests, verify pass

## 6. ProductRecommendationService

- [x] 6.1 Write unit tests in `backend/tests/unit/test_product_recommendation.py`: single marker, max-1 limit, invalid indices (0, out-of-range), no markers, empty catalog, deduplication, strip_markers
- [x] 6.2 Implement `ProductRecommendationService` in `backend/app/services/product_recommendation.py`: `ProductRecommendation` dataclass with `to_dict()`, `extract()` with `[product:N]` regex + max-1 limit, `strip_markers()`
- [x] 6.3 Register in `backend/app/services/__init__.py`
- [x] 6.4 Run tests, verify all pass

## 7. Citation Enrichment

- [x] 7.1 Write unit tests in `backend/tests/unit/test_citation_service.py`: purchase_url when catalog active, no purchase when inactive, no purchase when no catalog item
- [x] 7.2 Extend `SourceInfo` dataclass with `catalog_item_url`, `catalog_item_name`, `catalog_item_type`, `catalog_item_active` (defaults for backward compatibility)
- [x] 7.3 Extend `Citation` dataclass with `purchase_url`, `purchase_title`, `catalog_item_type` (nullable defaults); update `to_dict()` and `from_dict()`
- [x] 7.4 Add enrichment logic in `CitationService.extract()`: populate purchase fields when `catalog_item_active` and URL present
- [x] 7.5 Run all citation tests, verify pass (existing + new)

## 8. ContextAssembler Extension

- [x] 8.1 Write unit tests in `backend/tests/unit/test_context_assembler.py`: available_products layer present with catalog, omitted when empty/None, product_instructions included, catalog_items_used tracked, token counts
- [x] 8.2 Add `catalog_items: list[CatalogItemInfo] | None = None` to `ContextAssembler.__init__()`, add `catalog_items_used` field to `AssembledPrompt`
- [x] 8.3 Implement `_build_available_products_layer()` using `self._build_layer()` for XML wrapping
- [x] 8.4 Implement `_build_product_instructions_layer()` using `self._build_layer()`
- [x] 8.5 Wire both layers into `assemble()` in correct order: available_products after promotions, product_instructions after citation_instructions
- [x] 8.6 Run all context assembler tests, verify pass

## 9. SSE + DI + ChatService Integration

- [x] 9.1 Make `get_context_assembler()` in `backend/app/api/dependencies.py` async; add session dependency; load active catalog items via `CatalogService` using `DEFAULT_AGENT_ID` from `app.core.constants`
- [x] 9.2 Add `ChatStreamProducts` dataclass in `backend/app/services/chat.py` (alongside existing `ChatStreamCitations`); add SSE formatting for `products` event in `backend/app/api/chat.py`
- [x] 9.3 Extend `_load_source_map()` in `backend/app/services/chat.py` to JOIN with catalog_items; handle datetime→date conversion for validity filtering
- [x] 9.4 Add product extraction after `CitationService.extract()` in both streaming and non-streaming paths using `assembled.catalog_items_used`
- [x] 9.5 Strip `[product:N]` markers from response content before persisting
- [x] 9.6 Persist products in Message record: add `products` parameter to `_persist_message()`, set `assistant_message.products` in streaming path
- [x] 9.7 Emit `ChatStreamProducts` SSE event after citations in streaming path
- [x] 9.8 Extend `CitationResponse` in `backend/app/api/chat_schemas.py` with `purchase_url`, `purchase_title`, `catalog_item_type`
- [x] 9.9 Add `ProductRecommendationResponse` schema and `products` field to `MessageResponse` and `MessageInHistory` in `chat_schemas.py`
- [x] 9.10 Write unit tests for SSE products event: `ChatStreamProducts` serialization, event ordering (token → citations → products → done), products not emitted when no markers found
- [x] 9.11 Write unit test for idempotency replay: verify that replaying a completed message with products returns the persisted `products` alongside `citations`
- [x] 9.12 Run all chat tests, verify no regressions

## 10. Configuration Update

- [x] 10.1 Add `Catalog item: AI-PRACTICE-2026` to book promotion in `config/PROMOTIONS.md`
- [x] 10.2 Add `Catalog item: TECHSUMMIT-2026` to conference promotion in `config/PROMOTIONS.md`

## 11. Integration Smoke Test

- [x] 11.1 Rebuild and start all services with `docker compose up --build`
- [x] 11.2 Run migration `alembic upgrade head`
- [x] 11.3 Create catalog items matching PROMOTIONS.md SKUs via POST /api/admin/catalog
- [x] 11.4 Verify catalog list endpoint returns both items
- [ ] 11.5 Upload source linked to a catalog item, publish snapshot, chat — verify citation contains purchase_url
      Blocked in live env: upload and publish succeed, but chat retrieval requires `GEMINI_API_KEY`; unit/integration coverage for citation enrichment and products passes.
- [x] 11.6 Run full test suite `docker compose exec api pytest tests/ -v`, confirm all tests pass
