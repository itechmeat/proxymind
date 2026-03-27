import { Pencil, Trash2 } from "lucide-react";
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
import { translateCatalogItemType, useAppTranslation } from "@/lib/i18n";
import type { CatalogItem, CatalogItemType } from "@/types/admin";

function typeBadgeVariant(itemType: CatalogItemType) {
  switch (itemType) {
    case "book":
      return "info" as const;
    case "course":
      return "warning" as const;
    case "event":
      return "muted" as const;
    case "merch":
      return "success" as const;
    default:
      return "muted" as const;
  }
}

interface CatalogListProps {
  deletingItemId: string | null;
  filterType: CatalogItemType | null;
  items: CatalogItem[];
  onDelete: (item: CatalogItem) => void;
  onEdit: (item: CatalogItem) => void;
}

export function CatalogList({
  deletingItemId,
  filterType,
  items,
  onDelete,
  onEdit,
}: CatalogListProps) {
  const { t } = useAppTranslation();
  const [pendingItem, setPendingItem] = useState<CatalogItem | null>(null);

  if (items.length === 0) {
    return (
      <div className="rounded-[1.5rem] border border-dashed border-stone-300 bg-white/70 px-6 py-10 text-center text-sm text-stone-500">
        {filterType
          ? t("admin.catalog.emptyFiltered")
          : t("admin.catalog.emptyState")}
      </div>
    );
  }

  return (
    <>
      <div className="hidden overflow-hidden rounded-[1.5rem] border border-white/70 bg-white/90 shadow-sm shadow-stone-900/5 md:block">
        <table className="min-w-full border-collapse">
          <thead className="bg-stone-100/80 text-left text-xs uppercase tracking-[0.16em] text-stone-500">
            <tr>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.name")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.sku")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.type")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.catalog.table.sources")}
              </th>
              <th className="px-5 py-4 text-right font-medium">
                {t("admin.catalog.table.actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr className="border-t border-stone-200/80" key={item.id}>
                <td className="px-5 py-4 align-top">
                  <div className="space-y-1">
                    <p className="m-0 font-medium text-stone-950">
                      {item.name}
                    </p>
                    {item.description ? (
                      <p className="m-0 text-sm text-stone-500 line-clamp-1">
                        {item.description}
                      </p>
                    ) : null}
                  </div>
                </td>
                <td className="px-5 py-4 align-top font-mono text-sm text-stone-500">
                  {item.sku}
                </td>
                <td className="px-5 py-4 align-top">
                  <Badge variant={typeBadgeVariant(item.item_type)}>
                    {translateCatalogItemType(item.item_type)}
                  </Badge>
                </td>
                <td className="px-5 py-4 align-top text-sm text-stone-500">
                  {item.linked_sources_count > 0
                    ? t("admin.catalog.table.linkedCount", {
                        count: item.linked_sources_count,
                      })
                    : t("admin.catalog.table.noLinks")}
                </td>
                <td className="px-5 py-4 text-right align-top">
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      aria-label={t("admin.catalog.accessibility.editProduct", {
                        name: item.name,
                      })}
                      onClick={() => {
                        onEdit(item);
                      }}
                      size="icon-sm"
                      type="button"
                      variant="outline"
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      aria-label={t(
                        "admin.catalog.accessibility.deleteProduct",
                        { name: item.name },
                      )}
                      disabled={deletingItemId === item.id}
                      onClick={() => {
                        setPendingItem(item);
                      }}
                      size="icon-sm"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-3 md:hidden">
        {items.map((item) => (
          <article
            className="rounded-[1.5rem] border border-white/70 bg-white/90 p-4 shadow-sm shadow-stone-900/5"
            key={item.id}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-2">
                <p className="m-0 font-medium text-stone-950">{item.name}</p>
                <p className="m-0 font-mono text-xs text-stone-500">
                  {item.sku}
                </p>
                <Badge variant={typeBadgeVariant(item.item_type)}>
                  {translateCatalogItemType(item.item_type)}
                </Badge>
                <p className="m-0 text-sm text-stone-500">
                  {item.linked_sources_count > 0
                    ? t("admin.catalog.table.linkedCount", {
                        count: item.linked_sources_count,
                      })
                    : t("admin.catalog.table.noLinks")}
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  aria-label={t("admin.catalog.accessibility.editProduct", {
                    name: item.name,
                  })}
                  onClick={() => {
                    onEdit(item);
                  }}
                  size="icon-sm"
                  type="button"
                  variant="outline"
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  aria-label={t("admin.catalog.accessibility.deleteProduct", {
                    name: item.name,
                  })}
                  disabled={deletingItemId === item.id}
                  onClick={() => {
                    setPendingItem(item);
                  }}
                  size="icon-sm"
                  type="button"
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </div>
          </article>
        ))}
      </div>

      <AlertDialog
        onOpenChange={(open) => {
          if (!open) {
            setPendingItem(null);
          }
        }}
        open={pendingItem !== null}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingItem
                ? t("admin.catalog.delete.title", { name: pendingItem.name })
                : undefined}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingItem
                ? t("admin.catalog.delete.description", {
                    count: pendingItem.linked_sources_count,
                  })
                : undefined}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancelButton type="button">
              {t("common.cancel")}
            </AlertDialogCancelButton>
            <AlertDialogActionButton
              onClick={() => {
                if (pendingItem) {
                  onDelete(pendingItem);
                }
                setPendingItem(null);
              }}
              type="button"
              variant="destructive"
            >
              {t("admin.catalog.delete.action")}
            </AlertDialogActionButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
