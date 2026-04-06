import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { ProtectedRoute, PublicAuthRoute } from "@/components/ProtectedRoute";
import { useAuth } from "@/hooks/useAuth";
import { AuthProvider } from "@/hooks/useUserAuth";
import { appConfig } from "@/lib/config";
import {
  AdminPage,
  CatalogTab,
  SnapshotsTab,
  SourcesTab,
} from "@/pages/AdminPage";
import { AdminSignInPage } from "@/pages/AdminSignInPage/AdminSignInPage";
import {
  AuthIndexRedirect,
  ForgotPasswordPage,
  RegisterPage,
  ResetPasswordPage,
  SignInPage,
  VerifyEmailPage,
} from "@/pages/AuthPage";
import { ChatPage } from "@/pages/ChatPage";

function AdminModeGuard() {
  if (!appConfig.adminMode) {
    return <Navigate replace to="/" />;
  }

  return <Outlet />;
}

function AdminRouteGuard() {
  const { isAuthenticated } = useAuth();

  if (!appConfig.adminMode) {
    return <Navigate replace to="/" />;
  }

  if (!isAuthenticated) {
    return <Navigate replace to="/admin/sign-in" />;
  }

  return <Outlet />;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<PublicAuthRoute />}>
            <Route path="/auth">
              <Route element={<AuthIndexRedirect />} index />
              <Route element={<SignInPage />} path="sign-in" />
              <Route element={<RegisterPage />} path="register" />
              <Route element={<ForgotPasswordPage />} path="forgot-password" />
              <Route element={<ResetPasswordPage />} path="reset-password" />
              <Route element={<VerifyEmailPage />} path="verify-email" />
            </Route>
          </Route>

          <Route element={<ProtectedRoute />}>
            <Route element={<ChatPage />} path="/" />
          </Route>

          <Route element={<AdminModeGuard />}>
            <Route element={<AdminSignInPage />} path="/admin/sign-in" />
            <Route element={<AdminRouteGuard />}>
              <Route element={<AdminPage />} path="/admin">
                <Route element={<Navigate replace to="sources" />} index />
                <Route element={<SourcesTab />} path="sources" />
                <Route element={<SnapshotsTab />} path="snapshots" />
                <Route element={<CatalogTab />} path="catalog" />
              </Route>
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
