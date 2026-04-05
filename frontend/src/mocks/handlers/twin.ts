import { HttpResponse, http } from "msw";

import { mockTwinProfile } from "@/mocks/data/fixtures";

function buildCurrentProfile() {
  return { ...mockTwinProfile };
}

let currentProfile = buildCurrentProfile();

export function resetTwinHandlersState() {
  currentProfile = buildCurrentProfile();
}

export const twinHandlers = [
  http.get("*/api/chat/twin", () => {
    return HttpResponse.json(currentProfile);
  }),

  http.get("*/api/chat/twin/avatar", () => {
    if (!currentProfile.has_avatar) {
      return new HttpResponse(null, { status: 404 });
    }

    return new HttpResponse(null, {
      status: 200,
      headers: {
        "Content-Type": "image/png",
      },
    });
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
