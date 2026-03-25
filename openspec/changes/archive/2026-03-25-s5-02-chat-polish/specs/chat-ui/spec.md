## MODIFIED Requirements

### Requirement: ChatHeader displays twin identity

The ChatHeader SHALL display the twin's avatar and name. On mount, ChatPage SHALL fetch the twin profile from `GET /api/chat/twin`, which returns `{ name, has_avatar }`. ChatPage SHALL pass the resolved `name` and `has_avatar` to ChatHeader. When `has_avatar` is `true`, the avatar `<img>` element SHALL use `/api/chat/twin/avatar` as its `src` (the proxy endpoint). When `has_avatar` is `false`, the avatar SHALL fall back to displaying initials derived from the twin name.

The fallback chain for profile data SHALL be: API response, then environment variables (`VITE_TWIN_NAME`, `VITE_TWIN_AVATAR_URL`), then defaults ("ProxyMind", initials avatar). If the API call fails or returns incomplete data, the system SHALL fall back to env vars. For this story, incomplete data means the API profile object has no `name` value or only whitespace in `name`. If env vars are also absent, the system SHALL use defaults.

The ChatHeader SHALL render a Settings icon button (lucide-react `Settings` icon) in the right section of the header. The Settings button SHALL be rendered only when `import.meta.env.VITE_ADMIN_MODE === "true"`. When `VITE_ADMIN_MODE` is not `"true"` or is unset, the Settings button SHALL NOT be rendered. This is a UI-only guard -- it does not protect backend endpoints.

#### Scenario: Avatar from URL

- **WHEN** `VITE_TWIN_AVATAR_URL` is set to a valid image URL and the API is unavailable
- **THEN** the ChatHeader SHALL render an `img` element with that URL as the avatar

#### Scenario: Avatar fallback to initials

- **WHEN** the API is unavailable
- **AND** `VITE_TWIN_AVATAR_URL` is empty or not set
- **THEN** the ChatHeader SHALL render initials derived from the twin name as the avatar fallback

#### Scenario: Twin name displayed

- **WHEN** the ChatHeader renders
- **THEN** it SHALL display the twin name as text next to the avatar

#### Scenario: Profile loaded from API

- **WHEN** ChatPage mounts and `GET /api/chat/twin` returns `{ name: "Marcus Aurelius", has_avatar: true }`
- **THEN** the ChatHeader SHALL display "Marcus Aurelius" as the twin name
- **AND** the avatar `<img>` element SHALL have `src` set to the `/api/chat/twin/avatar` proxy endpoint

#### Scenario: API returns profile without avatar

- **WHEN** `GET /api/chat/twin` returns `{ name: "Marcus Aurelius", has_avatar: false }`
- **THEN** the ChatHeader SHALL display "Marcus Aurelius" as the twin name
- **AND** the avatar SHALL render initials derived from "Marcus Aurelius"

#### Scenario: API failure falls back to env vars

- **WHEN** `GET /api/chat/twin` fails with a network error or non-200 status
- **AND** `VITE_TWIN_NAME` is set to "Seneca"
- **THEN** the ChatHeader SHALL display "Seneca" as the twin name
- **AND** the avatar SHALL use `VITE_TWIN_AVATAR_URL` if set, or initials otherwise

#### Scenario: Full fallback to defaults

- **WHEN** `GET /api/chat/twin` fails
- **AND** `VITE_TWIN_NAME` is not set
- **THEN** the ChatHeader SHALL display "ProxyMind" as the twin name
- **AND** the avatar SHALL render initials derived from "ProxyMind"

#### Scenario: Settings button visible in admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` equals `"true"`
- **THEN** the ChatHeader SHALL render a Settings icon button (lucide-react) in the right section

#### Scenario: Settings button hidden when not admin

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **THEN** the ChatHeader SHALL NOT render the Settings icon button

---

### Requirement: MessageBubble rendering by role

User messages SHALL be right-aligned with an accent background and plain text content. Assistant messages SHALL be left-aligned with a neutral background, a small twin avatar on the left, and content rendered as Markdown via `react-markdown`. Both message types SHALL display a relative timestamp (e.g., "just now", "2m ago").

For assistant messages, the `react-markdown` plugin chain SHALL include the custom `remarkCitations` remark plugin, `rehypeRaw`, and `rehypeSanitize` (with a strict allowlist schema that allows only `sup` and `button[class, data-citation-index, aria-label, type]` for the citation markup). The plugin order SHALL be: `remarkCitations`, then `rehypeRaw`, then `rehypeSanitize`. The `remarkCitations` plugin SHALL treat citation markers as 1-based indices: `[source:1]` through `[source:N]` correspond to the first through Nth entries in the citations array. It SHALL find `[source:N]` patterns in text nodes and replace them with HTML nodes containing `<sup><button class="citation-ref" data-citation-index="N">N</button></sup>`. The `react-markdown` `components` prop SHALL map `button` elements with `className === "citation-ref"` to the `CitationRef` React component, rendering interactive superscript citation markers styled in indigo.

The replacement SHALL happen at render time only -- the raw text in `message.parts` SHALL NOT be mutated. The plugin SHALL apply only to assistant messages. User messages SHALL render as plain text (unchanged). Out-of-range markers (`[source:0]` or `[source:N]` where N exceeds the citations array length) SHALL be left as plain text. During streaming, `[source:N]` markers SHALL render as plain text until citations arrive via the SSE `citations` event, at which point a re-render SHALL replace them with interactive superscripts.

When an assistant message has non-empty `message.metadata.citations` and the message state is not `"streaming"`, a `CitationsBlock` component SHALL render below the message card, inside `MessageBubble`, after the card and before the meta section. Interactive `CitationRef` superscripts SHALL render only under the same two conditions: citations are populated and the message state is not `"streaming"`. When citations are empty or the message state is `"streaming"`, the `CitationsBlock` SHALL NOT render and citation markers SHALL remain plain text.

#### Scenario: User message appearance

- **WHEN** a message with `role: "user"` is rendered
- **THEN** the MessageBubble SHALL be right-aligned with accent styling and plain text content

#### Scenario: Assistant message Markdown rendering

- **WHEN** a message with `role: "assistant"` is rendered with Markdown content (e.g., bold, lists, code blocks)
- **THEN** the MessageBubble SHALL render the Markdown as formatted HTML via `react-markdown`
- **AND** the rendered HTML SHALL be sanitized by `rehype-sanitize` to prevent XSS

#### Scenario: Assistant message has twin avatar

- **WHEN** an assistant message is rendered
- **THEN** a small twin avatar SHALL appear to the left of the message bubble

#### Scenario: Relative timestamp displayed

- **WHEN** a message is rendered with a `created_at` timestamp
- **THEN** the MessageBubble SHALL display a human-readable relative time (e.g., "just now", "5m ago")

#### Scenario: Citation markers rendered as superscripts

- **WHEN** an assistant message contains `[source:1]` and `[source:2]` markers in its text
- **AND** `message.metadata.citations` contains at least 2 citations
- **AND** the message state is not `"streaming"`
- **THEN** each `[source:N]` marker SHALL be replaced with an interactive `CitationRef` superscript component displaying the number N
- **AND** the superscripts SHALL be styled in indigo

#### Scenario: Out-of-range citation markers left as plain text

- **WHEN** an assistant message contains `[source:0]` or `[source:5]` and the citations array has only 3 entries
- **THEN** the out-of-range markers SHALL be left as plain text and SHALL NOT be replaced with superscript components

#### Scenario: Citation markers during streaming render as plain text

- **WHEN** an assistant message has state `"streaming"` and contains `[source:1]` in partial text
- **AND** citations have not yet arrived via the SSE `citations` event
- **THEN** `[source:1]` SHALL render as plain text

#### Scenario: Citations re-render after SSE citations event

- **WHEN** the SSE `citations` event arrives and `message.metadata.citations` is populated
- **AND** the message state transitions from `"streaming"` to `"complete"`
- **THEN** all valid `[source:N]` markers SHALL be replaced with interactive `CitationRef` superscripts

#### Scenario: CitationsBlock rendered for cited assistant message

- **WHEN** an assistant message has non-empty `message.metadata.citations`
- **AND** the message state is not `"streaming"`
- **THEN** a `CitationsBlock` SHALL render below the message card and before the meta section

#### Scenario: CitationsBlock not rendered when no citations

- **WHEN** an assistant message has empty `message.metadata.citations`
- **THEN** the `CitationsBlock` SHALL NOT render

#### Scenario: CitationsBlock not rendered during streaming

- **WHEN** an assistant message has state `"streaming"`
- **THEN** the `CitationsBlock` SHALL NOT render, even if partial citation data exists

#### Scenario: Raw message text preserved

- **WHEN** citation markers are rendered as superscript components
- **THEN** the original text in `message.parts` SHALL NOT be mutated
- **AND** the raw `[source:N]` text SHALL be preserved for copy-to-clipboard and history
