import { authHandlers, resetAuthMockState } from "./auth";
import { catalogHandlers, resetCatalogHandlersState } from "./catalog";
import { messageHandlers, resetMessageHandlersState } from "./messages";
import { resetSessionHandlersState, sessionHandlers } from "./session";
import { resetSnapshotHandlersState, snapshotHandlers } from "./snapshots";
import { resetSourceHandlersState, sourceHandlers } from "./sources";
import { resetTwinHandlersState, twinHandlers } from "./twin";

export const handlers = [
  ...authHandlers,
  ...sessionHandlers,
  ...messageHandlers,
  ...twinHandlers,
  ...snapshotHandlers,
  ...catalogHandlers,
  ...sourceHandlers,
];

export function resetMockHandlersState() {
  resetAuthMockState();
  resetSessionHandlersState();
  resetMessageHandlersState();
  resetTwinHandlersState();
  resetSnapshotHandlersState();
  resetCatalogHandlersState();
  resetSourceHandlersState();
}
