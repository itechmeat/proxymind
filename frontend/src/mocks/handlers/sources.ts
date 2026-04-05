import { HttpResponse, http } from "msw";

import { mockSources } from "@/mocks/data/fixtures";
import type { SourceListItem } from "@/types/admin";

const sources: SourceListItem[] = [...mockSources];

export const sourceHandlers = [
  http.get("*/api/admin/sources", () => {
    return HttpResponse.json(sources);
  }),

  http.post("*/api/admin/sources", async ({ request }) => {
    const newId = crypto.randomUUID();
    const formData = await request.formData();
    const metadataRaw = formData.get("metadata");
    const metadata =
      typeof metadataRaw === "string"
        ? (JSON.parse(metadataRaw) as Record<string, unknown>)
        : {};
    const file = formData.get("file");
    const filename = file instanceof File ? file.name : `${newId}.bin`;

    const newSource: SourceListItem = {
      id: newId,
      catalog_item_id: (metadata.catalog_item_id as string | null) ?? null,
      title: (metadata.title as string) ?? filename,
      source_type: "pdf",
      status: "pending",
      description: (metadata.description as string | null) ?? null,
      public_url: (metadata.public_url as string | null) ?? null,
      file_size_bytes: file instanceof File ? file.size : null,
      language: (metadata.language as string | null) ?? null,
      created_at: new Date().toISOString(),
    };
    sources.push(newSource);

    return HttpResponse.json({
      source_id: newSource.id,
      task_id: crypto.randomUUID(),
      status: newSource.status,
      file_path: `/storage/${newSource.id}/${filename}`,
      message: "Source uploaded successfully. Processing started.",
    });
  }),

  http.patch("*/api/admin/sources/:id", async ({ params, request }) => {
    const source = sources.find((s) => s.id === params.id);
    if (!source) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const body = (await request.json()) as Record<string, unknown>;
    Object.assign(source, body);
    return HttpResponse.json(source);
  }),

  http.delete("*/api/admin/sources/:id", ({ params }) => {
    const index = sources.findIndex((s) => s.id === params.id);
    if (index === -1) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const [removed] = sources.splice(index, 1);
    return HttpResponse.json({
      id: removed.id,
      title: removed.title,
      source_type: removed.source_type,
      status: "deleted" as const,
      deleted_at: new Date().toISOString(),
      warnings: [],
    });
  }),
];
