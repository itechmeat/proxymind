import { Navigate, Outlet, useLocation } from "react-router";

import { useUserAuth } from "@/hooks/useUserAuth";
import { strings } from "@/lib/strings";

function RouteLoadingState() {
  return (
    <main className="min-h-dvh bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.14),_transparent_28%),linear-gradient(180deg,_rgba(255,251,235,0.96)_0%,_rgba(248,250,252,1)_100%)]">
      <div className="mx-auto flex min-h-dvh max-w-4xl items-center justify-center px-6 py-12">
        <div
          aria-live="polite"
          className="w-full max-w-md rounded-[2rem] border border-white/70 bg-white/80 px-8 py-10 text-center shadow-xl shadow-stone-900/5 backdrop-blur-sm"
          role="status"
        >
          <p className="text-xs font-medium uppercase tracking-[0.22em] text-amber-700/80">
            ProxyMind
          </p>
          <h1 className="mt-3 font-serif text-3xl tracking-[-0.04em] text-stone-950">
            {strings.authLoading}
          </h1>
          <p className="mt-3 text-sm leading-6 text-stone-600">
            {strings.authLoadingDescription}
          </p>
        </div>
      </div>
    </main>
  );
}

export function ProtectedRoute() {
  const location = useLocation();
  const { isAuthenticated, isLoading } = useUserAuth();

  if (isLoading) {
    return <RouteLoadingState />;
  }

  if (!isAuthenticated) {
    return (
      <Navigate
        replace
        state={{ from: `${location.pathname}${location.search}` }}
        to="/auth/sign-in"
      />
    );
  }

  return <Outlet />;
}

export function PublicAuthRoute() {
  const { isAuthenticated, isLoading } = useUserAuth();

  if (isLoading) {
    return <RouteLoadingState />;
  }

  if (isAuthenticated) {
    return <Navigate replace to="/" />;
  }

  return <Outlet />;
}
