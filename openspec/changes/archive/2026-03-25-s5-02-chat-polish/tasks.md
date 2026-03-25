**Story verification criteria (from docs/plan.md S5-02):** citation produces clickable link; collapse/expand block; avatar visible in chat header.

## 0. TODO Resolution

No `TODO(S5-02)` stubs found in the codebase (verified via `grep -rn "TODO(S5-02)" backend/ frontend/src/`). No resolution tasks needed.

## 1. Setup and Dependencies

- [x] 1.1 Read `docs/development.md` to internalize coding standards
- [x] 1.2 Install `lucide-react` and `rehype-raw` frontend dependencies (`bun add lucide-react rehype-raw`)
- [x] 1.3 Verify all dependency versions meet `docs/spec.md` minimums; run `bun run build` to confirm

## 2. Source Icon Mapping

- [x] 2.1 Write failing tests for `getSourceIcon()` in `src/tests/lib/source-icons.test.ts` (8 known types + unknown fallback)
- [x] 2.2 Implement `src/lib/source-icons.ts` — pure mapping from `source_type` to lucide icon + color
- [x] 2.3 Run tests and confirm all pass

## 3. Remark Citations Plugin

- [x] 3.1 Write failing tests for `remarkCitations` in `src/tests/lib/remark-citations.test.ts` (valid markers, multiple, out-of-range, no markers, empty citations) — tests MUST use `rehypeRaw` in the render helper
- [x] 3.2 Implement `src/lib/remark-citations.ts` — remark plugin that replaces `[source:N]` text with `html` mdast nodes (`<sup><button class="citation-ref" ...>`)
- [x] 3.3 Run tests and confirm all pass

## 4. CitationRef Component

- [x] 4.1 Create `src/components/CitationRef/` — superscript button component with click callback, CSS styling (indigo color)
- [x] 4.2 Create `src/components/CitationRef/index.ts` re-export
- [x] 4.3 Verify build succeeds

## 5. CitationsBlock Component

- [x] 5.1 Add `sourcesCount(n)` format function to `src/lib/strings.ts` (pluralization-neutral, default English, configurable per installation via strings module)
- [x] 5.2 Write failing tests for `CitationsBlock` in `src/tests/components/CitationsBlock.test.tsx` (empty, collapsed, expand, online link, offline text, image click, collapse back)
- [x] 5.3 Implement `src/components/CitationsBlock/` — collapsible sources list with type icons, click behavior per source type
- [x] 5.4 Run tests and confirm all pass

## 6. ImageLightbox Component

- [x] 6.1 Write failing tests for `ImageLightbox` in `src/tests/components/ImageLightbox.test.tsx` (render, close via X/Escape/backdrop, lazy loading: `<img>` element MUST NOT exist in DOM before lightbox is opened)
- [x] 6.2 Implement `src/components/ImageLightbox/` — modal overlay with image preview, close handlers, lazy `<img>` creation
- [x] 6.3 Run tests and confirm all pass

## 7. Integrate Citations into MessageBubble

- [x] 7.1 Write new failing tests in existing `src/tests/components/MessageBubble.test.tsx` using existing `createMessage` helper: citations block present/absent, not shown during streaming, scroll-to-highlight interaction (clicking superscript expands collapsed block and highlights the target source item)
- [x] 7.2 Integrate into `MessageBubble.tsx`: add `remarkCitations` + `rehypeRaw` + custom `rehypeSanitize` schema + `components` prop mapping `button` → `CitationRef`; add `CitationsBlock` and `ImageLightbox` with state management; implement expand → scroll → highlight on CitationRef click
- [x] 7.3 Run all MessageBubble tests (old + new) and confirm all pass

## 8. Backend Profile Schemas

- [x] 8.1 Create `backend/app/api/profile_schemas.py` — `TwinProfileResponse(name, has_avatar)`, `ProfileUpdateRequest(name)`, `AvatarUploadResponse(has_avatar)`
- [x] 8.2 Verify import succeeds (`python -c "from app.api.profile_schemas import ..."`)

## 9. Backend Profile Endpoints

- [x] 9.1 Write failing tests in `backend/tests/unit/test_profile_api.py` using `profile_app` fixture (GET twin, PUT profile, POST avatar rejects non-image, POST avatar rejects oversized, GET avatar returns 404 when no avatar)
- [x] 9.2 Create `profile_app` fixture in conftest following `admin_app` pattern (mount chat + admin profile routers, inject mock_storage_service with `download` mock)
- [x] 9.3 Implement `backend/app/api/profile.py` — `GET /chat/twin`, `GET /chat/twin/avatar` (SeaweedFS proxy), `PUT /admin/agent/profile`, `POST /admin/agent/avatar`, `DELETE /admin/agent/avatar`; use `get_session` dependency and `request.app.state.storage_service`
- [x] 9.4 Mount profile routers in `backend/app/main.py`
- [x] 9.5 Run tests and confirm all pass

## 10. Frontend Profile API Client

- [x] 10.1 Add `TwinProfile` interface (`name`, `has_avatar`) to `src/types/chat.ts`
- [x] 10.2 Add API functions to `src/lib/api.ts`: `getTwinProfile()`, `updateTwinProfile()`, `uploadTwinAvatar()`, `deleteTwinAvatar()`
- [x] 10.3 Add `adminMode` flag to `src/lib/config.ts` from `VITE_ADMIN_MODE`
- [x] 10.4 Verify build succeeds

## 11. ProfileEditModal Component

- [x] 11.1 Write failing tests for `ProfileEditModal` in `src/tests/components/ProfileEditModal.test.tsx` (name input, save callback, close, avatar upload trigger, local blob preview, remove avatar, hidden when closed, discard unsaved name changes on close without save)
- [x] 11.2 Implement `src/components/ProfileEditModal/` — Radix Dialog modal with name input, avatar upload zone with `URL.createObjectURL` local preview, save/remove/close handlers, discard unsaved changes on close
- [x] 11.3 Run tests and confirm all pass

## 12. Integrate Profile into ChatHeader and ChatPage

- [x] 12.1 Write failing tests in existing `src/tests/components/ChatHeader.test.tsx` (settings button visible when adminMode=true, hidden when false)
- [x] 12.2 Update `ChatHeader.tsx` — receive profile from API, render avatar from `/api/chat/twin/avatar` proxy URL, add Settings button gated by `adminMode` prop
- [x] 12.3 Update `ChatPage.tsx` — fetch `getTwinProfile()` on mount with env-var fallback, manage profile state and `profileModalOpen`, render `ProfileEditModal` with handlers
- [x] 12.4 Run all frontend tests and confirm all pass

## 13. UI Strings

- [x] 13.1 Add all remaining UI strings to `src/lib/strings.ts` (profileTitle, profileNameLabel, profileSave, profileRemoveAvatar, profileChangeAvatar, profileSettings, imageLightboxClose)
- [x] 13.2 Verify no hardcoded user-facing strings in new components

## 14. Test Coverage Review

- [x] 14.1 Review all new specs (citation-display, twin-profile, chat-ui delta) against implemented tests — identify any scenario not covered by a test
- [x] 14.2 Add missing tests for any uncovered scenarios (scroll-to-highlight interaction, lazy loading, discard unsaved state, etc.)
- [x] 14.3 Run full frontend test suite (`bun run test`) and confirm all pass

## 15. Full CI Verification and Self-Review

- [x] 15.1 Run all frontend tests (`bun run test`)
- [x] 15.2 Run frontend lint (`bun run lint`)
- [x] 15.3 Run frontend build (`bun run build`)
- [x] 15.4 Run all backend tests (`python -m pytest -v`)
- [x] 15.5 Run backend lint (`ruff check .`)
- [x] 15.6 Verify installed package versions against `docs/spec.md`
- [x] 15.7 Re-read `docs/development.md` and self-review the change against it — confirm: no mocks outside tests, no stubs without story reference, SOLID/KISS/DRY/YAGNI, all new files have tests, no secrets in code
- [ ] 15.8 Manual smoke test if dev server available (send message with citations, verify superscripts + sources block + settings modal)
