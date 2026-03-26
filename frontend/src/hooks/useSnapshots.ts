import { useCallback, useEffect, useMemo, useState } from "react";
import { useToast } from "@/hooks/useToast";
import {
  activateSnapshot,
  createSnapshot,
  getSnapshots,
  publishSnapshot,
  rollbackSnapshot,
} from "@/lib/admin-api";
import { translate } from "@/lib/i18n";
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
                : translate("admin.snapshot.loadFailed"),
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
      fallbackErrorMessage: string,
    ) => {
      setBusySnapshotId(snapshotId);
      try {
        await operation();
        pushToast({ message: successMessage, tone: "success" });
      } catch (error) {
        pushToast({
          message:
            error instanceof Error ? error.message : fallbackErrorMessage,
          tone: "error",
        });
        return;
      }

      try {
        await refreshSnapshots();
      } catch (error) {
        pushToast({
          message:
            error instanceof Error
              ? error.message
              : translate("admin.snapshot.refreshFailed"),
          tone: "warning",
        });
      } finally {
        setBusySnapshotId(null);
      }
    },
    [pushToast, refreshSnapshots],
  );

  const createDraft = useCallback(async () => {
    await runMutation(
      null,
      () => createSnapshot(),
      translate("admin.snapshot.draftReady"),
      translate("admin.snapshot.actionFailed"),
    );
  }, [runMutation]);

  const publish = useCallback(
    async (snapshotId: string, activate = false) => {
      await runMutation(
        snapshotId,
        () => publishSnapshot(snapshotId, activate),
        activate
          ? translate("admin.snapshot.publishedAndActivated")
          : translate("admin.snapshot.published"),
        translate("admin.snapshot.actionFailed"),
      );
    },
    [runMutation],
  );

  const activate = useCallback(
    async (snapshotId: string) => {
      await runMutation(
        snapshotId,
        () => activateSnapshot(snapshotId),
        translate("admin.snapshot.activated"),
        translate("admin.snapshot.actionFailed"),
      );
    },
    [runMutation],
  );

  const rollback = useCallback(
    async (snapshotId: string) => {
      await runMutation(
        snapshotId,
        () => rollbackSnapshot(snapshotId),
        translate("admin.snapshot.rollbackCompleted"),
        translate("admin.snapshot.actionFailed"),
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
