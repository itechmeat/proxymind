import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "@/hooks/useToast";
import {
  deleteSource,
  getCatalogItems,
  getSources,
  updateSource,
  uploadSource,
} from "@/lib/admin-api";
import { translate } from "@/lib/i18n";
import type { CatalogItem, SourceListItem } from "@/types/admin";

const SOURCE_STATUS_POLL_INTERVAL_MS = 3000;
const DEFAULT_CATALOG_REFRESH_INTERVAL_MS = 60000;
const CATALOG_FOCUS_REFRESH_DEBOUNCE_MS = 1000;

interface UseSourcesOptions {
  catalogRefreshIntervalMs?: number;
}

function resolveCatalogLoadErrorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : translate("admin.sourceLink.loadFailed");
}

export const ALLOWED_SOURCE_EXTENSIONS = new Set([
  ".md",
  ".txt",
  ".pdf",
  ".docx",
  ".html",
  ".htm",
  ".png",
  ".jpg",
  ".jpeg",
  ".mp3",
  ".wav",
  ".mp4",
]);

export function deriveSourceTitle(filename: string) {
  const trimmed = filename.trim();
  const dotIndex = trimmed.lastIndexOf(".");
  if (dotIndex <= 0) {
    return trimmed || translate("admin.source.untitled");
  }

  return trimmed.slice(0, dotIndex) || trimmed;
}

export function validateSourceFile(file: File) {
  const name = file.name.trim();
  const extension = name.includes(".")
    ? name.slice(name.lastIndexOf(".")).toLowerCase()
    : "";

  if (!ALLOWED_SOURCE_EXTENSIONS.has(extension)) {
    return translate("admin.source.unsupportedType", { filename: file.name });
  }

  if (file.size === 0) {
    return translate("admin.source.emptyFile", { filename: file.name });
  }

  return null;
}

function hasProcessingSources(sources: SourceListItem[]) {
  return sources.some(
    (source) => source.status === "pending" || source.status === "processing",
  );
}

export function useSources({
  catalogRefreshIntervalMs = DEFAULT_CATALOG_REFRESH_INTERVAL_MS,
}: UseSourcesOptions = {}) {
  const { pushToast } = useToast();
  const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
  const [catalogLoadError, setCatalogLoadError] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshingCatalog, setIsRefreshingCatalog] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [deletingSourceId, setDeletingSourceId] = useState<string | null>(null);
  const [linkingSourceId, setLinkingSourceId] = useState<string | null>(null);
  const sourcePollingIntervalRef = useRef<number | null>(null);
  const catalogPollingIntervalRef = useRef<number | null>(null);
  const lastCatalogFocusRefreshRef = useRef(0);

  const refreshSources = useCallback(async () => {
    const nextSources = await getSources();
    setSources(nextSources);
    return nextSources;
  }, []);

  const refreshCatalogItems = useCallback(async () => {
    setIsRefreshingCatalog(true);

    try {
      const response = await getCatalogItems();
      setCatalogItems(response.items);
      setCatalogLoadError(null);
      return response.items;
    } catch (error) {
      setCatalogLoadError(resolveCatalogLoadErrorMessage(error));
      throw error;
    } finally {
      setIsRefreshingCatalog(false);
    }
  }, []);
  const shouldPoll = hasProcessingSources(sources);

  useEffect(() => {
    let active = true;

    void (async () => {
      const [sourcesResult, catalogResult] = await Promise.allSettled([
        getSources(),
        getCatalogItems(),
      ]);

      if (sourcesResult.status === "fulfilled") {
        if (active) {
          setSources(sourcesResult.value);
        }
      } else if (active) {
        pushToast({
          message:
            sourcesResult.reason instanceof Error
              ? sourcesResult.reason.message
              : translate("admin.source.loadFailed"),
          tone: "error",
        });
      }

      if (catalogResult.status === "fulfilled") {
        if (active) {
          setCatalogItems(catalogResult.value.items);
          setCatalogLoadError(null);
        }
      } else if (active) {
        setCatalogLoadError(
          resolveCatalogLoadErrorMessage(catalogResult.reason),
        );
      }

      if (active) {
        setIsLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [pushToast]);

  useEffect(() => {
    if (!shouldPoll) {
      if (sourcePollingIntervalRef.current !== null) {
        window.clearInterval(sourcePollingIntervalRef.current);
        sourcePollingIntervalRef.current = null;
      }
      return undefined;
    }

    if (sourcePollingIntervalRef.current !== null) {
      return undefined;
    }

    sourcePollingIntervalRef.current = window.setInterval(() => {
      void refreshSources().catch(() => {
        pushToast({
          message: translate("admin.source.statusRefreshFailed"),
          tone: "error",
        });
      });
    }, SOURCE_STATUS_POLL_INTERVAL_MS);

    return () => {
      if (sourcePollingIntervalRef.current !== null) {
        window.clearInterval(sourcePollingIntervalRef.current);
        sourcePollingIntervalRef.current = null;
      }
    };
  }, [pushToast, refreshSources, shouldPoll]);

  useEffect(() => {
    if (catalogRefreshIntervalMs <= 0) {
      if (catalogPollingIntervalRef.current !== null) {
        window.clearInterval(catalogPollingIntervalRef.current);
        catalogPollingIntervalRef.current = null;
      }
      return undefined;
    }

    catalogPollingIntervalRef.current = window.setInterval(() => {
      void refreshCatalogItems().catch((error) => {
        pushToast({
          message: resolveCatalogLoadErrorMessage(error),
          tone: "warning",
        });
      });
    }, catalogRefreshIntervalMs);

    return () => {
      if (catalogPollingIntervalRef.current !== null) {
        window.clearInterval(catalogPollingIntervalRef.current);
        catalogPollingIntervalRef.current = null;
      }
    };
  }, [catalogRefreshIntervalMs, pushToast, refreshCatalogItems]);

  useEffect(() => {
    const refreshCatalogOnFocus = (event: Event) => {
      if (
        event.type === "visibilitychange" &&
        document.visibilityState === "hidden"
      ) {
        return;
      }

      const now = Date.now();
      if (
        now - lastCatalogFocusRefreshRef.current <
        CATALOG_FOCUS_REFRESH_DEBOUNCE_MS
      ) {
        return;
      }

      lastCatalogFocusRefreshRef.current = now;

      void refreshCatalogItems().catch((error) => {
        pushToast({
          message: resolveCatalogLoadErrorMessage(error),
          tone: "warning",
        });
      });
    };

    window.addEventListener("focus", refreshCatalogOnFocus);
    document.addEventListener("visibilitychange", refreshCatalogOnFocus);

    return () => {
      window.removeEventListener("focus", refreshCatalogOnFocus);
      document.removeEventListener("visibilitychange", refreshCatalogOnFocus);
    };
  }, [pushToast, refreshCatalogItems]);

  const uploadFiles = useCallback(
    async (files: File[], catalogItemId?: string | null) => {
      const validFiles: File[] = [];

      for (const file of files) {
        const validationError = validateSourceFile(file);
        if (validationError) {
          pushToast({
            message: validationError,
            tone: "error",
          });
          continue;
        }

        validFiles.push(file);
      }

      if (validFiles.length === 0) {
        return;
      }

      setIsUploading(true);
      try {
        const results = await Promise.allSettled(
          validFiles.map((file) =>
            uploadSource(file, {
              title: deriveSourceTitle(file.name),
              ...(catalogItemId ? { catalog_item_id: catalogItemId } : {}),
            }),
          ),
        );

        for (const [index, result] of results.entries()) {
          if (result.status === "fulfilled") {
            pushToast({
              message: translate("admin.source.queuedForIngestion", {
                filename:
                  validFiles[index]?.name ?? translate("admin.source.untitled"),
              }),
              tone: "success",
            });
            continue;
          }

          pushToast({
            message:
              result.reason instanceof Error
                ? result.reason.message
                : translate("admin.source.uploadFailed", {
                    filename:
                      validFiles[index]?.name ??
                      translate("admin.source.untitled"),
                  }),
            tone: "error",
          });
        }

        try {
          await Promise.all([refreshSources(), refreshCatalogItems()]);
        } catch (error) {
          pushToast({
            message:
              error instanceof Error
                ? error.message
                : translate("admin.source.refreshFailed"),
            tone: "warning",
          });
        }
      } finally {
        setIsUploading(false);
      }
    },
    [pushToast, refreshCatalogItems, refreshSources],
  );

  const linkSourceToCatalog = useCallback(
    async (sourceId: string, catalogItemId: string | null) => {
      setLinkingSourceId(sourceId);
      try {
        const updatedSource = await updateSource(sourceId, {
          catalog_item_id: catalogItemId,
        });
        setSources((current) =>
          current.map((source) =>
            source.id === sourceId ? updatedSource : source,
          ),
        );

        try {
          await refreshSources();
        } catch (error) {
          pushToast({
            message:
              error instanceof Error
                ? error.message
                : translate("admin.source.refreshFailed"),
            tone: "warning",
          });
        }
      } catch (error) {
        pushToast({
          message:
            error instanceof Error
              ? error.message
              : translate("admin.sourceLink.updateFailed"),
          tone: "error",
        });
      } finally {
        setLinkingSourceId(null);
      }
    },
    [pushToast, refreshSources],
  );

  const removeSource = useCallback(
    async (source: SourceListItem) => {
      setDeletingSourceId(source.id);
      try {
        const response = await deleteSource(source.id);
        setSources((current) =>
          current.filter((item) => item.id !== source.id),
        );

        if (response.warnings.length > 0) {
          for (const warning of response.warnings) {
            pushToast({ message: warning, tone: "warning" });
          }
        } else {
          pushToast({
            message: translate("admin.source.deleted", { title: source.title }),
            tone: "success",
          });
        }

        try {
          await refreshSources();
        } catch (error) {
          pushToast({
            message:
              error instanceof Error
                ? error.message
                : translate("admin.source.refreshFailed"),
            tone: "warning",
          });
        }
      } catch (error) {
        pushToast({
          message:
            error instanceof Error
              ? error.message
              : translate("admin.source.deleteFailed"),
          tone: "error",
        });
      } finally {
        setDeletingSourceId(null);
      }
    },
    [pushToast, refreshSources],
  );

  return {
    catalogItems,
    catalogLoadError,
    deletingSourceId,
    isLoading,
    isRefreshingCatalog,
    isUploading,
    linkingSourceId,
    linkSourceToCatalog,
    refreshCatalogItems,
    refreshSources,
    removeSource,
    sources,
    uploadFiles,
  };
}
