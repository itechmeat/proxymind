import { HttpResponse, http } from "msw";

import { mockTwinProfile } from "@/mocks/data/fixtures";

let currentProfile = { ...mockTwinProfile };

export const twinHandlers = [
  http.get("*/api/chat/twin", () => {
    return HttpResponse.json(currentProfile);
  }),

  http.get("*/api/chat/twin/avatar", () => {
    return new HttpResponse(null, { status: 404 });
  }),

  http.put("*/api/admin/agent/profile", async ({ request }) => {
    const body = (await request.json()) as { name?: string };
    if (body.name) {
      currentProfile = { ...currentProfile, name: body.name };
    }
    return HttpResponse.json(currentProfile);
  }),

  http.post("*/api/admin/agent/avatar", () => {
    currentProfile = { ...currentProfile, has_avatar: true };
    return HttpResponse.json({ has_avatar: true });
  }),

  http.delete("*/api/admin/agent/avatar", () => {
    currentProfile = { ...currentProfile, has_avatar: false };
    return HttpResponse.json({ has_avatar: false });
  }),
];
