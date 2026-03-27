import { CatalogFormDialog } from "@/components/CatalogFormDialog";
import { CatalogList } from "@/components/CatalogList";
import { Button } from "@/components/ui/button";
import { useCatalog } from "@/hooks/useCatalog";
import { useAppTranslation } from "@/lib/i18n";
import type { CatalogItemType } from "@/types/admin";

const FILTER_TYPES: CatalogItemType[] = [
  "book",
  "course",
  "event",
  "merch",
  "other",
];

export function CatalogTab() {
  const { t } = useAppTranslation();
  const {
    closeDialog,
    deletingItemId,
    editingItem,
    filterType,
    isDialogOpen,
    isLoading,
    isSaving,
    items,
    openCreate,
    openEdit,
    removeItem,
    saveItem,
    setFilterType,
  } = useCatalog();

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-3 rounded-[1.5rem] border border-white/70 bg-white/90 px-4 py-4 shadow-sm shadow-stone-900/5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <Button onClick={openCreate} type="button">
          {t("admin.catalog.addProduct")}
        </Button>

        <label className="flex items-center gap-3 text-sm text-stone-600">
          {t("admin.catalog.table.type")}
          <select
            className="rounded-full border border-stone-200 bg-white px-3 py-2 text-sm text-stone-950 outline-none"
            onChange={(event) => {
              const value = event.target.value as CatalogItemType | "";
              setFilterType(value ? value : null);
            }}
            value={filterType ?? ""}
          >
            <option value="">{t("admin.catalog.filterAll")}</option>
            {FILTER_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`admin.catalog.type.${type}`)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading ? (
        <div className="rounded-[1.5rem] border border-white/70 bg-white/90 px-6 py-8 text-sm text-stone-500 shadow-sm shadow-stone-900/5">
          {t("admin.catalog.loading")}
        </div>
      ) : (
        <CatalogList
          deletingItemId={deletingItemId}
          filterType={filterType}
          items={items}
          onDelete={(item) => {
            void removeItem(item);
          }}
          onEdit={openEdit}
        />
      )}

      <CatalogFormDialog
        editingItem={editingItem}
        isSaving={isSaving}
        onClose={closeDialog}
        onSave={saveItem}
        open={isDialogOpen}
      />
    </section>
  );
}
