import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "proxymind_admin_key";

function isMockMode() {
  return import.meta.env.VITE_MOCK_MODE === "true";
}

function getStorage(): Storage {
  return isMockMode() ? sessionStorage : localStorage;
}

function getSnapshot(): string | null {
  const storage = getStorage();
  if (typeof storage?.getItem !== "function") {
    return null;
  }

  return storage.getItem(STORAGE_KEY);
}

function getServerSnapshot(): string | null {
  return null;
}

const listeners = new Set<() => void>();

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

function notify() {
  for (const listener of listeners) {
    listener();
  }
}

export function useAuth() {
  const adminKey = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const login = useCallback((key: string) => {
    const storage = getStorage();
    if (typeof storage?.setItem === "function") {
      storage.setItem(STORAGE_KEY, key);
    }
    notify();
  }, []);

  const logout = useCallback(() => {
    const storage = getStorage();
    if (typeof storage?.removeItem === "function") {
      storage.removeItem(STORAGE_KEY);
    }
    notify();
  }, []);

  return {
    adminKey,
    isAuthenticated: adminKey !== null && adminKey.length > 0,
    login,
    logout,
  };
}

export function getAdminKey(): string | null {
  const storage = getStorage();
  if (typeof storage?.getItem !== "function") {
    return null;
  }

  return storage.getItem(STORAGE_KEY);
}
