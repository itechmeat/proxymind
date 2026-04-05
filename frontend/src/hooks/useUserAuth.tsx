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
  const refreshPromiseRef = useRef<Promise<string | null> | null>(null);

  const applyAuthenticatedState = useCallback(async (token: string) => {
    const nextUser = await resolveUser(token);
    setAccessToken(token);
    setUser(nextUser);
    setIsLoading(false);
  }, []);

  const applyUnauthenticatedState = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setIsLoading(false);
  }, []);

  const refreshSession = useCallback(async () => {
    if (refreshPromiseRef.current) {
      return await refreshPromiseRef.current;
    }

    refreshPromiseRef.current = (async () => {
      try {
        const tokenResponse = await refreshUserToken();
        await applyAuthenticatedState(tokenResponse.access_token);
        return tokenResponse.access_token;
      } catch {
        applyUnauthenticatedState();
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
      if (!options?.forceRefresh && accessToken) {
        return accessToken;
      }

      return await refreshSession();
    },
    [accessToken, refreshSession],
  );

  const signIn = useCallback(
    async (payload: SignInRequest) => {
      clearStoredSessionId();
      const tokenResponse = await signInUser(payload);
      await applyAuthenticatedState(tokenResponse.access_token);
    },
    [applyAuthenticatedState],
  );

  const signOut = useCallback(async () => {
    try {
      await signOutUser();
    } finally {
      clearStoredSessionId();
      applyUnauthenticatedState();
    }
  }, [applyUnauthenticatedState]);

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
