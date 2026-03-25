## Story

**S5-01: Chat UI** (Phase 5: Frontend)

Verification: open → send message → streaming response → history on refresh

Parallel pair: S4-04 (Query rewriting) — pure frontend vs pure backend, zero file overlap.

## Why

ProxyMind has a fully functional backend (chat API with SSE streaming, knowledge snapshots, citations, persona) but no browser interface. Visitors cannot interact with the digital twin. The web chat UI is the primary visitor-facing experience and the foundation for all subsequent frontend work (S5-02 citations display, S5-03 admin UI).

## What Changes

- Add a full-page chat interface (React 19 + Vite 8 + Bun) with input field, message feed, and twin avatar/name header
- Implement SSE streaming client that consumes the existing `POST /api/chat/messages` SSE stream
- Integrate AI SDK (`ai` + `@ai-sdk/react`) for chat state management via `useChat` hook with a custom transport adapter, with fallback to a custom hook if AI SDK transport API is incompatible
- Add session persistence via localStorage + `GET /api/chat/sessions/:id` for history on refresh
- Add shadcn/ui component library + Tailwind CSS for UI primitives
- Add React Router for page routing (prepares for S5-03 admin pages)
- Add Vitest + React Testing Library test infrastructure
- Add centralized UI strings module (`lib/strings.ts`) for language configurability per project policy
- Configure Vite dev proxy (`/api → :8000`) for CORS-free local development
- Render assistant messages as Markdown with XSS protection (react-markdown + rehype-sanitize)

## Capabilities

### New Capabilities

- `chat-ui`: Browser chat interface — layout, components, SSE streaming, session management, error handling, responsive design
- `chat-ui-transport`: SSE transport adapter bridging backend format to AI SDK, SSE parser, message format adapter
- `frontend-testing`: Vitest + React Testing Library infrastructure, test setup, CI-compatible test scripts

### Modified Capabilities

- `frontend-skeleton`: The placeholder App component is replaced by a working chat interface with React Router. The `VITE_API_URL` behavior changes from an absolute backend URL to relative paths via Vite dev proxy (empty default). New env vars added (`VITE_TWIN_NAME`, `VITE_TWIN_AVATAR_URL`). Vite config gains Tailwind plugin and `server.proxy`.

## Impact

- **Frontend:** Replaces the bootstrap landing page with a working chat interface. All new files under `frontend/src/`.
- **Backend:** Zero changes. Consumes existing Chat API (`POST /api/chat/sessions`, `POST /api/chat/messages`, `GET /api/chat/sessions/:id`).
- **Dependencies:** Adds ~10 new npm packages (ai, @ai-sdk/react, react-router, react-markdown, rehype-sanitize, tailwindcss, shadcn/ui, vitest, testing-library).
- **Infrastructure:** Vite config updated with Tailwind plugin and dev proxy. No Docker/Caddy changes.
- **Testing:** Adds frontend test infrastructure. All stable behavior (session management, SSE parsing, message rendering, error handling) MUST be covered by tests before archive per Phase 5 requirements.
