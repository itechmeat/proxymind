import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { appConfig } from "@/lib/config";
import "@/lib/i18n";
import "./index.css";
import App from "./App.tsx";

async function enableMocking() {
  if (import.meta.env.VITE_MOCK_MODE !== "true") {
    return;
  }

  const { worker } = await import("@/mocks/browser");
  await worker.start({ onUnhandledRequest: "warn" });
}

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element not found");
}

document.documentElement.lang = appConfig.language;
document.title = appConfig.twinName;

enableMocking().then(() => {
  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
