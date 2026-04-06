import { startTransition, useCallback, useEffect, useState } from "react";
import { useUserAuth } from "@/hooks/useUserAuth";
import { ApiError, createSession, getSession } from "@/lib/api";
import { toUIMessages } from "@/lib/message-adapter";
import {
  clearStoredSessionId,
  readStoredSessionId,
  SESSION_STORAGE_KEY,
  writeStoredSessionId,
} from "@/lib/session-storage";
import { strings } from "@/lib/strings";
import type { ChatMessage } from "@/types/chat";

export { SESSION_STORAGE_KEY };

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

export function useSession() {
  const {
    getAccessToken,
    isAuthenticated,
    isLoading: authIsLoading,
  } = useUserAuth();
  const [state, setState] = useState<SessionState>(initialState);

  const applyState = useCallback((nextState: SessionState) => {
    startTransition(() => {
      setState(nextState);
    });
  }, []);

  const createAndStoreSession = useCallback(async () => {
    const accessToken = await getAccessToken();
    if (!accessToken) {
      throw new Error(strings.authenticationRequired);
    }

    const session = await createSession(accessToken);
    writeStoredSessionId(session.id);

    applyState({
      error: null,
      initialMessages: [],
      isLoading: false,
      sessionId: session.id,
      snapshotId: session.snapshot_id,
    });

    return session;
  }, [applyState, getAccessToken]);

  const restoreOrCreateSession = useCallback(async () => {
    const storedSessionId = readStoredSessionId();

    if (!storedSessionId) {
      await createAndStoreSession();
      return;
    }

    try {
      const accessToken = await getAccessToken();
      if (!accessToken) {
        throw new Error(strings.authenticationRequired);
      }

      const session = await getSession(storedSessionId, accessToken);
      writeStoredSessionId(session.id);

      applyState({
        error: null,
        initialMessages: toUIMessages(session.messages),
        isLoading: false,
        sessionId: session.id,
        snapshotId: session.snapshot_id,
      });
    } catch (error) {
      if (
        error instanceof ApiError &&
        (error.status === 403 || error.status === 404)
      ) {
        await createAndStoreSession();
        return;
      }

      throw error;
    }
  }, [applyState, createAndStoreSession, getAccessToken]);

  useEffect(() => {
    let cancelled = false;

    if (authIsLoading) {
      return () => {
        cancelled = true;
      };
    }

    if (!isAuthenticated) {
      clearStoredSessionId();
      applyState({
        ...initialState,
        isLoading: false,
      });

      return () => {
        cancelled = true;
      };
    }

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
  }, [applyState, authIsLoading, isAuthenticated, restoreOrCreateSession]);

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
