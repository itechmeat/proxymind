import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DraftTestPanel } from "@/components/DraftTestPanel/DraftTestPanel";

describe("DraftTestPanel", () => {
  it("submits a query and renders results", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <DraftTestPanel
        isLoading={false}
        onSubmit={onSubmit}
        result={{
          snapshot_id: "draft-1",
          snapshot_name: "Draft",
          query: "what changed",
          mode: "hybrid",
          total_chunks_in_draft: 2,
          results: [
            {
              chunk_id: "chunk-1",
              source_id: "source-1",
              source_title: "Marcus Notes",
              text_content: "A precise answer",
              score: 0.91,
              anchor: {
                page: 1,
                chapter: null,
                section: null,
                timecode: null,
              },
            },
          ],
        }}
        selectedSnapshotId="draft-1"
        snapshots={[
          {
            id: "draft-1",
            agent_id: null,
            knowledge_base_id: null,
            name: "Draft",
            description: null,
            status: "draft",
            published_at: null,
            activated_at: null,
            archived_at: null,
            chunk_count: 0,
            created_at: "2026-03-25T12:00:00Z",
            updated_at: "2026-03-25T12:00:00Z",
          },
        ]}
      />,
    );

    await user.type(screen.getByLabelText(/query/i), "what changed");
    await user.click(screen.getByRole("button", { name: /test draft/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      mode: "hybrid",
      query: "what changed",
      snapshotId: "draft-1",
    });
    expect(screen.getByText("Marcus Notes")).toBeInTheDocument();
    expect(screen.getByText(/page 1/i)).toBeInTheDocument();
  });
});
