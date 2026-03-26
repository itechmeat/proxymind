import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SnapshotCard } from "@/components/SnapshotCard/SnapshotCard";
import { translate } from "@/lib/i18n";

function buildSnapshot(
  overrides: Partial<
    React.ComponentProps<typeof SnapshotCard>["snapshot"]
  > = {},
): React.ComponentProps<typeof SnapshotCard>["snapshot"] {
  return {
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
    ...overrides,
  };
}

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
        snapshot={buildSnapshot()}
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

  it("shows the activate action for published snapshots", async () => {
    const user = userEvent.setup();
    const onActivate = vi.fn();

    render(
      <SnapshotCard
        busy={false}
        onActivate={onActivate}
        onPublish={vi.fn()}
        onRollback={vi.fn()}
        onTest={vi.fn()}
        snapshot={buildSnapshot({
          id: "published-1",
          name: "Published",
          status: "published",
        })}
      />,
    );

    expect(
      screen.queryByRole("button", { name: translate("admin.snapshot.test") }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: translate("admin.snapshot.publish"),
      }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: translate("admin.snapshot.activate"),
      }),
    );

    expect(onActivate).toHaveBeenCalledWith("published-1");
  });

  it("shows rollback confirmation for active snapshots", async () => {
    const user = userEvent.setup();
    const onRollback = vi.fn();

    render(
      <SnapshotCard
        busy={false}
        onActivate={vi.fn()}
        onPublish={vi.fn()}
        onRollback={onRollback}
        onTest={vi.fn()}
        snapshot={buildSnapshot({
          id: "active-1",
          name: "Active",
          status: "active",
        })}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: translate("admin.snapshot.rollback"),
      }),
    );
    await user.click(
      screen.getByRole("button", {
        name: translate("admin.snapshot.confirm.rollback.action"),
      }),
    );

    expect(onRollback).toHaveBeenCalledWith("active-1");
  });

  it("does not show lifecycle actions for archived snapshots", () => {
    render(
      <SnapshotCard
        busy={false}
        onActivate={vi.fn()}
        onPublish={vi.fn()}
        onRollback={vi.fn()}
        onTest={vi.fn()}
        snapshot={buildSnapshot({
          id: "archived-1",
          name: "Archived",
          status: "archived",
        })}
      />,
    );

    expect(
      screen.queryByRole("button", { name: translate("admin.snapshot.test") }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: translate("admin.snapshot.publish"),
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: translate("admin.snapshot.publishAndActivate"),
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: translate("admin.snapshot.activate"),
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: translate("admin.snapshot.rollback"),
      }),
    ).not.toBeInTheDocument();
  });
});
