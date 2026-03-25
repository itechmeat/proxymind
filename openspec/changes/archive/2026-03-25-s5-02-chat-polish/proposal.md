## Story

**S5-02: Chat polish — citations display + twin profile**

**Verification criteria:** citation in response produces clickable superscript; collapse/expand block shows sources; avatar visible in chat header; settings modal allows name/avatar changes.

**Parallel pair:** S4-05 (Promotions + context assembly) — frontend vs backend, zero file overlap.

## Why

The chat UI (S5-01) streams responses and displays Markdown, but citations arrive as raw `[source:N]` markers with no visual treatment — users cannot see or navigate to the sources backing a response. Additionally, the twin's identity in the chat header is hardcoded via environment variables with no way to update name or avatar through the UI.

## What Changes

- Replace `[source:N]` markers in assistant messages with clickable superscript numbers (Wikipedia-style)
- Add a collapsible "Sources (N)" block under each cited message (Perplexity-style), with source type icons, anchor metadata, and clickable links for online sources
- Add image lightbox modal for image-type sources
- Add backend endpoints for twin profile CRUD (name, avatar upload/download via SeaweedFS proxy)
- Add frontend profile edit modal accessible from chat header (gated by `VITE_ADMIN_MODE`)
- Add `lucide-react` and `rehype-raw` frontend dependencies

## Capabilities

### New Capabilities

- `citation-display`: Inline superscript citation rendering, collapsible sources block with type-specific icons, image lightbox, and scroll-to-highlight interaction
- `twin-profile`: Backend profile API (GET/PUT/POST/DELETE), avatar proxy endpoint, frontend profile edit modal with local preview and optimistic updates

### Modified Capabilities

- `chat-ui`: MessageBubble gains citation rendering (remark plugin + rehype-raw + components mapping) and CitationsBlock; ChatHeader gains settings button and API-driven profile; ChatPage gains profile state management

## Impact

- **Frontend:** New components (CitationsBlock, CitationRef, ImageLightbox, ProfileEditModal), modified MessageBubble/ChatHeader/ChatPage, new remark plugin, new dependencies (lucide-react, rehype-raw)
- **Backend:** New `profile.py` router with 5 endpoints, new `profile_schemas.py`, mounted in `main.py`
- **No overlap with:** S4-05 files (persona.py, prompt.py, admin.py prompt-assembly code, PROMOTIONS.md)
- **Security:** Admin endpoints remain unprotected until S7-01; `VITE_ADMIN_MODE` is a UI-only guard (documented)
