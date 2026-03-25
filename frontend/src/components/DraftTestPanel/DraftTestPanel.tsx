import { Search } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  DraftTestResponse,
  RetrievalMode,
  SnapshotResponse,
} from "@/types/admin";

interface DraftTestPanelProps {
  isLoading: boolean;
  onSubmit: (payload: {
    mode: RetrievalMode;
    query: string;
    snapshotId: string;
  }) => void;
  result: DraftTestResponse | null;
  selectedSnapshotId: string;
  snapshots: SnapshotResponse[];
}

export function DraftTestPanel({
  isLoading,
  onSubmit,
  result,
  selectedSnapshotId,
  snapshots,
}: DraftTestPanelProps) {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const selectedSnapshot = snapshots.find(
    (snapshot) => snapshot.id === selectedSnapshotId,
  );

  const anchorSummary = (
    anchor: DraftTestResponse["results"][number]["anchor"],
  ) => {
    const items = [
      anchor.page ? `Page ${anchor.page}` : null,
      anchor.chapter ? `Chapter ${anchor.chapter}` : null,
      anchor.section ? `Section ${anchor.section}` : null,
      anchor.timecode ? `Timecode ${anchor.timecode}` : null,
    ].filter(Boolean);

    return items.join(" • ");
  };

  return (
    <section className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm shadow-stone-900/5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="m-0 text-xs uppercase tracking-[0.16em] text-stone-500">
            Draft testing
          </p>
          <h3 className="m-0 mt-1 text-lg font-semibold text-stone-950">
            Search inside the current draft before publishing
          </h3>
        </div>
        {selectedSnapshot ? (
          <Badge variant="warning">Testing {selectedSnapshot.name}</Badge>
        ) : null}
      </div>

      {selectedSnapshot ? (
        <form
          className="mt-4 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!query.trim()) {
              return;
            }

            onSubmit({
              mode,
              query: query.trim(),
              snapshotId: selectedSnapshot.id,
            });
          }}
        >
          <label className="grid gap-2 text-sm font-medium text-stone-700">
            Query
            <textarea
              className="min-h-28 rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3 text-base text-stone-950 outline-none transition focus:border-sky-400 focus:bg-white"
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              placeholder="Ask what the draft should know"
              value={query}
            />
          </label>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <label className="flex items-center gap-2 text-sm text-stone-600">
              Mode
              <select
                className="rounded-full border border-stone-200 bg-white px-3 py-2 text-sm text-stone-950 outline-none"
                onChange={(event) => {
                  setMode(event.target.value as RetrievalMode);
                }}
                value={mode}
              >
                <option value="hybrid">Hybrid</option>
                <option value="dense">Dense</option>
                <option value="sparse">Sparse</option>
              </select>
            </label>

            <Button disabled={isLoading} type="submit">
              <Search className="size-4" />
              {isLoading ? "Searching…" : "Test draft"}
            </Button>
          </div>
        </form>
      ) : (
        <p className="mb-0 mt-4 text-sm text-stone-500">
          Select a draft snapshot to test retrieval.
        </p>
      )}

      {result ? (
        <div className="mt-5 space-y-3 border-t border-stone-200 pt-5">
          <p className="m-0 text-sm text-stone-600">
            {result.results.length} result(s) from{" "}
            {result.total_chunks_in_draft} indexed chunk(s)
          </p>
          <div className="grid gap-3">
            {result.results.map((item) => (
              <article
                className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3"
                key={item.chunk_id}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="m-0 font-medium text-stone-950">
                    {item.source_title ?? item.source_id}
                  </p>
                  <Badge variant="info">{item.score.toFixed(3)}</Badge>
                </div>
                <p className="mb-0 mt-2 text-sm leading-6 text-stone-600">
                  {item.text_content}
                </p>
                {anchorSummary(item.anchor) ? (
                  <p className="mb-0 mt-2 text-xs uppercase tracking-[0.14em] text-stone-500">
                    {anchorSummary(item.anchor)}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
