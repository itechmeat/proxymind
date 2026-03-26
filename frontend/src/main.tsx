import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { appConfig } from "@/lib/config";
import "@/lib/i18n";
import "./index.css";
import App from "./App.tsx";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element not found");
}

document.documentElement.lang = appConfig.language;
document.title = appConfig.twinName;

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
