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
import { translateSnapshotStatus, useAppTranslation } from "@/lib/i18n";
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

function confirmationCopy(
  action: Exclude<ConfirmationAction, null>,
  t: ReturnType<typeof useAppTranslation>["t"],
) {
  switch (action) {
    case "publish":
      return {
        button: t("admin.snapshot.confirm.publish.action"),
        description: t("admin.snapshot.confirm.publish.description"),
        title: t("admin.snapshot.confirm.publish.title"),
      };
    case "publish-activate":
      return {
        button: t("admin.snapshot.confirm.publishAndActivate.action"),
        description: t("admin.snapshot.confirm.publishAndActivate.description"),
        title: t("admin.snapshot.confirm.publishAndActivate.title"),
      };
    case "rollback":
      return {
        button: t("admin.snapshot.confirm.rollback.action"),
        description: t("admin.snapshot.confirm.rollback.description"),
        title: t("admin.snapshot.confirm.rollback.title"),
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
  const { t } = useAppTranslation();
  const [confirmationAction, setConfirmationAction] =
    useState<ConfirmationAction>(null);
  const confirmation = confirmationAction
    ? confirmationCopy(confirmationAction, t)
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
                {translateSnapshotStatus(snapshot.status)}
              </Badge>
            </div>
            <div className="grid gap-2 text-sm text-stone-600 sm:grid-cols-2">
              <p className="m-0">
                {t("admin.snapshot.chunks", { count: snapshot.chunk_count })}
              </p>
              <p className="m-0">
                {t("admin.snapshot.createdAt", {
                  relativeTime: formatRelativeTime(snapshot.created_at),
                })}
              </p>
              {snapshot.published_at ? (
                <p className="m-0">
                  {t("admin.snapshot.publishedAt", {
                    relativeTime: formatRelativeTime(snapshot.published_at),
                  })}
                </p>
              ) : null}
              {snapshot.activated_at ? (
                <p className="m-0">
                  {t("admin.snapshot.activatedAt", {
                    relativeTime: formatRelativeTime(snapshot.activated_at),
                  })}
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
                  {t("admin.snapshot.test")}
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
                  {t("admin.snapshot.publish")}
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setConfirmationAction("publish-activate");
                  }}
                  type="button"
                >
                  <Rocket className="size-4" />
                  {t("admin.snapshot.publishAndActivate")}
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
                {t("admin.snapshot.activate")}
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
                {t("admin.snapshot.rollback")}
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
              {t("common.cancel")}
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
