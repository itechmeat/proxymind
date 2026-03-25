import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { TabsLink, TabsList } from "@/components/ui/tabs";
import { ToastProvider } from "@/hooks/useToast";
import { getTwinProfile } from "@/lib/api";
import { appConfig } from "@/lib/config";
import { getInitials } from "@/lib/identity";
import { strings } from "@/lib/strings";
import type { TwinProfile } from "@/types/chat";

interface DisplayTwinProfile {
  avatarUrl?: string;
  name: string;
}

function resolveFallbackProfile(): DisplayTwinProfile {
  return {
    avatarUrl: appConfig.twinAvatarUrl || undefined,
    name: appConfig.twinName || strings.appTitle,
  };
}

function resolveApiProfile(
  profile: TwinProfile | null,
): DisplayTwinProfile | null {
  if (!profile?.name?.trim()) {
    return null;
  }

  return {
    avatarUrl: profile.has_avatar ? "/api/chat/twin/avatar" : undefined,
    name: profile.name.trim(),
  };
}

export function AdminPage() {
  const [profile, setProfile] = useState<DisplayTwinProfile>(
    resolveFallbackProfile,
  );

  useEffect(() => {
    let active = true;

    void (async () => {
      try {
        const nextProfile = resolveApiProfile(await getTwinProfile());
        if (active && nextProfile) {
          setProfile(nextProfile);
        }
      } catch {
        if (active) {
          setProfile(resolveFallbackProfile());
        }
      }
    })();

    return () => {
      active = false;
    };
  }, []);

  const initials = getInitials(profile.name);

  return (
    <ToastProvider>
      <main className="min-h-dvh bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.12),_transparent_28%),linear-gradient(180deg,_rgba(255,251,235,0.95)_0%,_rgba(248,250,252,1)_100%)]">
        <div className="mx-auto flex min-h-dvh w-full max-w-6xl flex-col px-4 py-5 sm:px-6 lg:px-8">
          <header className="rounded-[2rem] border border-white/70 bg-white/75 px-5 py-5 shadow-lg shadow-stone-900/5 backdrop-blur-sm sm:px-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <Button asChild type="button" variant="outline">
                  <Link to="/">
                    <ArrowLeft className="size-4" />
                    Chat
                  </Link>
                </Button>

                <div>
                  <p className="m-0 text-xs uppercase tracking-[0.16em] text-stone-500">
                    ProxyMind Control Surface
                  </p>
                  <h1 className="m-0 mt-1 font-serif text-3xl font-semibold tracking-[-0.03em] text-stone-950">
                    ProxyMind Admin
                  </h1>
                </div>
              </div>

              <div className="flex items-center gap-3 rounded-full border border-stone-200 bg-stone-50/80 px-4 py-2">
                <Avatar size="lg">
                  {profile.avatarUrl ? (
                    <img
                      alt={profile.name}
                      className="size-full object-cover"
                      src={profile.avatarUrl}
                    />
                  ) : (
                    <AvatarFallback>{initials}</AvatarFallback>
                  )}
                </Avatar>
                <div>
                  <p className="m-0 text-xs uppercase tracking-[0.16em] text-stone-500">
                    Twin identity
                  </p>
                  <p className="m-0 text-sm font-medium text-stone-900">
                    {profile.name}
                  </p>
                </div>
              </div>
            </div>
          </header>

          <div className="mt-4">
            <TabsList aria-label="Admin sections">
              <TabsLink to="/admin/sources">Sources</TabsLink>
              <TabsLink to="/admin/snapshots">Snapshots</TabsLink>
            </TabsList>
          </div>

          <div className="mt-4 flex-1 overflow-hidden rounded-[2rem] border border-white/70 bg-white/55 p-4 shadow-sm shadow-stone-900/5 backdrop-blur-sm sm:p-5">
            <div className="h-full overflow-auto">
              <Outlet />
            </div>
          </div>
        </div>
      </main>
    </ToastProvider>
  );
}
