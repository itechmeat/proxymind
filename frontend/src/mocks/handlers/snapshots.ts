import { HttpResponse, http } from "msw";

import { mockSnapshots } from "@/mocks/data/fixtures";
import type { SnapshotResponse } from "@/types/admin";

function cloneSnapshot(snapshot: SnapshotResponse): SnapshotResponse {
  return { ...snapshot };
}

function makeSnapshots(): SnapshotResponse[] {
  return mockSnapshots.map(cloneSnapshot);
}

let snapshots: SnapshotResponse[] = makeSnapshots();

export function resetSnapshotHandlersState() {
  snapshots = makeSnapshots();
}

function findSnapshot(id: string) {
  return snapshots.find((s) => s.id === id);
}

export const snapshotHandlers = [
  http.get("*/api/admin/snapshots", ({ request }) => {
    const url = new URL(request.url);
    const includeArchived = url.searchParams.get("include_archived") === "true";

    const result = includeArchived
      ? snapshots
      : snapshots.filter((s) => s.status !== "archived");

    return HttpResponse.json(result);
  }),

  http.post("*/api/admin/snapshots", () => {
    const newSnapshot: SnapshotResponse = {
      id: crypto.randomUUID(),
      agent_id: null,
      knowledge_base_id: null,
      name: `v${snapshots.length + 1}.0 — New snapshot`,
      description: null,
      status: "draft",
      published_at: null,
      activated_at: null,
      archived_at: null,
      chunk_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    snapshots.push(newSnapshot);
    return HttpResponse.json(newSnapshot);
  }),

  http.post("*/api/admin/snapshots/:id/publish", ({ params, request }) => {
    const snapshot = findSnapshot(params.id as string);
    if (!snapshot) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const url = new URL(request.url);
    const now = new Date().toISOString();
    snapshot.status = "published";
    snapshot.published_at = now;
    snapshot.updated_at = now;

    if (url.searchParams.get("activate") === "true") {
      for (const s of snapshots) {
        if (s.status === "active") {
          s.status = "archived";
          s.archived_at = now;
        }
      }
      snapshot.status = "active";
      snapshot.activated_at = now;
    }

    return HttpResponse.json(snapshot);
  }),

  http.post("*/api/admin/snapshots/:id/activate", ({ params }) => {
    const snapshot = findSnapshot(params.id as string);
    if (!snapshot) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    const now = new Date().toISOString();
    for (const s of snapshots) {
      if (s.status === "active") {
        s.status = "archived";
        s.archived_at = now;
      }
    }
    snapshot.status = "active";
    snapshot.activated_at = now;
    snapshot.updated_at = now;

    return HttpResponse.json(snapshot);
  }),

  http.post("*/api/admin/snapshots/:id/rollback", ({ params }) => {
    const snapshot = findSnapshot(params.id as string);
    if (!snapshot) {
      return HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }

    return HttpResponse.json({
      rolled_back_from: {
        id: snapshot.id,
        name: snapshot.name,
        status: "archived",
        published_at: snapshot.published_at,
        activated_at: snapshot.activated_at,
      },
      rolled_back_to: {
        id: snapshot.id,
        name: snapshot.name,
        status: "active",
        published_at: snapshot.published_at,
        activated_at: new Date().toISOString(),
      },
    });
  }),

  http.post("*/api/admin/snapshots/:id/test", async ({ params, request }) => {
    const body = (await request.json()) as {
      query: string;
      top_n?: number;
      mode?: string;
    };
    const snapshot = findSnapshot(params.id as string);

    return HttpResponse.json({
      snapshot_id: snapshot?.id ?? "unknown",
      snapshot_name: snapshot?.name ?? "Unknown",
      query: body.query,
      mode: body.mode ?? "hybrid",
      results: [
        {
          chunk_id: crypto.randomUUID(),
          source_id: "mock-src-00000000-0000-0000-0000-000000000001",
          source_title: "Designing Resilient Systems",
          text_content: `Relevant chunk for query: "${body.query}". Circuit breakers prevent cascading failures by monitoring error rates and temporarily blocking requests to unhealthy services.`,
          score: 0.92,
          anchor: {
            page: 42,
            chapter: "Chapter 3",
            section: "Circuit Breakers",
            timecode: null,
          },
        },
        {
          chunk_id: crypto.randomUUID(),
          source_id: "mock-src-00000000-0000-0000-0000-000000000002",
          source_title: "API Design Handbook",
          text_content: `Another relevant chunk for: "${body.query}". Retry budgets limit the total number of retries across all callers, preventing thundering herd problems.`,
          score: 0.85,
          anchor: {
            page: 15,
            chapter: "Chapter 2",
            section: "Error Handling",
            timecode: null,
          },
        },
      ],
      total_chunks_in_draft: snapshot?.chunk_count ?? 0,
    });
  }),
];
