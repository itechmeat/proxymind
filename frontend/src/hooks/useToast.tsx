import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ToastViewport } from "@/components/ui/toast";

export type ToastTone = "success" | "error" | "warning" | "info";

export interface ToastItem {
  id: string;
  message: string;
  tone: ToastTone;
}

interface ToastContextValue {
  dismissToast: (id: string) => void;
  pushToast: (toast: Omit<ToastItem, "id">) => void;
  toasts: ToastItem[];
}

const ToastContext = createContext<ToastContextValue | null>(null);
const TOAST_TTL_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timerIdsRef = useRef(new Map<string, number>());

  const dismissToast = useCallback((id: string) => {
    const timerId = timerIdsRef.current.get(id);
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
      timerIdsRef.current.delete(id);
    }

    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const pushToast = useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = crypto.randomUUID();
      const timerId = window.setTimeout(() => {
        dismissToast(id);
      }, TOAST_TTL_MS);

      timerIdsRef.current.set(id, timerId);
      setToasts((current) => [...current, { ...toast, id }]);
    },
    [dismissToast],
  );

  useEffect(() => {
    return () => {
      for (const timer of timerIdsRef.current.values()) {
        window.clearTimeout(timer);
      }
      timerIdsRef.current.clear();
    };
  }, []);

  const value = useMemo(
    () => ({ dismissToast, pushToast, toasts }),
    [dismissToast, pushToast, toasts],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport dismissToast={dismissToast} toasts={toasts} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }

  return context;
}
