import { NavLink, type NavLinkRenderProps } from "react-router";

import { cn } from "@/lib/utils";

export function TabsList({ className, ...props }: React.ComponentProps<"nav">) {
  return (
    <nav
      className={cn(
        "flex w-full gap-2 rounded-2xl border border-white/70 bg-white/70 p-2 shadow-sm shadow-stone-900/5 backdrop-blur-sm",
        className,
      )}
      {...props}
    />
  );
}

function tabLinkClassName({ isActive }: NavLinkRenderProps) {
  return cn(
    "flex-1 rounded-xl px-4 py-3 text-center text-sm font-medium transition-colors",
    isActive
      ? "bg-stone-950 text-white shadow-md shadow-stone-900/20"
      : "text-stone-600 hover:bg-stone-100/80 hover:text-stone-950",
  );
}

export function TabsLink({
  children,
  to,
}: {
  children: React.ReactNode;
  to: string;
}) {
  return (
    <NavLink className={tabLinkClassName} end to={to}>
      {children}
    </NavLink>
  );
}
