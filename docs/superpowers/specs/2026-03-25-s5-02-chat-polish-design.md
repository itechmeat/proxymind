# S5-02: Chat Polish — Citations Display + Twin Profile

## Summary

Add inline citation rendering, a collapsible sources block under assistant messages, and a twin profile management UI (avatar upload + name editing). This story is frontend-heavy with a small backend addition for profile endpoints.

**Parallel pair:** S4-05 (Promotions + context assembly) — frontend vs backend, zero file overlap.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Inline citation style | Superscript numbers (¹²³) | Does not break reading flow; matches Perplexity UX; badges are too heavy for 3-5 citations per paragraph |
| Sources block | Collapsible (Perplexity-style) | Exactly what the plan describes; clean UI; collapsed by default keeps message area tidy |
| Source type indicators | lucide-react SVG icons, color-coded per type | Tree-shakeable (~2KB), visually immediate; CSS-only badges are less elegant |
| Image source click | Opens lightbox modal | Natural UX for images; lightweight component |
| PDF fragment preview | Deferred | Requires backend page-render endpoint; out of scope |
| Twin profile data source | API with env var fallback | Agent table already has `name` and `avatar_url`; env vars preserved as fallback for backward compatibility |
| Profile edit location | Modal from chat header, gated by `VITE_ADMIN_MODE` | Settings button hidden by default; owner enables via env var. **UI-only guard** — does not protect backend endpoints (S7-01 auth is required before non-local deployment) |
| Avatar storage | Object key in DB, proxy endpoint for browser | Browser never talks to SeaweedFS directly; `GET /api/chat/twin/avatar` proxies the file |
| Profile backend file | New `profile.py` router | Avoids bloating `admin.py`; no overlap with S4-05 |
| Icon library | lucide-react | Standard for React + Radix UI; tree-shakeable; used for both citation icons and UI icons |
| Pluralization | Count-only format `"Sources (3)"` | Avoids language-specific plural forms; works for all languages per multilingual policy |
| Description field | Excluded from S5-02 scope | YAGNI — story specifies name + avatar only; trivial to add later |

## Deferred items

- **Public links schema extension** — noted in plan as deferred to a future story.
- **PDF fragment preview** — requires a backend endpoint to render a specific PDF page as image. Out of S5-02 scope.

---

## Section 1: Inline Citations (Markdown Processing)

Markers `[source:N]` in assistant text are replaced with clickable superscript numbers during rendering.

### Implementation

- A custom **remark plugin** (`remark-citations.ts`) for ReactMarkdown. During Markdown AST traversal, the plugin finds text nodes containing `[source:N]` patterns and replaces them with `html` type mdast nodes containing `<sup><button class="citation-ref" data-citation-index="N">N</button></sup>`.
- **`rehype-raw`** (new dependency) is added to the ReactMarkdown plugin chain to parse these HTML nodes into the hast tree. Plugin order: `remarkCitations → rehypeRaw → rehypeSanitize` (with a strict allowlist schema that allows only `sup`, `button[class, data-citation-index, aria-label, type]` for citation markup).
- ReactMarkdown's **`components` prop** maps `button` elements: when `className === "citation-ref"`, render the `CitationRef` React component instead of a plain `<button>`. This connects the remark output to the interactive React component.
- `CitationRef` renders as `<sup><button>N</button></sup>`, styled in indigo (#818cf8).
- **Click behavior:** `CitationRef.onClick` calls a callback from `MessageBubble`. If the sources block is collapsed, expand it first. Then scroll to the corresponding source item and briefly highlight it (CSS animation, ~1s fade).
- Replacement happens at **render time only** — the raw text in `message.parts` is never mutated. Original text is preserved for copy-to-clipboard and history.
- The plugin applies **only to assistant messages**. User messages render as plain text (unchanged).

### Data flow

`CitationResponse[]` already arrives via SSE event `type: "citations"` and is stored in `message.metadata.citations`. The plugin receives citations via its options object. The `CitationRef` click callback is passed through ReactMarkdown's `components` prop closure.

### Edge cases

- `[source:0]` or `[source:N]` where N > citations.length — left as plain text (not replaced).
- Message with no citations — plugin is a no-op.
- Streaming state — `[source:N]` markers may appear in partial text before citations arrive. During streaming, markers render as plain text. Once citations arrive (SSE `citations` event), a re-render replaces them with superscripts.

---

## Section 2: Collapsible Sources Block

A collapsible block of sources rendered below each assistant message that has citations.

### Component: `CitationsBlock`

**Location in DOM:** Inside `MessageBubble`, after `message-bubble__card`, before `message-bubble__meta`. Renders only when `message.metadata.citations` is non-empty AND `state !== "streaming"`.

### States

- **Collapsed (default):** A single line: `"▶ Sources (N)"` — clickable toggle. Format produced by `strings.sourcesCount(N)`, language-neutral.
- **Expanded:** A bordered list with header `"▼ Sources (N)"` and source items.

### Source item structure

Each source item in the expanded list contains:

| Element | Description |
|---------|-------------|
| **Number** | Index from citation (indigo, bold) — matches superscript in text |
| **Icon** | lucide-react SVG, color-coded by `source_type` (see mapping below) |
| **Title** | Source title with anchor info (e.g., `"Meditations", Chapter 5`) |
| **Meta line** | Type label + additional info (`PDF · p. 42`, `Article · example.com`, `Video · at 03:24`) |

### Source type → icon mapping

| source_type | Icon (lucide-react) | Color |
|-------------|---------------------|-------|
| `pdf` | `FileText` | #ef4444 (red) |
| `docx` | `FileText` | #6b7280 (gray) |
| `markdown` | `FileType` | #6b7280 (gray) |
| `txt` | `FileType` | #6b7280 (gray) |
| `html` | `Globe` | #3b82f6 (blue) |
| `image` | `ImageIcon` | #10b981 (green) |
| `audio` | `Headphones` | #f59e0b (amber) |
| `video` | `Video` | #a855f7 (purple) |

Mapping lives in `lib/source-icons.ts` — a pure function `getSourceIcon(sourceType: string): { icon: LucideIcon, color: string }`.

### Click behavior per source type

- **Online** (`url !== null`, not image): `<a href={url} target="_blank" rel="noopener noreferrer">` — title is a blue underlined link, opens in new tab.
- **Offline** (`url === null`): Title is plain white text (not clickable). Anchor info in meta provides context.
- **Image** (`source_type === "image"` AND `url !== null`): Click opens `ImageLightbox` modal with the image from SeaweedFS.

### Component: `ImageLightbox`

Minimal lightbox modal for image preview:

- Dark overlay backdrop (click to close).
- Image scaled to `max-width: 90vw; max-height: 85vh; object-fit: contain`.
- Close via: click outside image, Escape key, X button in corner.
- Lazy loading: `<img>` element created only when modal opens.
- No carousel, no zoom — minimal viable lightbox.

---

## Section 3: Twin Profile — Backend API

New endpoints for reading and updating the twin's profile (name, avatar). The `agents` table already has `name` (String 255) and `avatar_url` (String 2048) columns.

### New endpoints

#### `GET /api/chat/twin` (public, Chat API router)

Returns the twin's public profile for display in the chat UI.

```json
{
  "name": "Marcus Aurelius",
  "has_avatar": true
}
```

Source: `agents` table, `DEFAULT_AGENT_ID`. `has_avatar` is derived from `avatar_url IS NOT NULL`. No internal URLs exposed.

#### `GET /api/chat/twin/avatar` (public, Chat API router)

Proxies the avatar image from SeaweedFS. Returns the image bytes with correct `Content-Type` header. Returns 404 if no avatar is set.

This endpoint exists because SeaweedFS is internal — the browser cannot access it directly. The frontend uses `/api/chat/twin/avatar` as the `<img src>`.

#### `PUT /api/admin/agent/profile` (Admin API)

Updates agent name.

```json
// Request body
{ "name": "Marcus Aurelius" }

// Response
{ "name": "Marcus Aurelius", "has_avatar": true }
```

Validation: `name` max 255 chars, required.

#### `POST /api/admin/agent/avatar` (Admin API)

Uploads a new avatar image.

- **Input:** Multipart form, field `file`.
- **Validation:** Declared content type MUST be one of `image/jpeg`, `image/png`, `image/webp`, `image/gif`. File signature bytes MUST match the declared image type. File size MUST be ≤ 2MB.
- **Storage:** `agents.avatar_url` stores the **SeaweedFS object key** (e.g., `agents/{agent_id}/avatar/{uuid}.{ext}`), NOT a full URL. The browser accesses the image via `GET /api/chat/twin/avatar` proxy endpoint.
- **Pipeline:** Validate → upload to SeaweedFS → update `agents.avatar_url` with object key → delete old file from SeaweedFS (if exists) → return `{ has_avatar: true }`.
- **Cleanup failure handling:** Old-avatar deletion remains best-effort. If the delete call fails, the profile update stays committed and the backend logs a structured warning for follow-up.

#### `DELETE /api/admin/agent/avatar` (Admin API)

Removes the current avatar.

- Deletes file from SeaweedFS, sets `agents.avatar_url = NULL`.
- Returns `{ has_avatar: false }`.

### Backend file structure

New file: `backend/app/api/profile.py` with a dedicated router. Mounted in `main.py` at:
- `GET /api/chat/twin` — on the chat router
- `PUT /api/admin/agent/profile`, `POST /api/admin/agent/avatar`, `DELETE /api/admin/agent/avatar` — on the admin router

This avoids bloating `admin.py` and prevents file overlap with S4-05 (Promotions).

---

## Section 4: Twin Profile — Frontend

Chat header fetches profile from API and provides a modal for editing.

### Profile loading

- New function in `lib/api.ts`: `getTwinProfile(): Promise<TwinProfile>` → `GET /api/chat/twin`.
- `ChatPage` calls on mount, passes result to `ChatHeader` and `MessageBubble`.
- **Fallback chain:** API response → env vars (`appConfig.twinName`, `appConfig.twinAvatarUrl`) → defaults ("ProxyMind", initials avatar).

### ChatHeader updates

- Receives `name` and `has_avatar` from API response. Avatar `<img src>` points to `/api/chat/twin/avatar` (proxy endpoint), not SeaweedFS directly.
- New `Settings` icon button (lucide-react) in the right part of the header. **Gated by `VITE_ADMIN_MODE` env var** — button is rendered only when `import.meta.env.VITE_ADMIN_MODE === "true"`. Default: hidden. **This is a UI-only guard** — it hides the button but does NOT protect backend endpoints. Admin endpoints remain unprotected until S7-01 (auth + rate limiting), which MUST be implemented before any non-local deployment per the security ordering note in `docs/plan.md`.
- Click opens `ProfileEditModal`.

### Component: `ProfileEditModal`

A modal dialog for editing the twin's profile.

- **Technology:** Radix Dialog (`@radix-ui/react-dialog`) — consistent with existing Radix usage for Avatar, ScrollArea, etc. If not already installed, add as dependency.
- **Contents:**
  - **Avatar zone:** Current avatar displayed with "Change" overlay on hover. Click triggers a hidden `<input type="file" accept="image/*">`. After file selection → instant preview (local `URL.createObjectURL`) + upload via `POST /api/admin/agent/avatar`. Success → update state.
    Blob URLs created for local preview are revoked when replaced, when the modal closes, and on component unmount. Failed uploads restore the previous preview and surface an inline error message instead of leaving a stale preview on screen.
  - **Name field:** Text input with current value. Change is saved via `PUT /api/admin/agent/profile` on "Save" button click.
  - **"Remove avatar" button:** Visible when avatar exists. Calls `DELETE /api/admin/agent/avatar`.
- **Optimistic UI:** After successful upload/save, state in `ChatPage` updates immediately — header and message avatars reflect the change without page reload.
- **Close:** Escape, click outside, X button.

### API functions (additions to `lib/api.ts`)

```
getTwinProfile() → GET /api/chat/twin → { name, has_avatar }
updateTwinProfile(data) → PUT /api/admin/agent/profile
uploadTwinAvatar(file) → POST /api/admin/agent/avatar
deleteTwinAvatar() → DELETE /api/admin/agent/avatar
```

Avatar image URL for `<img src>` is constructed as `buildApiUrl("/api/chat/twin/avatar")` — not fetched from the profile response.

### New frontend files

```
src/components/
  CitationsBlock/
    CitationsBlock.tsx
    CitationsBlock.css
    CitationsBlock.test.tsx
    index.ts
  CitationRef/
    CitationRef.tsx
    CitationRef.css
    index.ts
  ImageLightbox/
    ImageLightbox.tsx
    ImageLightbox.css
    ImageLightbox.test.tsx
    index.ts
  ProfileEditModal/
    ProfileEditModal.tsx
    ProfileEditModal.css
    ProfileEditModal.test.tsx
    index.ts
src/lib/
  remark-citations.ts
  remark-citations.test.ts
  source-icons.ts
```

### Files modified

- `MessageBubble.tsx` — add CitationsBlock, use remark plugin with rehype-raw + components mapping
- `ChatHeader.tsx` — add settings button (gated by `VITE_ADMIN_MODE`), receive profile from API
- `ChatPage.tsx` — fetch twin profile, manage profile state
- `lib/api.ts` — add profile API functions
- `lib/config.ts` — add `adminMode` flag from `VITE_ADMIN_MODE`
- `lib/strings.ts` — add new UI strings
- `types/chat.ts` — add `TwinProfile` interface (name + has_avatar, no description)

### Files NOT modified (zero overlap guarantee)

`ChatInput`, `StreamingIndicator`, `MessageList`, `useSession`, `transport.ts`, `sse-parser.ts`, `message-adapter.ts`.

---

## Section 5: Testing

### Frontend (Vitest + Testing Library)

**`remark-citations.test.ts`** — unit tests for the remark plugin:
- `[source:1]` → replaced with CitationRef component
- `[source:0]`, `[source:99]` (out of range) → left as plain text
- Multiple `[source:N]` in one paragraph → all replaced
- Text without markers → unchanged
- User message context → plugin not applied

**`CitationsBlock.test.tsx`** — component tests:
- Not rendered when `citations` is empty
- Collapsed by default: shows "N sources" text
- Click toggle → expanded: source list visible
- Online source: rendered as link with `target="_blank"`
- Offline source: rendered as plain text, not clickable
- Icon matches `source_type`
- Image source: click opens lightbox

**`ImageLightbox.test.tsx`** — component tests:
- Opens and closes (Escape, click outside, X button)
- Renders `<img>` with correct `src`

**`ProfileEditModal.test.tsx`** — component tests:
- Modal opens and closes
- Name input shows current value
- Submit calls API
- Avatar upload: file input triggered on avatar zone click
- Remove avatar: calls DELETE endpoint

**`MessageBubble.test.tsx`** — update existing tests:
- Assistant message with citations → renders CitationsBlock
- Assistant message without citations → does not render CitationsBlock
- Streaming state → CitationsBlock not shown

### Backend (pytest)

**`test_profile_api.py`** — integration tests:
- `GET /api/chat/twin` → 200 with agent data
- `PUT /api/admin/agent/profile` → updates name
- `POST /api/admin/agent/avatar` → validates image type, rejects non-images, rejects files > 2MB, stores in SeaweedFS
- `GET /api/chat/twin/avatar` → proxies avatar image, returns 404 when no avatar
- `DELETE /api/admin/agent/avatar` → removes avatar, sets `avatar_url` to null

### Out of scope

- E2E tests (no Playwright/Cypress in the project)
- Visual regression tests

---

## Dependencies

### New npm packages

| Package | Purpose | Size impact |
|---------|---------|-------------|
| `lucide-react` | Source type icons + UI icons (Settings, X) | ~2KB (tree-shaken) |
| `rehype-raw` | Parse HTML nodes inserted by remark-citations plugin | ~3KB |

### No new Python packages

All backend work uses existing dependencies (FastAPI, SQLAlchemy, httpx for SeaweedFS).

---

## Component hierarchy (updated)

```
ChatPage
├── ChatHeader
│   ├── Avatar (twin)
│   ├── Name + Status
│   └── Settings button → ProfileEditModal
├── MessageList
│   └── MessageBubble (per message)
│       ├── Avatar (twin, for assistant messages)
│       ├── Card
│       │   ├── ReactMarkdown + remark-citations plugin
│       │   │   └── CitationRef (per [source:N] marker)
│       │   └── StreamingIndicator
│       ├── CitationsBlock (if citations present & not streaming)
│       │   └── Source items (icon + title + meta)
│       │       └── ImageLightbox (for image sources)
│       ├── Meta (timestamp, badges)
│       └── Actions (retry button)
└── ChatInput
```
