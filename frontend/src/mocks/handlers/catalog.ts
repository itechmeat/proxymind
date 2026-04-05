import { HttpResponse, http } from "msw";

import {
  mockCatalogItemDetails,
  mockCatalogItems,
} from "@/mocks/data/fixtures";
import type { CatalogItem } from "@/types/admin";

function cloneCatalogItem(item: CatalogItem): CatalogItem {
  return { ...item };
}

function makeItems(): CatalogItem[] {
  return mockCatalogItems.map(cloneCatalogItem);
}

let items: CatalogItem[] = makeItems();

export function resetCatalogHandlersState() {
  items = makeItems();
}

export const catalogHandlers = [
  http.get("*/api/admin/catalog", ({ request }) => {
    const url = new URL(request.url);
    const itemType = url.searchParams.get("item_type");

    const filtered = itemType
      ? items.filter((i) => i.item_type === itemType)
      : items;

    return HttpResponse.json({ items: filtered, total: filtered.length });
  }),

  http.get("*/api/admin/catalog/:id", ({ params }) => {
    const item = items.find((entry) => entry.id === params.id);
    if (!item) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const detail = mockCatalogItemDetails[item.id];
    return HttpResponse.json({
      ...item,
      linked_sources: detail?.linked_sources ?? [],
    });
  }),

  http.post("*/api/admin/catalog", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    const newItem: CatalogItem = {
      id: crypto.randomUUID(),
      sku: (body.sku as string) ?? "NEW-001",
      name: (body.name as string) ?? "New Item",
      description: (body.description as string) ?? null,
      item_type: (body.item_type as CatalogItem["item_type"]) ?? "other",
      url: (body.url as string) ?? null,
      image_url: (body.image_url as string) ?? null,
      is_active: true,
      valid_from: (body.valid_from as string) ?? null,
      valid_until: (body.valid_until as string) ?? null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      linked_sources_count: 0,
    };
    items.push(newItem);
    return HttpResponse.json(newItem, { status: 201 });
  }),

  http.patch("*/api/admin/catalog/:id", async ({ params, request }) => {
    const index = items.findIndex((i) => i.id === params.id);
    const item = items[index];
    if (!item) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const body = (await request.json()) as Record<string, unknown>;
    items[index] = {
      ...item,
      ...body,
      updated_at: new Date().toISOString(),
    };
    return HttpResponse.json(items[index]);
  }),

  http.delete("*/api/admin/catalog/:id", ({ params }) => {
    const index = items.findIndex((i) => i.id === params.id);
    if (index === -1) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const [removed] = items.splice(index, 1);
    return HttpResponse.json(removed);
  }),
];
