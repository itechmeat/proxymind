import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SnapshotCard } from "@/components/SnapshotCard/SnapshotCard";

describe("SnapshotCard", () => {
  it("shows draft actions and confirms publish", async () => {
    const user = userEvent.setup();
    const onPublish = vi.fn();

    render(
      <SnapshotCard
        busy={false}
        onActivate={vi.fn()}
        onPublish={onPublish}
        onRollback={vi.fn()}
        onTest={vi.fn()}
        snapshot={{
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
        }}
      />,
    );

    expect(screen.getByRole("button", { name: /test/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^publish$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /publish & activate/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^publish$/i }));
    await user.click(screen.getByRole("button", { name: /^publish$/i }));

    expect(onPublish).toHaveBeenCalledTimes(1);
    expect(onPublish).toHaveBeenCalledWith("draft-1", false);
  });
});
