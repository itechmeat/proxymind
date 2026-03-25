import { Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

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
import { getSourceIcon } from "@/lib/source-icons";
import { formatRelativeTime } from "@/lib/strings";
import type { SourceListItem } from "@/types/admin";

function sourceStatusVariant(status: SourceListItem["status"]) {
  switch (status) {
    case "pending":
      return "warning" as const;
    case "processing":
      return "info" as const;
    case "ready":
      return "success" as const;
    case "failed":
      return "error" as const;
    default:
      return "muted" as const;
  }
}

function SourceTypeCell({ source }: { source: SourceListItem }) {
  const { Icon, color } = getSourceIcon(source.source_type);

  return (
    <div className="flex items-center gap-2 text-sm text-stone-600">
      <Icon className="size-4" color={color} />
      <span className="capitalize">{source.source_type}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: SourceListItem["status"] }) {
  return (
    <Badge
      className={status === "processing" ? "animate-pulse" : undefined}
      variant={sourceStatusVariant(status)}
    >
      {status}
    </Badge>
  );
}

interface SourceListProps {
  deletingSourceId: string | null;
  onDelete: (source: SourceListItem) => void;
  sources: SourceListItem[];
}

export function SourceList({
  deletingSourceId,
  onDelete,
  sources,
}: SourceListProps) {
  const [pendingSource, setPendingSource] = useState<SourceListItem | null>(
    null,
  );

  const emptyState = useMemo(
    () => (
      <div className="rounded-[1.5rem] border border-dashed border-stone-300 bg-white/70 px-6 py-10 text-center text-sm text-stone-500">
        No sources yet. Upload a file to start building the knowledge base.
      </div>
    ),
    [],
  );

  if (sources.length === 0) {
    return emptyState;
  }

  return (
    <>
      <div className="hidden overflow-hidden rounded-[1.5rem] border border-white/70 bg-white/90 shadow-sm shadow-stone-900/5 md:block">
        <table className="min-w-full border-collapse">
          <thead className="bg-stone-100/80 text-left text-xs uppercase tracking-[0.16em] text-stone-500">
            <tr>
              <th className="px-5 py-4 font-medium">Title</th>
              <th className="px-5 py-4 font-medium">Type</th>
              <th className="px-5 py-4 font-medium">Status</th>
              <th className="px-5 py-4 font-medium">Created</th>
              <th className="px-5 py-4 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr className="border-t border-stone-200/80" key={source.id}>
                <td className="px-5 py-4 align-top">
                  <div className="space-y-1">
                    <p className="m-0 font-medium text-stone-950">
                      {source.title}
                    </p>
                    {source.description ? (
                      <p className="m-0 text-sm text-stone-500">
                        {source.description}
                      </p>
                    ) : null}
                  </div>
                </td>
                <td className="px-5 py-4 align-top">
                  <SourceTypeCell source={source} />
                </td>
                <td className="px-5 py-4 align-top">
                  <StatusBadge status={source.status} />
                </td>
                <td className="px-5 py-4 align-top text-sm text-stone-500">
                  {formatRelativeTime(source.created_at)}
                </td>
                <td className="px-5 py-4 text-right align-top">
                  <Button
                    aria-label={`Delete ${source.title}`}
                    disabled={deletingSourceId === source.id}
                    onClick={() => {
                      setPendingSource(source);
                    }}
                    size="icon-sm"
                    type="button"
                    variant="outline"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-3 md:hidden">
        {sources.map((source) => (
          <article
            className="rounded-[1.5rem] border border-white/70 bg-white/90 p-4 shadow-sm shadow-stone-900/5"
            key={source.id}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-2">
                <p className="m-0 font-medium text-stone-950">{source.title}</p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="muted">{source.source_type}</Badge>
                  <StatusBadge status={source.status} />
                </div>
                <p className="m-0 text-sm text-stone-500">
                  Added {formatRelativeTime(source.created_at)}
                </p>
              </div>
              <Button
                aria-label={`Delete ${source.title}`}
                disabled={deletingSourceId === source.id}
                onClick={() => {
                  setPendingSource(source);
                }}
                size="icon-sm"
                type="button"
                variant="outline"
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          </article>
        ))}
      </div>

      <AlertDialog
        open={pendingSource !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingSource(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete source {pendingSource?.title}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Chunks in published snapshots will remain until replaced.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancelButton type="button">
              Cancel
            </AlertDialogCancelButton>
            <AlertDialogActionButton
              onClick={() => {
                if (pendingSource) {
                  onDelete(pendingSource);
                }
                setPendingSource(null);
              }}
              type="button"
              variant="destructive"
            >
              Delete source
            </AlertDialogActionButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
