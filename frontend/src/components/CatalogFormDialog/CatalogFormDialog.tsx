import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { getCatalogItem } from "@/lib/admin-api";
import {
  translateCatalogItemType,
  translateSourceStatus,
  translateSourceType,
  useAppTranslation,
} from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type {
  CatalogItem,
  CatalogItemCreate,
  CatalogItemType,
  CatalogItemUpdate,
  LinkedSource,
} from "@/types/admin";

const ITEM_TYPES: CatalogItemType[] = [
  "book",
  "course",
  "event",
  "merch",
  "other",
];

type ValidationErrors = Partial<
  Record<"sku" | "name" | "url" | "imageUrl" | "validUntil", string>
>;

interface CatalogFormDialogProps {
  editingItem: CatalogItem | null;
  isSaving: boolean;
  onClose: () => void;
  onSave: (data: CatalogItemCreate | CatalogItemUpdate) => Promise<void> | void;
  open: boolean;
}

function normalizeOptionalText(value: string) {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function toIsoDate(value: string) {
  if (!value) {
    return null;
  }

  return `${value}T00:00:00.000Z`;
}

function isValidUrl(value: string) {
  try {
    new URL(value);
    return true;
  } catch {
    return false;
  }
}

function fieldClassName(hasError: boolean) {
  return cn(
    "w-full rounded-2xl border bg-white px-4 py-3 text-sm text-stone-950 outline-none transition focus:border-sky-400 focus:bg-white",
    hasError
      ? "border-rose-300 focus:border-rose-400"
      : "border-stone-200 bg-stone-50",
  );
}

export function CatalogFormDialog({
  editingItem,
  isSaving,
  onClose,
  onSave,
  open,
}: CatalogFormDialogProps) {
  const { t } = useAppTranslation();
  const isEditMode = editingItem !== null;
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [itemType, setItemType] = useState<CatalogItemType>("book");
  const [url, setUrl] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [linkedSources, setLinkedSources] = useState<LinkedSource[]>([]);
  const [isLoadingLinkedSources, setIsLoadingLinkedSources] = useState(false);
  const [linkedSourcesError, setLinkedSourcesError] = useState<string | null>(
    null,
  );
  const [validationErrors, setValidationErrors] = useState<ValidationErrors>(
    {},
  );

  useEffect(() => {
    if (!open) {
      return;
    }

    setValidationErrors({});
    setLinkedSourcesError(null);

    if (!editingItem) {
      setSku("");
      setName("");
      setDescription("");
      setItemType("book");
      setUrl("");
      setImageUrl("");
      setValidFrom("");
      setValidUntil("");
      setLinkedSources([]);
      setIsLoadingLinkedSources(false);
      return;
    }

    setSku(editingItem.sku);
    setName(editingItem.name);
    setDescription(editingItem.description ?? "");
    setItemType(editingItem.item_type);
    setUrl(editingItem.url ?? "");
    setImageUrl(editingItem.image_url ?? "");
    setValidFrom(editingItem.valid_from?.slice(0, 10) ?? "");
    setValidUntil(editingItem.valid_until?.slice(0, 10) ?? "");
    setLinkedSources([]);
    setIsLoadingLinkedSources(true);

    let active = true;

    void (async () => {
      try {
        const detail = await getCatalogItem(editingItem.id);
        if (active) {
          setLinkedSources(detail.linked_sources);
        }
      } catch (error) {
        if (active) {
          setLinkedSourcesError(
            error instanceof Error
              ? error.message
              : t("admin.catalog.form.linkedSourcesLoadFailed"),
          );
        }
      } finally {
        if (active) {
          setIsLoadingLinkedSources(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [editingItem, open, t]);

  const validate = () => {
    const nextErrors: ValidationErrors = {};

    if (!sku.trim()) {
      nextErrors.sku = t("admin.catalog.form.validation.skuRequired");
    }

    if (!name.trim()) {
      nextErrors.name = t("admin.catalog.form.validation.nameRequired");
    }

    if (url.trim() && !isValidUrl(url.trim())) {
      nextErrors.url = t("admin.catalog.form.validation.urlInvalid");
    }

    if (imageUrl.trim() && !isValidUrl(imageUrl.trim())) {
      nextErrors.imageUrl = t("admin.catalog.form.validation.imageUrlInvalid");
    }

    if (validFrom && validUntil && validUntil < validFrom) {
      nextErrors.validUntil = t("admin.catalog.form.validation.dateRange");
    }

    setValidationErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const buildCreatePayload = (): CatalogItemCreate => ({
    sku: sku.trim(),
    name: name.trim(),
    item_type: itemType,
    description: normalizeOptionalText(description),
    url: normalizeOptionalText(url),
    image_url: normalizeOptionalText(imageUrl),
    valid_from: toIsoDate(validFrom),
    valid_until: toIsoDate(validUntil),
  });

  const buildUpdatePayload = (): CatalogItemUpdate => {
    if (!editingItem) {
      return {};
    }

    const nextPayload: CatalogItemUpdate = {};
    const nextDescription = normalizeOptionalText(description);
    const nextUrl = normalizeOptionalText(url);
    const nextImageUrl = normalizeOptionalText(imageUrl);
    const nextValidFrom = toIsoDate(validFrom);
    const nextValidUntil = toIsoDate(validUntil);

    if (sku.trim() !== editingItem.sku) {
      nextPayload.sku = sku.trim();
    }
    if (name.trim() !== editingItem.name) {
      nextPayload.name = name.trim();
    }
    if (nextDescription !== editingItem.description) {
      nextPayload.description = nextDescription;
    }
    if (itemType !== editingItem.item_type) {
      nextPayload.item_type = itemType;
    }
    if (nextUrl !== editingItem.url) {
      nextPayload.url = nextUrl;
    }
    if (nextImageUrl !== editingItem.image_url) {
      nextPayload.image_url = nextImageUrl;
    }
    if ((editingItem.valid_from?.slice(0, 10) ?? "") !== validFrom) {
      nextPayload.valid_from = nextValidFrom;
    }
    if ((editingItem.valid_until?.slice(0, 10) ?? "") !== validUntil) {
      nextPayload.valid_until = nextValidUntil;
    }

    return nextPayload;
  };

  const submit = async () => {
    if (!validate()) {
      return;
    }

    const payload = editingItem ? buildUpdatePayload() : buildCreatePayload();
    await onSave(payload);
  };

  return (
    <Dialog.Root
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onClose();
        }
      }}
      open={open}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-stone-950/45 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(44rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-[2rem] border border-white/70 bg-white shadow-2xl shadow-stone-900/20 outline-none">
          <div className="flex items-start justify-between gap-4 border-b border-stone-200 px-6 py-5">
            <div className="space-y-1">
              <Dialog.Title className="text-xl font-semibold tracking-[-0.02em] text-stone-950">
                {isEditMode
                  ? t("admin.catalog.form.editTitle")
                  : t("admin.catalog.form.createTitle")}
              </Dialog.Title>
              <Dialog.Description className="text-sm text-stone-500">
                {t("admin.catalog.form.description")}
              </Dialog.Description>
            </div>

            <Dialog.Close asChild>
              <button
                aria-label={t("common.cancel")}
                className="rounded-full border border-stone-200 p-2 text-stone-500 transition hover:bg-stone-100 hover:text-stone-900"
                type="button"
              >
                <X className="size-4" />
              </button>
            </Dialog.Close>
          </div>

          <div className="overflow-y-auto px-6 py-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.sku")}
                <input
                  className={fieldClassName(Boolean(validationErrors.sku))}
                  maxLength={64}
                  onChange={(event) => {
                    setSku(event.target.value);
                    setValidationErrors((current) => ({
                      ...current,
                      sku: undefined,
                    }));
                  }}
                  placeholder={t("admin.catalog.form.skuPlaceholder")}
                  type="text"
                  value={sku}
                />
                {validationErrors.sku ? (
                  <span className="text-sm text-rose-600">
                    {validationErrors.sku}
                  </span>
                ) : null}
              </label>

              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.name")}
                <input
                  className={fieldClassName(Boolean(validationErrors.name))}
                  maxLength={255}
                  onChange={(event) => {
                    setName(event.target.value);
                    setValidationErrors((current) => ({
                      ...current,
                      name: undefined,
                    }));
                  }}
                  placeholder={t("admin.catalog.form.namePlaceholder")}
                  type="text"
                  value={name}
                />
                {validationErrors.name ? (
                  <span className="text-sm text-rose-600">
                    {validationErrors.name}
                  </span>
                ) : null}
              </label>

              <div className="grid gap-2 text-sm font-medium text-stone-700 sm:col-span-2">
                <label htmlFor="catalog-description">
                  {t("admin.catalog.form.descriptionLabel")}
                </label>
                <Textarea
                  className={cn(
                    "min-h-28 rounded-2xl border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-950",
                    "focus-visible:border-sky-400 focus-visible:ring-sky-200",
                  )}
                  id="catalog-description"
                  maxLength={2000}
                  onChange={(event) => {
                    setDescription(event.target.value);
                  }}
                  placeholder={t("admin.catalog.form.descriptionPlaceholder")}
                  value={description}
                />
              </div>

              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.itemType")}
                <select
                  className={fieldClassName(false)}
                  onChange={(event) => {
                    setItemType(event.target.value as CatalogItemType);
                  }}
                  value={itemType}
                >
                  {ITEM_TYPES.map((value) => (
                    <option key={value} value={value}>
                      {translateCatalogItemType(value)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.url")}
                <input
                  className={fieldClassName(Boolean(validationErrors.url))}
                  onChange={(event) => {
                    setUrl(event.target.value);
                    setValidationErrors((current) => ({
                      ...current,
                      url: undefined,
                    }));
                  }}
                  placeholder={t("admin.catalog.form.urlPlaceholder")}
                  type="url"
                  value={url}
                />
                {validationErrors.url ? (
                  <span className="text-sm text-rose-600">
                    {validationErrors.url}
                  </span>
                ) : null}
              </label>

              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.imageUrl")}
                <input
                  className={fieldClassName(Boolean(validationErrors.imageUrl))}
                  onChange={(event) => {
                    setImageUrl(event.target.value);
                    setValidationErrors((current) => ({
                      ...current,
                      imageUrl: undefined,
                    }));
                  }}
                  placeholder={t("admin.catalog.form.imageUrlPlaceholder")}
                  type="url"
                  value={imageUrl}
                />
                {validationErrors.imageUrl ? (
                  <span className="text-sm text-rose-600">
                    {validationErrors.imageUrl}
                  </span>
                ) : null}
              </label>

              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.validFrom")}
                <input
                  className={fieldClassName(false)}
                  onChange={(event) => {
                    setValidFrom(event.target.value);
                    setValidationErrors((current) => ({
                      ...current,
                      validUntil: undefined,
                    }));
                  }}
                  type="date"
                  value={validFrom}
                />
              </label>

              <label className="grid gap-2 text-sm font-medium text-stone-700">
                {t("admin.catalog.form.validUntil")}
                <input
                  className={fieldClassName(
                    Boolean(validationErrors.validUntil),
                  )}
                  onChange={(event) => {
                    setValidUntil(event.target.value);
                    setValidationErrors((current) => ({
                      ...current,
                      validUntil: undefined,
                    }));
                  }}
                  type="date"
                  value={validUntil}
                />
                {validationErrors.validUntil ? (
                  <span className="text-sm text-rose-600">
                    {validationErrors.validUntil}
                  </span>
                ) : null}
              </label>
            </div>

            {isEditMode ? (
              <div className="mt-6 rounded-[1.5rem] border border-stone-200 bg-stone-50 px-5 py-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="m-0 text-sm font-semibold uppercase tracking-[0.16em] text-stone-500">
                    {t("admin.catalog.form.linkedSources")}
                  </h3>
                  {isLoadingLinkedSources ? (
                    <span className="text-sm text-stone-500">
                      {t("admin.catalog.form.linkedSourcesLoading")}
                    </span>
                  ) : null}
                </div>

                {linkedSourcesError ? (
                  <p className="m-0 text-sm text-rose-600">
                    {linkedSourcesError}
                  </p>
                ) : null}

                {!isLoadingLinkedSources && !linkedSourcesError ? (
                  linkedSources.length > 0 ? (
                    <div className="grid gap-3">
                      {linkedSources.map((source) => (
                        <div
                          className="rounded-2xl border border-white/80 bg-white px-4 py-3 shadow-sm shadow-stone-900/5"
                          key={source.id}
                        >
                          <p className="m-0 font-medium text-stone-950">
                            {source.title}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Badge variant="muted">
                              {translateSourceType(source.source_type)}
                            </Badge>
                            <Badge
                              variant={
                                source.status === "ready"
                                  ? "success"
                                  : source.status === "failed"
                                    ? "error"
                                    : source.status === "processing"
                                      ? "info"
                                      : "warning"
                              }
                            >
                              {translateSourceStatus(source.status)}
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="m-0 text-sm text-stone-500">
                      {t("admin.catalog.form.noLinkedSources")}
                    </p>
                  )
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-stone-200 px-6 py-4">
            <Button onClick={onClose} type="button" variant="outline">
              {t("admin.catalog.form.cancel")}
            </Button>
            <Button
              disabled={isSaving}
              onClick={() => void submit()}
              type="button"
            >
              {isEditMode
                ? t("admin.catalog.form.save")
                : t("admin.catalog.form.create")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
