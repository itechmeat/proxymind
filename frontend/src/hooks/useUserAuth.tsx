import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  forgotPassword,
  getMe,
  refreshUserToken,
  registerUser,
  resetPassword,
  signInUser,
  signOutUser,
  verifyEmail,
} from "@/lib/auth-api";
import { clearStoredSessionId } from "@/lib/session-storage";
import type { AuthUser, RegisterRequest, SignInRequest } from "@/types/auth";

interface AccessTokenOptions {
  forceRefresh?: boolean;
}

interface UserAuthContextValue {
  accessToken: string | null;
  getAccessToken: (options?: AccessTokenOptions) => Promise<string | null>;
  isAuthenticated: boolean;
  isLoading: boolean;
  register: (payload: RegisterRequest) => Promise<string>;
  resetPassword: (token: string, newPassword: string) => Promise<string>;
  signIn: (payload: SignInRequest) => Promise<void>;
  signOut: () => Promise<void>;
  user: AuthUser | null;
  verifyEmail: (token: string) => Promise<string>;
  forgotPassword: (email: string) => Promise<string>;
}

const UserAuthContext = createContext<UserAuthContextValue | null>(null);

async function resolveUser(accessToken: string) {
  return await getMe(accessToken);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);
  const accessTokenRef = useRef<string | null>(null);
  const authFlowVersionRef = useRef(0);
  const refreshPromiseRef = useRef<Promise<string | null> | null>(null);

  const invalidatePendingAuthFlows = useCallback(() => {
    authFlowVersionRef.current += 1;
    return authFlowVersionRef.current;
  }, []);

  const applyAuthenticatedState = useCallback(
    async (token: string, version: number) => {
      const nextUser = await resolveUser(token);
      if (version !== authFlowVersionRef.current) {
        return false;
      }

      accessTokenRef.current = token;
      setAccessToken(token);
      setUser(nextUser);
      setIsLoading(false);
      return true;
    },
    [],
  );

  const applyUnauthenticatedState = useCallback(() => {
    accessTokenRef.current = null;
    setAccessToken(null);
    setUser(null);
    setIsLoading(false);
  }, []);

  const refreshSession = useCallback(async () => {
    if (refreshPromiseRef.current) {
      return await refreshPromiseRef.current;
    }

    refreshPromiseRef.current = (async () => {
      const version = authFlowVersionRef.current;

      try {
        const tokenResponse = await refreshUserToken();
        const applied = await applyAuthenticatedState(
          tokenResponse.access_token,
          version,
        );
        return applied ? tokenResponse.access_token : accessTokenRef.current;
      } catch {
        if (version === authFlowVersionRef.current) {
          applyUnauthenticatedState();
        }
        return null;
      } finally {
        refreshPromiseRef.current = null;
      }
    })();

    return await refreshPromiseRef.current;
  }, [applyAuthenticatedState, applyUnauthenticatedState]);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  const getAccessToken = useCallback(
    async (options?: AccessTokenOptions) => {
      if (!options?.forceRefresh && accessTokenRef.current) {
        return accessTokenRef.current;
      }

      return await refreshSession();
    },
    [refreshSession],
  );

  const signIn = useCallback(
    async (payload: SignInRequest) => {
      const version = invalidatePendingAuthFlows();
      clearStoredSessionId();
      const tokenResponse = await signInUser(payload);
      await applyAuthenticatedState(tokenResponse.access_token, version);
    },
    [applyAuthenticatedState, invalidatePendingAuthFlows],
  );

  const signOut = useCallback(async () => {
    invalidatePendingAuthFlows();
    refreshPromiseRef.current = null;

    try {
      await signOutUser();
    } finally {
      clearStoredSessionId();
      applyUnauthenticatedState();
    }
  }, [applyUnauthenticatedState, invalidatePendingAuthFlows]);

  const register = useCallback(async (payload: RegisterRequest) => {
    const response = await registerUser(payload);
    return response.detail;
  }, []);

  const requestForgotPassword = useCallback(async (email: string) => {
    const response = await forgotPassword(email);
    return response.detail;
  }, []);

  const requestResetPassword = useCallback(
    async (token: string, newPassword: string) => {
      const response = await resetPassword({
        token,
        new_password: newPassword,
      });
      return response.detail;
    },
    [],
  );

  const requestVerifyEmail = useCallback(async (token: string) => {
    const response = await verifyEmail(token);
    return response.detail;
  }, []);

  return (
    <UserAuthContext.Provider
      value={{
        accessToken,
        getAccessToken,
        isAuthenticated: Boolean(accessToken),
        isLoading,
        register,
        resetPassword: requestResetPassword,
        signIn,
        signOut,
        user,
        verifyEmail: requestVerifyEmail,
        forgotPassword: requestForgotPassword,
      }}
    >
      {children}
    </UserAuthContext.Provider>
  );
}

export function useUserAuth() {
  const context = useContext(UserAuthContext);
  if (!context) {
    throw new Error("useUserAuth must be used within AuthProvider");
  }
  return context;
}
