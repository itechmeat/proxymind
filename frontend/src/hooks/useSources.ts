import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "@/hooks/useToast";
import { deleteSource, getSources, uploadSource } from "@/lib/admin-api";
import type { SourceListItem } from "@/types/admin";

const POLL_INTERVAL_MS = 3000;

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
    return trimmed || "Untitled source";
  }

  return trimmed.slice(0, dotIndex) || trimmed;
}

export function validateSourceFile(file: File) {
  const name = file.name.trim();
  const extension = name.includes(".")
    ? name.slice(name.lastIndexOf(".")).toLowerCase()
    : "";

  if (!ALLOWED_SOURCE_EXTENSIONS.has(extension)) {
    return `Unsupported file type for ${file.name}`;
  }

  if (file.size === 0) {
    return `${file.name} is empty`;
  }

  return null;
}

function hasProcessingSources(sources: SourceListItem[]) {
  return sources.some(
    (source) => source.status === "pending" || source.status === "processing",
  );
}

export function useSources() {
  const { pushToast } = useToast();
  const [sources, setSources] = useState<SourceListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [deletingSourceId, setDeletingSourceId] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);

  const refreshSources = useCallback(async () => {
    const nextSources = await getSources();
    setSources(nextSources);
    return nextSources;
  }, []);
  const shouldPoll = hasProcessingSources(sources);

  useEffect(() => {
    let active = true;

    void (async () => {
      try {
        const nextSources = await getSources();
        if (active) {
          setSources(nextSources);
        }
      } catch (error) {
        if (active) {
          pushToast({
            message:
              error instanceof Error ? error.message : "Failed to load sources",
            tone: "error",
          });
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    })();

    return () => {
      active = false;
    };
  }, [pushToast]);

  useEffect(() => {
    if (!shouldPoll) {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return undefined;
    }

    if (intervalRef.current !== null) {
      return undefined;
    }

    intervalRef.current = window.setInterval(() => {
      void refreshSources().catch(() => {
        pushToast({
          message: "Failed to refresh source statuses",
          tone: "error",
        });
      });
    }, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [pushToast, refreshSources, shouldPoll]);

  const uploadFiles = useCallback(
    async (files: File[]) => {
      const validFiles: File[] = [];

      for (const file of files) {
        const validationError = validateSourceFile(file);
        if (validationError) {
          pushToast({ message: validationError, tone: "error" });
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
            }),
          ),
        );

        for (const [index, result] of results.entries()) {
          if (result.status === "fulfilled") {
            pushToast({
              message: `${validFiles[index]?.name ?? "File"} queued for ingestion`,
              tone: "success",
            });
            continue;
          }

          pushToast({
            message:
              result.reason instanceof Error
                ? result.reason.message
                : `Failed to upload ${validFiles[index]?.name ?? "file"}`,
            tone: "error",
          });
        }

        await refreshSources();
      } finally {
        setIsUploading(false);
      }
    },
    [pushToast, refreshSources],
  );

  const removeSource = useCallback(
    async (source: SourceListItem) => {
      setDeletingSourceId(source.id);
      try {
        const response = await deleteSource(source.id);
        if (response.warnings.length > 0) {
          for (const warning of response.warnings) {
            pushToast({ message: warning, tone: "warning" });
          }
        } else {
          pushToast({
            message: `${source.title} deleted`,
            tone: "success",
          });
        }

        await refreshSources();
      } catch (error) {
        pushToast({
          message:
            error instanceof Error ? error.message : "Failed to delete source",
          tone: "error",
        });
      } finally {
        setDeletingSourceId(null);
      }
    },
    [pushToast, refreshSources],
  );

  return {
    deletingSourceId,
    isLoading,
    isUploading,
    refreshSources,
    removeSource,
    sources,
    uploadFiles,
  };
}
