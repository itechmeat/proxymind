import { useEffect, useState } from "react";

import { DropZone } from "@/components/DropZone/DropZone";
import { SourceList } from "@/components/SourceList/SourceList";
import { Button } from "@/components/ui/button";
import { useSources } from "@/hooks/useSources";
import { useAppTranslation } from "@/lib/i18n";

export function SourcesTab() {
  const { t } = useAppTranslation();
  const [uploadCatalogItemId, setUploadCatalogItemId] = useState<string>("");
  const {
    catalogItems,
    catalogLoadError,
    deletingSourceId,
    isLoading,
    isRefreshingCatalog,
    isUploading,
    linkingSourceId,
    linkSourceToCatalog,
    refreshCatalogItems,
    removeSource,
    sources,
    uploadFiles,
  } = useSources();
  const showCatalogLoadFailedState =
    catalogLoadError !== null && catalogItems.length === 0;
  const showNoProductsState =
    catalogLoadError === null && catalogItems.length === 0;
  const uploadSelectValue = uploadCatalogItemId
    ? uploadCatalogItemId
    : showCatalogLoadFailedState
      ? "__load_failed__"
      : showNoProductsState
        ? "__empty__"
        : "";

  useEffect(() => {
    if (
      uploadCatalogItemId &&
      !catalogItems.some((item) => item.id === uploadCatalogItemId)
    ) {
      setUploadCatalogItemId("");
    }
  }, [catalogItems, uploadCatalogItemId]);

  return (
    <section className="space-y-5">
      <div className="space-y-3 rounded-[1.75rem] border border-white/70 bg-white/70 p-3 shadow-sm shadow-stone-900/5">
        <DropZone
          disabled={isUploading}
          isUploading={isUploading}
          onFiles={(files) => {
            void uploadFiles(files, uploadCatalogItemId || null);
          }}
        />

        <div className="rounded-[1.25rem] border border-stone-200 bg-stone-50 px-4 py-3">
          <label className="grid gap-2 text-sm font-medium text-stone-700">
            {t("admin.sourceLink.label")}
            <select
              className="rounded-full border border-stone-200 bg-white px-3 py-2 text-sm font-normal text-stone-950 outline-none disabled:cursor-not-allowed disabled:opacity-60"
              disabled={
                isRefreshingCatalog ||
                showCatalogLoadFailedState ||
                showNoProductsState
              }
              onChange={(event) => {
                setUploadCatalogItemId(event.target.value);
              }}
              value={uploadSelectValue}
            >
              <option value="">{t("admin.sourceLink.placeholder")}</option>
              {showCatalogLoadFailedState ? (
                <option disabled value="__load_failed__">
                  {t("admin.sourceLink.loadFailed")}
                </option>
              ) : null}
              {showNoProductsState ? (
                <option disabled value="__empty__">
                  {t("admin.sourceLink.noProducts")}
                </option>
              ) : null}
              {catalogItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {`${item.name} (${item.sku})`}
                </option>
              ))}
            </select>
          </label>

          {showCatalogLoadFailedState ? (
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <p className="mb-0 text-sm text-rose-600">{catalogLoadError}</p>
              <Button
                disabled={isRefreshingCatalog}
                onClick={() => {
                  void refreshCatalogItems().catch(() => {});
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                {t("admin.sourceLink.retry")}
              </Button>
            </div>
          ) : showNoProductsState ? (
            <p className="mb-0 mt-2 text-sm text-stone-500">
              {t("admin.sourceLink.noProductsHint")}
            </p>
          ) : null}
        </div>
      </div>

      {isLoading ? (
        <div className="rounded-[1.5rem] border border-white/70 bg-white/90 px-6 py-8 text-sm text-stone-500 shadow-sm shadow-stone-900/5">
          {t("admin.loading.sources")}
        </div>
      ) : (
        <SourceList
          catalogItems={catalogItems}
          catalogLoadError={catalogLoadError}
          deletingSourceId={deletingSourceId}
          linkingSourceId={linkingSourceId}
          onDelete={(source) => {
            void removeSource(source);
          }}
          onLinkCatalogItem={(sourceId, catalogItemId) => {
            void linkSourceToCatalog(sourceId, catalogItemId);
          }}
          sources={sources}
        />
      )}
    </section>
  );
}
