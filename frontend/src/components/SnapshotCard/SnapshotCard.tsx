import { ArrowUpRight, Rocket, RotateCcw, Search, Upload } from "lucide-react";
import { useState } from "react";

import {
  AlertDialog,
  AlertDialogActionButton,
  AlertDialogCancelButton,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/strings";
import type { SnapshotResponse } from "@/types/admin";

type ConfirmationAction = "publish" | "publish-activate" | "rollback" | null;

function snapshotVariant(status: SnapshotResponse["status"]) {
  switch (status) {
    case "active":
      return "success" as const;
    case "draft":
      return "warning" as const;
    case "published":
      return "info" as const;
    default:
      return "muted" as const;
  }
}

function confirmationCopy(action: Exclude<ConfirmationAction, null>) {
  switch (action) {
    case "publish":
      return {
        button: "Publish",
        description: "This locks the current draft into a published snapshot.",
        title: "Publish this draft?",
      };
    case "publish-activate":
      return {
        button: "Publish & Activate",
        description:
          "This publishes the draft and switches the twin to the new snapshot immediately.",
        title: "Publish and activate this draft?",
      };
    case "rollback":
      return {
        button: "Rollback",
        description:
          "This restores the previously activated published snapshot as the active one.",
        title: "Rollback the active snapshot?",
      };
  }
}

interface SnapshotCardProps {
  busy: boolean;
  onActivate: (snapshotId: string) => void;
  onPublish: (snapshotId: string, activate?: boolean) => void;
  onRollback: (snapshotId: string) => void;
  onTest: (snapshotId: string) => void;
  snapshot: SnapshotResponse;
}

export function SnapshotCard({
  busy,
  onActivate,
  onPublish,
  onRollback,
  onTest,
  snapshot,
}: SnapshotCardProps) {
  const [confirmationAction, setConfirmationAction] =
    useState<ConfirmationAction>(null);
  const confirmation = confirmationAction
    ? confirmationCopy(confirmationAction)
    : null;

  return (
    <>
      <article className="rounded-[1.75rem] border border-white/70 bg-white/90 p-5 shadow-sm shadow-stone-900/5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="m-0 text-lg font-semibold text-stone-950">
                {snapshot.name}
              </h3>
              <Badge variant={snapshotVariant(snapshot.status)}>
                {snapshot.status}
              </Badge>
            </div>
            <div className="grid gap-2 text-sm text-stone-600 sm:grid-cols-2">
              <p className="m-0">Chunks: {snapshot.chunk_count}</p>
              <p className="m-0">
                Created {formatRelativeTime(snapshot.created_at)}
              </p>
              {snapshot.published_at ? (
                <p className="m-0">
                  Published {formatRelativeTime(snapshot.published_at)}
                </p>
              ) : null}
              {snapshot.activated_at ? (
                <p className="m-0">
                  Activated {formatRelativeTime(snapshot.activated_at)}
                </p>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-2 sm:max-w-[18rem] sm:justify-end">
            {snapshot.status === "draft" ? (
              <>
                <Button
                  onClick={() => {
                    onTest(snapshot.id);
                  }}
                  type="button"
                  variant="outline"
                >
                  <Search className="size-4" />
                  Test
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setConfirmationAction("publish");
                  }}
                  type="button"
                  variant="outline"
                >
                  <Upload className="size-4" />
                  Publish
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setConfirmationAction("publish-activate");
                  }}
                  type="button"
                >
                  <Rocket className="size-4" />
                  Publish & Activate
                </Button>
              </>
            ) : null}

            {snapshot.status === "published" ? (
              <Button
                disabled={busy}
                onClick={() => {
                  onActivate(snapshot.id);
                }}
                type="button"
              >
                <ArrowUpRight className="size-4" />
                Activate
              </Button>
            ) : null}

            {snapshot.status === "active" ? (
              <Button
                disabled={busy}
                onClick={() => {
                  setConfirmationAction("rollback");
                }}
                type="button"
                variant="outline"
              >
                <RotateCcw className="size-4" />
                Rollback
              </Button>
            ) : null}
          </div>
        </div>
      </article>

      <AlertDialog
        onOpenChange={(open) => {
          if (!open) {
            setConfirmationAction(null);
          }
        }}
        open={confirmationAction !== null}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmation?.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmation?.description}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancelButton type="button">
              Cancel
            </AlertDialogCancelButton>
            <AlertDialogActionButton
              onClick={() => {
                if (confirmationAction === "publish") {
                  onPublish(snapshot.id, false);
                }

                if (confirmationAction === "publish-activate") {
                  onPublish(snapshot.id, true);
                }

                if (confirmationAction === "rollback") {
                  onRollback(snapshot.id);
                }

                setConfirmationAction(null);
              }}
              type="button"
            >
              {confirmation?.button}
            </AlertDialogActionButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
