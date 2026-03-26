import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium capitalize tracking-[0.08em]",
  {
    variants: {
      variant: {
        success:
          "border-emerald-300/70 bg-emerald-50 text-emerald-800 shadow-sm shadow-emerald-100",
        warning:
          "border-amber-300/70 bg-amber-50 text-amber-800 shadow-sm shadow-amber-100",
        error:
          "border-rose-300/70 bg-rose-50 text-rose-800 shadow-sm shadow-rose-100",
        info: "border-sky-300/70 bg-sky-50 text-sky-800 shadow-sm shadow-sky-100",
        muted: "border-stone-300/70 bg-stone-100 text-stone-700 shadow-sm",
      },
    },
    defaultVariants: {
      variant: "muted",
    },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span className={cn(badgeVariants({ className, variant }))} {...props} />
  );
}
