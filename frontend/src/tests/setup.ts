import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import "@/lib/i18n";
import { afterEach, beforeEach } from "vitest";
import { resetMockHandlersState } from "@/mocks/handlers";

beforeEach(() => {
  resetMockHandlersState();
});

afterEach(() => {
  cleanup();
});
