import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { appConfig } from "@/lib/config";
import {
  AdminPage,
  CatalogTab,
  SnapshotsTab,
  SourcesTab,
} from "@/pages/AdminPage";
import { ChatPage } from "@/pages/ChatPage";

function AdminRouteGuard() {
  if (!appConfig.adminMode) {
    return <Navigate replace to="/" />;
  }

  return <Outlet />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<ChatPage />} path="/" />
        <Route element={<AdminRouteGuard />} path="/admin">
          <Route element={<AdminPage />}>
            <Route element={<Navigate replace to="sources" />} index />
            <Route element={<SourcesTab />} path="sources" />
            <Route element={<SnapshotsTab />} path="snapshots" />
            <Route element={<CatalogTab />} path="catalog" />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
