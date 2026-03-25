import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ToastItem } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

const toneStyles = {
  error: {
    icon: CircleAlert,
    className: "border-rose-200 bg-rose-50 text-rose-900",
  },
  info: {
    icon: Info,
    className: "border-sky-200 bg-sky-50 text-sky-900",
  },
  success: {
    icon: CircleCheck,
    className: "border-emerald-200 bg-emerald-50 text-emerald-900",
  },
  warning: {
    icon: TriangleAlert,
    className: "border-amber-200 bg-amber-50 text-amber-900",
  },
} as const;

export function ToastViewport({
  dismissToast,
  toasts,
}: {
  dismissToast: (id: string) => void;
  toasts: ToastItem[];
}) {
  return (
    <div className="pointer-events-none fixed top-5 right-5 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-3">
      {toasts.map((toast) => {
        const tone = toneStyles[toast.tone];
        const Icon = tone.icon;

        return (
          <div
            className={cn(
              "pointer-events-auto flex items-start gap-3 rounded-2xl border px-4 py-3 shadow-lg shadow-stone-900/10 backdrop-blur-sm",
              tone.className,
            )}
            key={toast.id}
            role="status"
          >
            <Icon className="mt-0.5 size-4 shrink-0" />
            <p className="m-0 flex-1 text-sm leading-6">{toast.message}</p>
            <Button
              aria-label="Dismiss notification"
              className="-mr-2"
              onClick={() => {
                dismissToast(toast.id);
              }}
              size="icon-xs"
              type="button"
              variant="ghost"
            >
              <X className="size-3.5" />
            </Button>
          </div>
        );
      })}
    </div>
  );
}
