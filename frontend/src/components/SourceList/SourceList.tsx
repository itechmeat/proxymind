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
import {
  translateSourceStatus,
  translateSourceType,
  useAppTranslation,
} from "@/lib/i18n";
import { getSourceIcon } from "@/lib/source-icons";
import { formatRelativeTime } from "@/lib/strings";
import type { CatalogItem, SourceListItem } from "@/types/admin";

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
      <span>{translateSourceType(source.source_type)}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: SourceListItem["status"] }) {
  return (
    <Badge
      className={status === "processing" ? "animate-pulse" : undefined}
      variant={sourceStatusVariant(status)}
    >
      {translateSourceStatus(status)}
    </Badge>
  );
}

interface SourceListProps {
  catalogItems: CatalogItem[];
  catalogLoadError: string | null;
  deletingSourceId: string | null;
  linkingSourceId: string | null;
  onDelete: (source: SourceListItem) => void;
  onLinkCatalogItem: (sourceId: string, catalogItemId: string | null) => void;
  sources: SourceListItem[];
}

function productOptionLabel(item: CatalogItem) {
  return `${item.name} (${item.sku})`;
}

function findSelectedCatalogItem(
  source: SourceListItem,
  catalogItems: CatalogItem[],
) {
  if (!source.catalog_item_id) {
    return null;
  }

  return (
    catalogItems.find((item) => item.id === source.catalog_item_id) ?? {
      id: source.catalog_item_id,
      label: "fallback",
    }
  );
}

function ProductSelect({
  catalogItems,
  catalogLoadError,
  disabled,
  id,
  onChange,
  source,
}: {
  catalogItems: CatalogItem[];
  catalogLoadError: string | null;
  disabled: boolean;
  id?: string;
  onChange: (catalogItemId: string | null) => void;
  source: SourceListItem;
}) {
  const { t } = useAppTranslation();
  const selectedItem = findSelectedCatalogItem(source, catalogItems);
  const isStale =
    selectedItem !== null &&
    !catalogItems.some((item) => item.id === source.catalog_item_id);
  const showCatalogLoadFailedOption =
    catalogLoadError !== null && catalogItems.length === 0;
  const showNoProductsOption =
    catalogLoadError === null && catalogItems.length === 0;
  const isDisabled = disabled || (catalogItems.length === 0 && !isStale);
  const value = source.catalog_item_id
    ? source.catalog_item_id
    : showCatalogLoadFailedOption
      ? "__load_failed__"
      : showNoProductsOption
        ? "__empty__"
        : "";

  return (
    <select
      aria-label={`${t("admin.sourceLink.label")} ${source.title}`}
      className="w-full rounded-full border border-stone-200 bg-white px-3 py-2 text-sm text-stone-950 outline-none disabled:cursor-not-allowed disabled:opacity-60"
      disabled={isDisabled}
      id={id}
      onChange={(event) => {
        const value = event.target.value;
        onChange(value || null);
      }}
      value={value}
    >
      <option value="">{t("admin.sourceLink.placeholder")}</option>
      {isStale && source.catalog_item_id ? (
        <option value={source.catalog_item_id}>
          ({t("admin.sourceLink.unknownProduct")})
        </option>
      ) : null}
      {showCatalogLoadFailedOption ? (
        <option disabled value="__load_failed__">
          {t("admin.sourceLink.loadFailed")}
        </option>
      ) : null}
      {showNoProductsOption ? (
        <option disabled value="__empty__">
          {t("admin.sourceLink.noProducts")}
        </option>
      ) : null}
      {catalogItems.map((item) => (
        <option key={item.id} value={item.id}>
          {productOptionLabel(item)}
        </option>
      ))}
    </select>
  );
}

export function SourceList({
  catalogItems,
  catalogLoadError,
  deletingSourceId,
  linkingSourceId,
  onDelete,
  onLinkCatalogItem,
  sources,
}: SourceListProps) {
  const { t } = useAppTranslation();
  const [pendingSource, setPendingSource] = useState<SourceListItem | null>(
    null,
  );

  const emptyState = useMemo(
    () => (
      <div className="rounded-[1.5rem] border border-dashed border-stone-300 bg-white/70 px-6 py-10 text-center text-sm text-stone-500">
        {t("admin.source.emptyState")}
      </div>
    ),
    [t],
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
              <th className="px-5 py-4 font-medium">
                {t("admin.source.table.title")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.source.table.type")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.source.table.status")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.sourceLink.label")}
              </th>
              <th className="px-5 py-4 font-medium">
                {t("admin.source.table.created")}
              </th>
              <th className="px-5 py-4 font-medium text-right">
                {t("admin.source.table.actions")}
              </th>
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
                <td className="px-5 py-4 align-top">
                  <ProductSelect
                    catalogItems={catalogItems}
                    catalogLoadError={catalogLoadError}
                    disabled={linkingSourceId === source.id}
                    id={`source-product-${source.id}`}
                    onChange={(catalogItemId) => {
                      onLinkCatalogItem(source.id, catalogItemId);
                    }}
                    source={source}
                  />
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
                  <Badge variant="muted">
                    {translateSourceType(source.source_type)}
                  </Badge>
                  <StatusBadge status={source.status} />
                </div>
                <div className="grid gap-2 text-sm text-stone-600">
                  <label htmlFor={`source-product-mobile-${source.id}`}>
                    {t("admin.sourceLink.label")}
                  </label>
                  <ProductSelect
                    catalogItems={catalogItems}
                    catalogLoadError={catalogLoadError}
                    disabled={linkingSourceId === source.id}
                    id={`source-product-mobile-${source.id}`}
                    onChange={(catalogItemId) => {
                      onLinkCatalogItem(source.id, catalogItemId);
                    }}
                    source={source}
                  />
                </div>
                <p className="m-0 text-sm text-stone-500">
                  {t("admin.source.addedAt", {
                    relativeTime: formatRelativeTime(source.created_at),
                  })}
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
              {pendingSource
                ? t("admin.source.deleteTitle", { title: pendingSource.title })
                : undefined}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("admin.source.deleteDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancelButton type="button">
              {t("common.cancel")}
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
              {t("admin.source.deleteAction")}
            </AlertDialogActionButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
