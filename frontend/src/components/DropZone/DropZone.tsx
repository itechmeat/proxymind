import { CloudUpload } from "lucide-react";
import { useRef, useState } from "react";

import { useAppTranslation } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface DropZoneProps {
  disabled?: boolean;
  isUploading?: boolean;
  onFiles: (files: File[]) => void;
}

export function DropZone({
  disabled = false,
  isUploading = false,
  onFiles,
}: DropZoneProps) {
  const { t } = useAppTranslation();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  return (
    <button
      disabled={disabled}
      className={cn(
        "group rounded-[1.75rem] border border-dashed bg-white/80 p-6 shadow-sm shadow-stone-900/5 transition-colors sm:p-8",
        isDragging
          ? "border-sky-400 bg-sky-50/80"
          : "border-stone-300/80 hover:border-stone-500/60",
        disabled && "cursor-not-allowed opacity-70",
      )}
      data-dragging={isDragging ? "true" : "false"}
      onClick={() => {
        if (disabled) {
          return;
        }
        inputRef.current?.click();
      }}
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) {
          setIsDragging(true);
        }
      }}
      onDragLeave={(event) => {
        event.preventDefault();
        const nextTarget = event.relatedTarget;
        if (
          !nextTarget ||
          !(nextTarget instanceof Node) ||
          !event.currentTarget.contains(nextTarget)
        ) {
          setIsDragging(false);
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        if (disabled) {
          return;
        }
        onFiles(Array.from(event.dataTransfer.files));
      }}
      type="button"
    >
      <input
        className="hidden"
        disabled={disabled}
        multiple
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
        ref={inputRef}
        type="file"
      />

      <div className="flex flex-col items-center justify-center gap-4 text-center">
        <div className="flex size-14 items-center justify-center rounded-2xl bg-stone-950 text-white shadow-lg shadow-stone-900/10">
          <CloudUpload className="size-6" />
        </div>
        <div className="space-y-1">
          <h2 className="m-0 text-lg font-semibold text-stone-950">
            {t("admin.source.dropZoneTitle")}
          </h2>
          <p className="m-0 text-sm leading-6 text-stone-600">
            {t("admin.source.dropZoneDescription")}
          </p>
          <p className="m-0 text-xs uppercase tracking-[0.14em] text-stone-400">
            {t("admin.source.dropZoneFormats")}
          </p>
          {isUploading ? (
            <p className="m-0 text-sm font-medium text-sky-700">
              {t("admin.source.uploading")}
            </p>
          ) : null}
        </div>
      </div>
    </button>
  );
}
