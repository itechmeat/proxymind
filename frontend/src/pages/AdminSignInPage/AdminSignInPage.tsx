import { useState } from "react";
import { Navigate, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { validateAdminKey } from "@/lib/admin-api";
import { appConfig } from "@/lib/config";
import { strings } from "@/lib/strings";

const MOCK_ADMIN_KEY = "mock-admin-key";
const inputClassName =
  "mt-2 w-full rounded-2xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-950 shadow-sm outline-none transition focus:border-amber-400 focus:ring-4 focus:ring-amber-100";

export function AdminSignInPage() {
  const isMock = import.meta.env.VITE_MOCK_MODE === "true";
  const navigate = useNavigate();
  const { isAuthenticated, login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [value, setValue] = useState(isMock ? MOCK_ADMIN_KEY : "");

  if (!appConfig.adminMode) {
    return <Navigate replace to="/" />;
  }

  if (isAuthenticated) {
    return <Navigate replace to="/admin/sources" />;
  }

  return (
    <main className="min-h-dvh bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.18),_transparent_28%),radial-gradient(circle_at_bottom_right,_rgba(14,165,233,0.14),_transparent_30%),linear-gradient(180deg,_rgba(255,251,235,0.98)_0%,_rgba(248,250,252,1)_100%)]">
      <div className="mx-auto flex min-h-dvh max-w-5xl flex-col justify-center gap-10 px-6 py-10 lg:flex-row lg:items-center lg:gap-16">
        <section className="max-w-xl">
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-amber-700/80">
            {strings.adminEyebrow}
          </p>
          <h1 className="mt-4 font-serif text-5xl leading-none tracking-[-0.06em] text-stone-950 sm:text-6xl">
            {strings.adminSignInTitle}
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-stone-600">
            {strings.adminSignInDescription}
          </p>
        </section>

        <section className="w-full max-w-md rounded-[2rem] border border-white/75 bg-white/82 p-8 shadow-2xl shadow-stone-900/5 backdrop-blur-sm">
          <form
            className="space-y-5"
            onSubmit={(event) => {
              event.preventDefault();
              const trimmed = value.trim();
              if (!trimmed) {
                setError(strings.adminKeyRequired);
                return;
              }

              setError(null);
              setIsSubmitting(true);

              void (async () => {
                try {
                  await validateAdminKey(trimmed);
                  login(trimmed);
                  navigate("/admin/sources", { replace: true });
                } catch (submitError) {
                  setError(
                    submitError instanceof Error
                      ? submitError.message
                      : strings.authRequestFailed,
                  );
                } finally {
                  setIsSubmitting(false);
                }
              })();
            }}
          >
            <div>
              <label
                className="text-sm font-medium text-stone-700"
                htmlFor="admin-sign-in-key"
              >
                {strings.adminKeyLabel}
              </label>
              <input
                autoComplete="off"
                className={inputClassName}
                id="admin-sign-in-key"
                onChange={(event) => {
                  setValue(event.currentTarget.value);
                  setError(null);
                }}
                placeholder={strings.adminKeyPlaceholder}
                required
                type="password"
                value={value}
              />
            </div>

            {error ? (
              <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                {error}
              </div>
            ) : null}

            <Button className="w-full" disabled={isSubmitting} type="submit">
              {isSubmitting ? strings.signingIn : strings.signInAction}
            </Button>
          </form>
        </section>
      </div>
    </main>
  );
}
