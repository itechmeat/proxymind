import { authHandlers } from "./auth";
import { catalogHandlers } from "./catalog";
import { messageHandlers } from "./messages";
import { sessionHandlers } from "./session";
import { snapshotHandlers } from "./snapshots";
import { sourceHandlers } from "./sources";
import { twinHandlers } from "./twin";

export const handlers = [
  ...authHandlers,
  ...sessionHandlers,
  ...messageHandlers,
  ...twinHandlers,
  ...snapshotHandlers,
  ...catalogHandlers,
  ...sourceHandlers,
];
