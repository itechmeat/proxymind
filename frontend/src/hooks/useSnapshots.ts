import { useCallback, useEffect, useMemo, useState } from "react";
import { useToast } from "@/hooks/useToast";
import {
  activateSnapshot,
  createSnapshot,
  getSnapshots,
  publishSnapshot,
  rollbackSnapshot,
} from "@/lib/admin-api";
import type { SnapshotResponse } from "@/types/admin";

export function sortSnapshots(snapshots: SnapshotResponse[]) {
  const priority = {
    active: 0,
    draft: 1,
    published: 2,
    archived: 3,
  } as const;

  return [...snapshots].sort((left, right) => {
    const priorityDiff = priority[left.status] - priority[right.status];
    if (priorityDiff !== 0) {
      return priorityDiff;
    }

    return (
      new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
    );
  });
}

export function useSnapshots(includeArchived = false) {
  const { pushToast } = useToast();
  const [snapshots, setSnapshots] = useState<SnapshotResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busySnapshotId, setBusySnapshotId] = useState<string | null>(null);

  const refreshSnapshots = useCallback(async () => {
    const nextSnapshots = sortSnapshots(await getSnapshots(includeArchived));
    setSnapshots(nextSnapshots);
    return nextSnapshots;
  }, [includeArchived]);

  useEffect(() => {
    let active = true;

    void (async () => {
      try {
        const nextSnapshots = await getSnapshots(includeArchived);
        if (active) {
          setSnapshots(sortSnapshots(nextSnapshots));
        }
      } catch (error) {
        if (active) {
          pushToast({
            message:
              error instanceof Error
                ? error.message
                : "Failed to load snapshots",
            tone: "error",
          });
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [includeArchived, pushToast]);

  const runMutation = useCallback(
    async (
      snapshotId: string | null,
      operation: () => Promise<unknown>,
      successMessage: string,
    ) => {
      setBusySnapshotId(snapshotId);
      try {
        await operation();
        pushToast({ message: successMessage, tone: "success" });
        await refreshSnapshots();
      } catch (error) {
        pushToast({
          message:
            error instanceof Error ? error.message : "Snapshot action failed",
          tone: "error",
        });
      } finally {
        setBusySnapshotId(null);
      }
    },
    [pushToast, refreshSnapshots],
  );

  const createDraft = useCallback(async () => {
    await runMutation(null, () => createSnapshot(), "Draft ready");
  }, [runMutation]);

  const publish = useCallback(
    async (snapshotId: string, activate = false) => {
      await runMutation(
        snapshotId,
        () => publishSnapshot(snapshotId, activate),
        activate ? "Snapshot published and activated" : "Snapshot published",
      );
    },
    [runMutation],
  );

  const activate = useCallback(
    async (snapshotId: string) => {
      await runMutation(
        snapshotId,
        () => activateSnapshot(snapshotId),
        "Snapshot activated",
      );
    },
    [runMutation],
  );

  const rollback = useCallback(
    async (snapshotId: string) => {
      await runMutation(
        snapshotId,
        () => rollbackSnapshot(snapshotId),
        "Rollback completed",
      );
    },
    [runMutation],
  );

  const draftSnapshot = useMemo(
    () => snapshots.find((snapshot) => snapshot.status === "draft") ?? null,
    [snapshots],
  );

  return {
    activate,
    busySnapshotId,
    createDraft,
    draftSnapshot,
    isLoading,
    publish,
    refreshSnapshots,
    rollback,
    snapshots,
  };
}
