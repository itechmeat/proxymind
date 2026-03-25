import { Fragment, useEffect, useState } from "react";

import { DraftTestPanel } from "@/components/DraftTestPanel/DraftTestPanel";
import { SnapshotCard } from "@/components/SnapshotCard/SnapshotCard";
import { Button } from "@/components/ui/button";
import { useDraftTest } from "@/hooks/useDraftTest";
import { useSnapshots } from "@/hooks/useSnapshots";

export function SnapshotsTab() {
  const [showArchived, setShowArchived] = useState(false);
  const {
    activate,
    busySnapshotId,
    createDraft,
    draftSnapshot,
    isLoading,
    publish,
    rollback,
    snapshots,
  } = useSnapshots(showArchived);
  const { isLoading: isTesting, result, runDraftTest } = useDraftTest();
  const [selectedDraftId, setSelectedDraftId] = useState<string>("");

  useEffect(() => {
    if (!draftSnapshot) {
      setSelectedDraftId("");
      return;
    }

    setSelectedDraftId((current) => current || draftSnapshot.id);
  }, [draftSnapshot]);

  const draftSnapshots = snapshots.filter(
    (snapshot) => snapshot.status === "draft",
  );

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="m-0 text-xs uppercase tracking-[0.16em] text-stone-500">
            Snapshot lifecycle
          </p>
          <h2 className="m-0 mt-1 text-2xl font-semibold tracking-[-0.03em] text-stone-950">
            Manage drafts, publications, activation and rollback
          </h2>
        </div>
        <Button
          disabled={draftSnapshot !== null}
          onClick={() => {
            void createDraft();
          }}
          title={draftSnapshot ? "A draft already exists" : undefined}
          type="button"
        >
          + New Draft
        </Button>
      </div>

      {isLoading ? (
        <div className="rounded-[1.5rem] border border-white/70 bg-white/90 px-6 py-8 text-sm text-stone-500 shadow-sm shadow-stone-900/5">
          Loading snapshots…
        </div>
      ) : (
        <div className="space-y-4">
          {snapshots.map((snapshot) => (
            <Fragment key={snapshot.id}>
              <SnapshotCard
                busy={busySnapshotId === snapshot.id}
                onActivate={(snapshotId) => {
                  void activate(snapshotId);
                }}
                onPublish={(snapshotId, shouldActivate) => {
                  void publish(snapshotId, shouldActivate);
                }}
                onRollback={(snapshotId) => {
                  void rollback(snapshotId);
                }}
                onTest={(snapshotId) => {
                  setSelectedDraftId(snapshotId);
                }}
                snapshot={snapshot}
              />

              {snapshot.status === "draft" &&
              snapshot.id === selectedDraftId ? (
                <DraftTestPanel
                  isLoading={isTesting}
                  onSubmit={(payload) => {
                    void runDraftTest(payload);
                  }}
                  result={result}
                  selectedSnapshotId={selectedDraftId}
                  snapshots={draftSnapshots}
                />
              ) : null}
            </Fragment>
          ))}

          {draftSnapshots.length === 0 ? (
            <div className="rounded-[1.5rem] border border-dashed border-stone-300 bg-white/70 px-5 py-6 text-sm text-stone-500">
              Create a draft to run inline draft testing.
            </div>
          ) : null}

          <label className="flex items-center gap-2 text-sm text-stone-600">
            <input
              checked={showArchived}
              onChange={(event) => {
                setShowArchived(event.target.checked);
              }}
              type="checkbox"
            />
            Show archived
          </label>
        </div>
      )}
    </section>
  );
}
