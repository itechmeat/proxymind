## Purpose

Inline citation rendering in assistant messages — superscript markers, collapsible sources block, source type icons, click behavior per source type, image lightbox, and scroll-to-highlight interaction. Introduced by S5-02.

## ADDED Requirements

### Requirement: Inline citation superscripts

A custom remark plugin SHALL replace `[source:N]` markers in assistant message text with clickable superscript numbers. The plugin SHALL operate at render time only — the raw text in `message.parts` SHALL NOT be mutated. The plugin SHALL apply only to assistant messages; user messages SHALL render as plain text. Out-of-range markers (`N < 1` or `N > citations.length`) SHALL be left as plain text. When citations have not yet arrived during streaming, markers SHALL render as plain text until the citations SSE event triggers a re-render.

#### Scenario: Valid marker replaced with superscript

- **WHEN** an assistant message contains `[source:1]` and `citations` includes an entry with `index: 1`
- **THEN** the marker SHALL be replaced with a clickable `<sup><button>` element displaying "1"
- **AND** the button SHALL be styled in indigo (#818cf8)

#### Scenario: Multiple markers in one paragraph

- **WHEN** an assistant message contains `[source:1]` and `[source:2]` in the same paragraph
- **THEN** both markers SHALL be replaced with their respective superscript buttons

#### Scenario: Out-of-range marker left as text

- **WHEN** an assistant message contains `[source:0]` or `[source:99]` and `citations` has fewer than 99 entries
- **THEN** the marker SHALL remain as plain text and no button SHALL be rendered for it

#### Scenario: No markers in text

- **WHEN** an assistant message contains no `[source:N]` patterns
- **THEN** the plugin SHALL be a no-op and the text SHALL render normally

#### Scenario: Empty citations array

- **WHEN** the `citations` array is empty
- **THEN** all `[source:N]` markers SHALL remain as plain text

#### Scenario: Markers during streaming before citations arrive

- **WHEN** an assistant message is still streaming and the `citations` SSE event has not yet arrived
- **THEN** `[source:N]` markers SHALL render as plain text
- **AND** once the `citations` event arrives and triggers a re-render, valid markers SHALL be replaced with superscripts

---

### Requirement: Collapsible sources block

A collapsible block SHALL render below each assistant message that has citations. The block SHALL NOT render when `citations` is empty. The block SHALL NOT render while the message is in a streaming state.

#### Scenario: Block hidden when no citations

- **WHEN** an assistant message has an empty `citations` array
- **THEN** no sources block SHALL be rendered

#### Scenario: Block hidden during streaming

- **WHEN** an assistant message is in streaming state
- **THEN** the sources block SHALL NOT be rendered, even if citations exist

#### Scenario: Collapsed by default

- **WHEN** an assistant message with citations finishes streaming
- **THEN** the sources block SHALL render in a collapsed state showing a toggle with the source count

#### Scenario: Expand on click

- **WHEN** the user clicks the collapsed toggle
- **THEN** the block SHALL expand to show the full list of source items

#### Scenario: Collapse on second click

- **WHEN** the user clicks the toggle while the block is expanded
- **THEN** the block SHALL collapse back to the single-line toggle

---

### Requirement: Source type icons

Each source item in the expanded sources block SHALL display a lucide-react SVG icon color-coded by `source_type`. The mapping SHALL be: `pdf` = FileText / #ef4444 (red), `docx` = FileText / #6b7280 (gray), `markdown` = FileType / #6b7280 (gray), `txt` = FileType / #6b7280 (gray), `html` = Globe / #3b82f6 (blue), `image` = ImageIcon / #10b981 (green), `audio` = Headphones / #f59e0b (amber), `video` = Video / #a855f7 (purple). Unknown source types SHALL fall back to FileText / #6b7280 (gray).

#### Scenario: Known source type renders correct icon and color

- **WHEN** a citation has `source_type: "pdf"`
- **THEN** the source item SHALL display the FileText icon in red (#ef4444)

#### Scenario: Each type maps to its designated icon

- **WHEN** citations include entries with source types `html`, `image`, `audio`, and `video`
- **THEN** each source item SHALL display Globe (blue), ImageIcon (green), Headphones (amber), and Video (purple) respectively

#### Scenario: Unknown source type uses default

- **WHEN** a citation has a `source_type` value not in the mapping (e.g., "spreadsheet")
- **THEN** the source item SHALL display the FileText icon in gray (#6b7280)

---

### Requirement: Source click behavior

Online sources (where `url` is not null and `source_type` is not `image`) SHALL render as links that open in a new tab with `target="_blank"` and `rel="noopener noreferrer"`. Offline sources (where `url` is null) SHALL render as plain text that is not clickable. Image sources (where `source_type` is `image` and `url` is not null) SHALL open an image lightbox on click.

#### Scenario: Online source opens in new tab

- **WHEN** a citation has `source_type: "html"` and `url: "https://example.com"`
- **THEN** the source title SHALL be an anchor element with `href="https://example.com"` and `target="_blank"`

#### Scenario: Offline source is plain text

- **WHEN** a citation has `url: null`
- **THEN** the source title SHALL render as a non-clickable text span
- **AND** it SHALL NOT be wrapped in an anchor element

#### Scenario: Image source opens lightbox

- **WHEN** a citation has `source_type: "image"` and `url` is not null
- **THEN** clicking the source title SHALL open the image lightbox with that URL

---

### Requirement: Image lightbox

An image lightbox modal SHALL display a full-screen overlay with the source image when triggered. The image SHALL be scaled to fit within `max-width: 90vw` and `max-height: 85vh` with `object-fit: contain`. The `<img>` element SHALL be created only when the modal opens (lazy loading). The lightbox SHALL close when the user presses Escape, clicks outside the image, or clicks the close (X) button.

#### Scenario: Lightbox opens with image

- **WHEN** the lightbox is triggered with an image URL
- **THEN** a modal overlay SHALL appear with the image rendered inside it

#### Scenario: Close via Escape key

- **WHEN** the lightbox is open and the user presses the Escape key
- **THEN** the lightbox SHALL close

#### Scenario: Close via click outside

- **WHEN** the lightbox is open and the user clicks on the overlay backdrop (outside the image)
- **THEN** the lightbox SHALL close

#### Scenario: Close via X button

- **WHEN** the lightbox is open and the user clicks the close button
- **THEN** the lightbox SHALL close

#### Scenario: Lazy loading

- **WHEN** the lightbox is not open
- **THEN** no `<img>` element for the lightbox image SHALL exist in the DOM

---

### Requirement: Citation scroll-to-highlight

Clicking a superscript citation number SHALL scroll the corresponding source item into view and briefly highlight it. If the sources block is collapsed, it SHALL be expanded first before scrolling.

#### Scenario: Click superscript scrolls to source

- **WHEN** the user clicks a superscript citation number and the sources block is already expanded
- **THEN** the view SHALL scroll to the corresponding source item in the list
- **AND** the source item SHALL be briefly highlighted (CSS animation, approximately 1 second fade)

#### Scenario: Click superscript expands collapsed block then scrolls

- **WHEN** the user clicks a superscript citation number and the sources block is collapsed
- **THEN** the sources block SHALL expand first
- **AND** then the view SHALL scroll to the corresponding source item and highlight it

---

### Requirement: Language-neutral source count

The sources block toggle label SHALL use a `sourcesCount(N)` format function from `lib/strings.ts` that produces a count-based string (default: `"Sources (3)"`). The label SHALL NOT use language-specific plural forms (e.g., no `count === 1 ? "source" : "sources"`). The default text is English; installations in other languages configure the format by modifying `strings.ts`, per the project's Product Language Policy and the centralized UI strings pattern from S5-01.

#### Scenario: Source count displayed

- **WHEN** a message has 3 citations
- **THEN** the toggle label SHALL display a string containing "3" and the word "Sources" in the format produced by `sourcesCount(3)`

#### Scenario: Single source count

- **WHEN** a message has 1 citation
- **THEN** the toggle label SHALL display the count using the same format function, without special singular form

---

### Requirement: Test coverage for citation behavior

All stable citation display behavior MUST be covered by deterministic CI tests. Tests SHALL verify: remark plugin marker replacement (valid, out-of-range, empty citations), source icon mapping for all known types and the unknown-type fallback, CitationsBlock rendering (collapsed default, expand/collapse toggle, source types rendering correctly, click behavior per source type), and ImageLightbox open/close behavior. Tests SHALL NOT depend on network requests or non-deterministic timing.

#### Scenario: Remark plugin tests pass

- **WHEN** CI runs the remark-citations test suite
- **THEN** all tests for valid replacement, out-of-range markers, empty citations, and no-marker text SHALL pass

#### Scenario: Source icon mapping tests pass

- **WHEN** CI runs the source-icons test suite
- **THEN** all known source types SHALL map to their designated icon and color
- **AND** an unknown type SHALL map to the default

#### Scenario: CitationsBlock component tests pass

- **WHEN** CI runs the CitationsBlock test suite
- **THEN** tests SHALL verify: no render on empty citations, collapsed-by-default state, expand/collapse toggle, online source link rendering, offline source plain text rendering, and image source click callback

#### Scenario: ImageLightbox component tests pass

- **WHEN** CI runs the ImageLightbox test suite
- **THEN** tests SHALL verify: modal opens with image, closes via Escape, closes via click outside, and closes via X button
