import { HttpResponse, http } from "msw";

import {
  MOCK_SESSION_ID,
  MOCK_SNAPSHOT_ID,
  mockSessionWithMessages,
} from "@/mocks/data/fixtures";

let sessionCounter = 0;

export function resetSessionHandlersState() {
  sessionCounter = 0;
}

export const sessionHandlers = [
  http.post("*/api/chat/sessions", () => {
    sessionCounter += 1;
    return HttpResponse.json({
      id: sessionCounter === 1 ? MOCK_SESSION_ID : crypto.randomUUID(),
      snapshot_id: MOCK_SNAPSHOT_ID,
      status: "active",
      channel: "web",
      message_count: 0,
      created_at: new Date().toISOString(),
    });
  }),

  http.get("*/api/chat/sessions/:sessionId", ({ params }) => {
    if (params.sessionId === MOCK_SESSION_ID) {
      return HttpResponse.json(mockSessionWithMessages);
    }

    return HttpResponse.json({
      id: params.sessionId,
      snapshot_id: MOCK_SNAPSHOT_ID,
      status: "active",
      channel: "web",
      message_count: 0,
      created_at: new Date().toISOString(),
      messages: [],
    });
  }),
];
