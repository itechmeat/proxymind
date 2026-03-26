import { startTransition, useCallback, useEffect, useState } from "react";

import { ApiError, createSession, getSession } from "@/lib/api";
import { toUIMessages } from "@/lib/message-adapter";
import { strings } from "@/lib/strings";
import type { ChatMessage } from "@/types/chat";

export const SESSION_STORAGE_KEY = "proxymind_session_id";

interface SessionState {
  error: string | null;
  initialMessages: ChatMessage[];
  isLoading: boolean;
  sessionId: string | null;
  snapshotId: string | null;
}

const initialState: SessionState = {
  error: null,
  initialMessages: [],
  isLoading: true,
  sessionId: null,
  snapshotId: null,
};

function getErrorDetail(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return strings.sessionUnavailable;
}

function readStoredSessionId() {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredSessionId(sessionId: string) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  } catch {
    // Ignore storage failures and keep the active in-memory session.
  }
}

export function useSession() {
  const [state, setState] = useState<SessionState>(initialState);

  const applyState = useCallback((nextState: SessionState) => {
    startTransition(() => {
      setState(nextState);
    });
  }, []);

  const createAndStoreSession = useCallback(async () => {
    const session = await createSession();
    writeStoredSessionId(session.id);

    applyState({
      error: null,
      initialMessages: [],
      isLoading: false,
      sessionId: session.id,
      snapshotId: session.snapshot_id,
    });

    return session;
  }, [applyState]);

  const restoreOrCreateSession = useCallback(async () => {
    const storedSessionId = readStoredSessionId();

    if (!storedSessionId) {
      await createAndStoreSession();
      return;
    }

    try {
      const session = await getSession(storedSessionId);
      writeStoredSessionId(session.id);

      applyState({
        error: null,
        initialMessages: toUIMessages(session.messages),
        isLoading: false,
        sessionId: session.id,
        snapshotId: session.snapshot_id,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        await createAndStoreSession();
        return;
      }

      throw error;
    }
  }, [applyState, createAndStoreSession]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        await restoreOrCreateSession();
      } catch (error) {
        if (cancelled) {
          return;
        }

        applyState({
          error: getErrorDetail(error),
          initialMessages: [],
          isLoading: false,
          sessionId: null,
          snapshotId: null,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [applyState, restoreOrCreateSession]);

  const createNewSession = useCallback(async () => {
    startTransition(() => {
      setState({
        ...initialState,
        error: null,
        isLoading: true,
      });
    });

    try {
      await createAndStoreSession();
    } catch (error) {
      applyState({
        error: getErrorDetail(error),
        initialMessages: [],
        isLoading: false,
        sessionId: null,
        snapshotId: null,
      });
    }
  }, [applyState, createAndStoreSession]);

  return {
    createNewSession,
    error: state.error,
    initialMessages: state.initialMessages,
    isLoading: state.isLoading,
    sessionId: state.sessionId,
    snapshotId: state.snapshotId,
  };
}
