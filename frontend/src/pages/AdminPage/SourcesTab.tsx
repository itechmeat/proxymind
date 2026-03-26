import { DropZone } from "@/components/DropZone/DropZone";
import { SourceList } from "@/components/SourceList/SourceList";
import { useSources } from "@/hooks/useSources";
import { useAppTranslation } from "@/lib/i18n";

export function SourcesTab() {
  const { t } = useAppTranslation();
  const {
    deletingSourceId,
    isLoading,
    isUploading,
    removeSource,
    sources,
    uploadFiles,
  } = useSources();

  return (
    <section className="space-y-5">
      <DropZone
        disabled={isUploading}
        isUploading={isUploading}
        onFiles={(files) => {
          void uploadFiles(files);
        }}
      />

      {isLoading ? (
        <div className="rounded-[1.5rem] border border-white/70 bg-white/90 px-6 py-8 text-sm text-stone-500 shadow-sm shadow-stone-900/5">
          {t("admin.loading.sources")}
        </div>
      ) : (
        <SourceList
          deletingSourceId={deletingSourceId}
          onDelete={(source) => {
            void removeSource(source);
          }}
          sources={sources}
        />
      )}
    </section>
  );
}
