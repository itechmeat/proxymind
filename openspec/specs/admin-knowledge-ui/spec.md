## Purpose

Frontend admin interface for knowledge management — source upload, source list with status tracking, snapshot lifecycle management, draft testing. Includes admin routing, layout, and access control via environment flag. Introduced by S5-03.

## ADDED Requirements

### Requirement: Admin routing with VITE_ADMIN_MODE guard

The application SHALL expose `/admin`, `/admin/sources`, and `/admin/snapshots` routes. Navigating to `/admin` SHALL redirect to `/admin/sources`. All `/admin/*` routes SHALL be guarded by the `VITE_ADMIN_MODE` environment flag. When `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset, navigating to any `/admin/*` route SHALL redirect the user to `/`. The guard is UI-only and does not protect backend endpoints.

#### Scenario: Admin root redirects to sources tab

- **WHEN** a user navigates to `/admin` and `VITE_ADMIN_MODE` is `"true"`
- **THEN** the browser SHALL redirect to `/admin/sources`

#### Scenario: Admin routes accessible in admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` equals `"true"`
- **AND** the user navigates to `/admin/sources` or `/admin/snapshots`
- **THEN** the corresponding tab content SHALL render

#### Scenario: Admin routes blocked when not admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **AND** the user navigates to `/admin`, `/admin/sources`, or `/admin/snapshots`
- **THEN** the user SHALL be redirected to `/`

---

### Requirement: Admin layout with header and top tabs navigation

The admin pages SHALL render inside an `AdminLayout` component that provides: (1) a header with a "Chat" back-link navigating to `/`, a "ProxyMind Admin" title, and twin identity display; (2) horizontal top tabs for "Sources" and "Snapshots" that link to `/admin/sources` and `/admin/snapshots` respectively; (3) a scrollable content area below the tabs rendering the active tab's route outlet. On mobile, tabs SHALL span full width (50/50 for two tabs).

#### Scenario: Admin header renders navigation elements

- **WHEN** the admin layout renders
- **THEN** it SHALL display a back-link to `/` (Chat), the title "ProxyMind Admin", and the twin identity

#### Scenario: Tab navigation between sources and snapshots

- **WHEN** the user clicks the "Sources" tab
- **THEN** the browser SHALL navigate to `/admin/sources` and the Sources tab content SHALL render

- **WHEN** the user clicks the "Snapshots" tab
- **THEN** the browser SHALL navigate to `/admin/snapshots` and the Snapshots tab content SHALL render

#### Scenario: Active tab visually indicated

- **WHEN** the user is on `/admin/sources`
- **THEN** the "Sources" tab SHALL have active styling (e.g., highlighted border or background)
- **AND** the "Snapshots" tab SHALL have inactive styling

#### Scenario: Mobile responsive tabs

- **WHEN** the viewport width is below the mobile breakpoint
- **THEN** the two tabs SHALL each occupy 50% of the available width

---

### Requirement: ChatHeader admin link

The ChatHeader component SHALL render an "Admin" link button that navigates to `/admin`. The link SHALL be visible only when `import.meta.env.VITE_ADMIN_MODE === "true"`. When `VITE_ADMIN_MODE` is not `"true"` or is unset, the Admin link SHALL NOT be rendered. The Admin link SHALL be separate from the existing Settings icon button.

#### Scenario: Admin link visible in admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` equals `"true"`
- **THEN** the ChatHeader SHALL render an Admin link button that navigates to `/admin`

#### Scenario: Admin link hidden when not admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **THEN** the ChatHeader SHALL NOT render the Admin link button

---

### Requirement: Sources tab with drag and drop upload zone

The Sources tab SHALL include a drag and drop upload zone at the top of the page. The drop zone SHALL display a dashed border, an icon, and instructional text. When files are dragged over the zone, it SHALL enter a highlighted visual state. The zone SHALL support multi-file upload: each dropped file SHALL trigger a separate `POST /api/admin/sources` request. On mobile, tapping the zone SHALL open the native file picker as a fallback. Upload metadata SHALL be auto-derived: `title` defaults to the filename without extension. No metadata modal SHALL be shown.

#### Scenario: Drop zone renders with instructional text

- **WHEN** the Sources tab renders
- **THEN** a drop zone with dashed border, icon, and instructional text SHALL be displayed

#### Scenario: Visual highlight on drag over

- **WHEN** files are dragged over the drop zone
- **THEN** the zone SHALL enter a highlighted visual state (e.g., changed border color/style)

- **WHEN** the drag leaves the zone without dropping
- **THEN** the zone SHALL return to its default visual state

#### Scenario: Multi-file upload triggers separate requests

- **WHEN** the user drops 3 files onto the zone
- **THEN** 3 separate `POST /api/admin/sources` requests SHALL be sent, one per file
- **AND** each request SHALL use the filename (without extension) as the `title` in metadata

#### Scenario: Mobile tap opens file picker

- **WHEN** the user taps the drop zone on a mobile device
- **THEN** the native file picker SHALL open to allow file selection

---

### Requirement: Client-side file validation

Before sending an upload request, the client SHALL validate each file. Allowed extensions SHALL be: `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.mp3`, `.wav`, `.mp4`. Files with unsupported extensions SHALL be rejected with an error toast before any network request. Empty (zero-byte) files SHALL be rejected with an error toast. Extension validation SHALL be case-insensitive.

#### Scenario: Unsupported file extension rejected

- **WHEN** the user drops a file with extension `.xlsx`
- **THEN** the upload SHALL NOT be sent
- **AND** an error toast SHALL display indicating the file type is unsupported

#### Scenario: Empty file rejected

- **WHEN** the user drops a zero-byte file
- **THEN** the upload SHALL NOT be sent
- **AND** an error toast SHALL display indicating the file is empty

#### Scenario: Allowed extension accepted

- **WHEN** the user drops a file with extension `.pdf`
- **THEN** the client-side validation SHALL pass and the upload request SHALL be sent

#### Scenario: Case-insensitive extension validation

- **WHEN** the user drops a file named `REPORT.PDF`
- **THEN** the client-side validation SHALL accept it as a valid PDF file

---

### Requirement: Source list with status badges and polling

The Sources tab SHALL display a list of sources below the upload zone. On desktop, the list SHALL render as a table with columns: title, type (icon), status (badge), and actions (delete button). On mobile, the list SHALL render as a card stack with each card showing title, type badge, status badge, and delete button. Sources SHALL be sorted by `created_at` descending (newest first). Status badges SHALL use the following colors: PENDING = yellow, PROCESSING = blue with animated pulse/spinner, READY = green, FAILED = red.

The list SHALL poll for updates: on mount, it SHALL fetch sources; when any source has status PENDING or PROCESSING, it SHALL start polling every 3 seconds; when all visible sources are READY or FAILED, polling SHALL stop. After a successful upload, it SHALL re-fetch immediately and start polling. After a successful delete, it SHALL re-fetch immediately. On unmount, polling intervals SHALL be cleaned up.

#### Scenario: Source list renders as table on desktop

- **WHEN** the Sources tab renders on a desktop viewport
- **THEN** sources SHALL be displayed in a table with title, type, status, and actions columns

#### Scenario: Source list renders as cards on mobile

- **WHEN** the Sources tab renders on a mobile viewport
- **THEN** sources SHALL be displayed as a card stack

#### Scenario: Status badge colors

- **WHEN** a source has status PENDING
- **THEN** its badge SHALL be yellow

- **WHEN** a source has status PROCESSING
- **THEN** its badge SHALL be blue with an animated pulse or spinner

- **WHEN** a source has status READY
- **THEN** its badge SHALL be green

- **WHEN** a source has status FAILED
- **THEN** its badge SHALL be red

#### Scenario: Polling starts when sources are processing

- **WHEN** the source list contains at least one source with status PENDING or PROCESSING
- **THEN** the list SHALL poll `GET /api/admin/sources` every 3 seconds

#### Scenario: Polling stops when all sources are terminal

- **WHEN** all visible sources have status READY or FAILED
- **THEN** the polling interval SHALL be stopped

#### Scenario: Re-fetch after upload

- **WHEN** a file upload completes successfully
- **THEN** the source list SHALL re-fetch immediately
- **AND** polling SHALL start if the new source has status PENDING or PROCESSING

#### Scenario: Cleanup on unmount

- **WHEN** the Sources tab component unmounts
- **THEN** all active polling intervals SHALL be cleaned up

---

### Requirement: Soft delete with AlertDialog confirmation

Each source in the list SHALL have a delete button. Clicking the delete button SHALL open an AlertDialog with the confirmation message: `Delete source {title}? Chunks in published snapshots will remain until replaced.` Confirming the dialog SHALL send a `DELETE /api/admin/sources/{id}` request. On success, the source SHALL be removed from the rendered list (the backend excludes DELETED sources). Backend warnings (e.g., source referenced in a published snapshot) SHALL be shown in a toast notification.

#### Scenario: Delete button opens confirmation dialog

- **WHEN** the user clicks the delete button on a source
- **THEN** an AlertDialog SHALL open with a confirmation message containing the source title

#### Scenario: Confirm delete sends request

- **WHEN** the user confirms the delete in the AlertDialog
- **THEN** a `DELETE /api/admin/sources/{id}` request SHALL be sent
- **AND** on success, the source SHALL be removed from the list

#### Scenario: Cancel delete closes dialog

- **WHEN** the user cancels the delete in the AlertDialog
- **THEN** the dialog SHALL close and no delete request SHALL be sent

#### Scenario: Backend warning shown as toast

- **WHEN** the delete response includes a warning message
- **THEN** the warning SHALL be displayed in a toast notification

---

### Requirement: Snapshots tab with card layout

The Snapshots tab SHALL display snapshots in a card layout. Each card SHALL show: snapshot name, status badge (colored), chunk count, relevant timestamps (created, published, activated as applicable), and action buttons based on status. Cards SHALL be sorted by status priority: ACTIVE first, then DRAFT, then PUBLISHED (newest first within each group). Status badge colors SHALL be: ACTIVE = green, DRAFT = yellow, PUBLISHED = blue, ARCHIVED = gray. ARCHIVED snapshots SHALL be hidden by default; a `Show archived` toggle at the bottom SHALL reveal them.

#### Scenario: Snapshot cards sorted by status priority

- **WHEN** the Snapshots tab renders with snapshots of various statuses
- **THEN** ACTIVE snapshots SHALL appear first, then DRAFT, then PUBLISHED

#### Scenario: Status badge colors on snapshot cards

- **WHEN** a snapshot has status ACTIVE
- **THEN** its badge SHALL be green

- **WHEN** a snapshot has status DRAFT
- **THEN** its badge SHALL be yellow

- **WHEN** a snapshot has status PUBLISHED
- **THEN** its badge SHALL be blue

- **WHEN** a snapshot has status ARCHIVED
- **THEN** its badge SHALL be gray

#### Scenario: Archived snapshots hidden by default

- **WHEN** the Snapshots tab renders and ARCHIVED snapshots exist
- **THEN** ARCHIVED snapshots SHALL NOT be visible

#### Scenario: Show archived toggle reveals archived snapshots

- **WHEN** the user activates the `Show archived` toggle
- **THEN** ARCHIVED snapshot cards SHALL become visible

#### Scenario: Card displays chunk count and timestamps

- **WHEN** a snapshot card renders
- **THEN** it SHALL display the snapshot name, chunk count, and relevant timestamps

---

### Requirement: Create draft button

The Snapshots tab SHALL display a `+ New Draft` button at the top of the snapshot list. Clicking the button SHALL send a `POST /api/admin/snapshots` request and add the returned snapshot to the list. The button SHALL be disabled when a DRAFT snapshot already exists in the current list. When disabled, a tooltip SHALL display: `A draft already exists`.

#### Scenario: Create draft button sends request

- **WHEN** no DRAFT snapshot exists and the user clicks `+ New Draft`
- **THEN** a `POST /api/admin/snapshots` request SHALL be sent
- **AND** the returned snapshot SHALL appear in the list

#### Scenario: Create draft button disabled when draft exists

- **WHEN** a DRAFT snapshot already exists in the list
- **THEN** the `+ New Draft` button SHALL be disabled
- **AND** hovering over it SHALL show a tooltip: `A draft already exists`

---

### Requirement: Snapshot actions by status

Snapshot cards SHALL display action buttons based on their status. DRAFT cards SHALL show: `Test`, `Publish`, and `Publish & Activate` buttons. PUBLISHED cards SHALL show an `Activate` button. ACTIVE cards SHALL show a `Rollback` button. ARCHIVED cards SHALL show no action buttons.

#### Scenario: DRAFT card actions

- **WHEN** a snapshot card has status DRAFT
- **THEN** it SHALL display `Test`, `Publish`, and `Publish & Activate` buttons

#### Scenario: PUBLISHED card actions

- **WHEN** a snapshot card has status PUBLISHED
- **THEN** it SHALL display an `Activate` button

#### Scenario: ACTIVE card actions

- **WHEN** a snapshot card has status ACTIVE
- **THEN** it SHALL display a `Rollback` button

#### Scenario: ARCHIVED card has no actions

- **WHEN** a snapshot card has status ARCHIVED
- **THEN** no action buttons SHALL be displayed

---

### Requirement: Publish and activate actions with confirmations

The `Publish` button SHALL open an AlertDialog confirmation before sending `POST /api/admin/snapshots/{id}/publish`. The `Publish & Activate` button SHALL open an AlertDialog confirmation before sending `POST /api/admin/snapshots/{id}/publish?activate=true`. The `Activate` button on a PUBLISHED card SHALL send `POST /api/admin/snapshots/{id}/activate`. Backend validation errors (no indexed chunks, failed chunks, pending chunks) SHALL be displayed as error toasts with details. On success, the snapshot list SHALL be re-fetched.

#### Scenario: Publish with confirmation

- **WHEN** the user clicks `Publish` on a DRAFT card
- **THEN** an AlertDialog SHALL open asking for confirmation
- **AND** confirming SHALL send `POST /api/admin/snapshots/{id}/publish`
- **AND** on success, the list SHALL re-fetch and a success toast SHALL display

#### Scenario: Publish and activate with confirmation

- **WHEN** the user clicks `Publish & Activate` on a DRAFT card
- **THEN** an AlertDialog SHALL open asking for confirmation
- **AND** confirming SHALL send `POST /api/admin/snapshots/{id}/publish?activate=true`
- **AND** on success, the list SHALL re-fetch and a success toast SHALL display

#### Scenario: Activate published snapshot

- **WHEN** the user clicks `Activate` on a PUBLISHED card
- **THEN** a `POST /api/admin/snapshots/{id}/activate` request SHALL be sent
- **AND** on success, the list SHALL re-fetch and a success toast SHALL display

#### Scenario: Backend validation error shown as toast

- **WHEN** a publish or activate request fails with a 422 status (e.g., no indexed chunks)
- **THEN** an error toast SHALL display with the validation error details from the backend response

---

### Requirement: Rollback action with confirmation

The `Rollback` button on an ACTIVE snapshot card SHALL open an AlertDialog with the message: `Roll back to previous published snapshot {name}?` Confirming SHALL send `POST /api/admin/snapshots/{id}/rollback`. The response contains `rolled_back_from` and `rolled_back_to` objects (each with `id`, `name`, `status`). On success, a toast SHALL display: `Rolled back to {rolled_back_to.name}` and the snapshot list SHALL re-fetch.

#### Scenario: Rollback opens confirmation dialog

- **WHEN** the user clicks `Rollback` on an ACTIVE snapshot card
- **THEN** an AlertDialog SHALL open with a rollback confirmation message

#### Scenario: Rollback success

- **WHEN** the user confirms the rollback
- **THEN** a `POST /api/admin/snapshots/{id}/rollback` request SHALL be sent
- **AND** on success, a toast SHALL display `Rolled back to {rolled_back_to.name}`
- **AND** the snapshot list SHALL re-fetch

#### Scenario: Rollback failure

- **WHEN** the rollback request fails (e.g., 409 conflict)
- **THEN** an error toast SHALL display with the backend error message
- **AND** the snapshot list SHALL re-fetch to reflect the current state

---

### Requirement: Inline draft test panel

The `Test` button on a DRAFT snapshot card SHALL expand an inline panel below the card. The panel SHALL contain: a text input for the search query, a mode selector (Hybrid, Dense, Sparse) with Hybrid as the default, and a `Search` button. On desktop, the mode selector SHALL render as radio buttons. On mobile, it SHALL render as a dropdown. Clicking `Search` SHALL send `POST /api/admin/snapshots/{id}/test` with `{ query, top_n: 5, mode }`. Results SHALL display as a list showing: source title, score, anchor metadata (`page`, `chapter`, `section`, `timecode`), and a text preview (first 500 characters).

#### Scenario: Test button expands inline panel

- **WHEN** the user clicks `Test` on a DRAFT card
- **THEN** an inline panel SHALL expand below the card with query input, mode selector, and search button

#### Scenario: Test button collapses panel on second click

- **WHEN** the user clicks `Test` again while the panel is expanded
- **THEN** the panel SHALL collapse

#### Scenario: Default search mode is Hybrid

- **WHEN** the test panel opens
- **THEN** the mode selector SHALL default to `Hybrid`

#### Scenario: Search sends test request

- **WHEN** the user enters a query and clicks `Search`
- **THEN** a `POST /api/admin/snapshots/{id}/test` request SHALL be sent with `{ query, top_n: 5, mode }`

#### Scenario: Search results displayed

- **WHEN** the test request returns results
- **THEN** each result SHALL display: source title, score, anchor metadata, and text preview (first 500 characters)

#### Scenario: Mode selector responsive rendering

- **WHEN** the test panel renders on a desktop viewport
- **THEN** the mode selector SHALL render as radio buttons

- **WHEN** the test panel renders on a mobile viewport
- **THEN** the mode selector SHALL render as a dropdown

---

### Requirement: Toast notifications

The admin UI SHALL use toast notifications for success and error feedback. Toast types SHALL be: success (green), error (red), warning (yellow), info (blue). Toasts SHALL auto-dismiss after 5 seconds and SHALL be manually closable. Toasts SHALL be lightweight and SHALL NOT require a heavy external library.

#### Scenario: Success toast displayed after action

- **WHEN** an admin action (upload, delete, publish, activate, rollback) succeeds
- **THEN** a success toast SHALL display with a confirmation message

#### Scenario: Error toast displayed on failure

- **WHEN** an admin action fails
- **THEN** an error toast SHALL display with the error details

#### Scenario: Toast auto-dismisses

- **WHEN** a toast is displayed
- **THEN** it SHALL auto-dismiss after 5 seconds

#### Scenario: Toast manually closable

- **WHEN** a toast is displayed and the user clicks the close button
- **THEN** the toast SHALL dismiss immediately

---

### Requirement: Error handling for admin API calls

Admin API calls SHALL handle errors according to the following mapping: network errors SHALL show a toast `Connection error. Retrying...` with auto-retry after 5 seconds; 404 responses SHALL show a toast `Not found` and remove the entity from local state; 409 responses SHALL show a toast with the backend message and re-fetch the list; 422 responses SHALL show a toast with error details from the backend; 413 responses SHALL show a toast `File exceeds server size limit`; 500 responses SHALL show a toast `Server error` with the error message if available.

#### Scenario: Network error with retry

- **WHEN** a fetch request fails due to a network error
- **THEN** an error toast SHALL display `Connection error. Retrying...`
- **AND** the request SHALL be retried after 5 seconds

#### Scenario: 404 removes entity from state

- **WHEN** a request returns 404
- **THEN** a toast SHALL display `Not found`
- **AND** the entity SHALL be removed from the local state

#### Scenario: 409 conflict triggers re-fetch

- **WHEN** a request returns 409
- **THEN** a toast SHALL display the backend error message
- **AND** the list SHALL be re-fetched

#### Scenario: 422 validation error

- **WHEN** a request returns 422
- **THEN** a toast SHALL display the validation error details from the response

#### Scenario: 413 file too large

- **WHEN** an upload request returns 413
- **THEN** a toast SHALL display `File exceeds server size limit`

#### Scenario: 500 server error

- **WHEN** a request returns 500
- **THEN** a toast SHALL display `Server error` with additional details if available

---

### Requirement: Responsive layout

The admin UI SHALL be responsive. On desktop, the source list SHALL render as a table; on mobile, it SHALL render as a card stack. Tabs SHALL span full width on mobile (50/50 for two tabs). The draft test mode selector SHALL render as radio buttons on desktop and a dropdown on mobile. Snapshot cards SHALL adapt to the available width.

#### Scenario: Table to cards on mobile

- **WHEN** the viewport width is below the mobile breakpoint
- **THEN** the source list SHALL render as cards instead of a table

#### Scenario: Desktop table layout

- **WHEN** the viewport width is above the mobile breakpoint
- **THEN** the source list SHALL render as a table with columns

---

### Requirement: Test coverage for admin UI

All stable admin UI behavior MUST be covered by deterministic CI tests. Tests SHALL cover: admin routing with mode guard (redirect when disabled, access when enabled), source list rendering with status badges, source polling lifecycle (start on PENDING/PROCESSING, stop on terminal), drag and drop upload with file validation, soft delete with confirmation dialog, snapshot card rendering with status-dependent actions, snapshot lifecycle actions (create draft, publish, activate, rollback), and draft test search flow. Tests SHALL use mocked API responses and SHALL NOT depend on real backend services.

#### Scenario: Routing guard tests pass

- **WHEN** CI runs the admin routing test suite
- **THEN** tests SHALL verify: redirect to `/` when `VITE_ADMIN_MODE` is not `"true"`, access granted when `VITE_ADMIN_MODE` is `"true"`, `/admin` redirects to `/admin/sources`

#### Scenario: Source list tests pass

- **WHEN** CI runs the source list test suite
- **THEN** tests SHALL verify: rendering with correct status badge colors, polling starts for PENDING/PROCESSING sources, polling stops for terminal sources, delete confirmation dialog flow

#### Scenario: Upload tests pass

- **WHEN** CI runs the upload test suite
- **THEN** tests SHALL verify: file validation (allowed/rejected extensions, empty files), multi-file upload triggers separate requests, metadata auto-derivation from filename

#### Scenario: Snapshot tests pass

- **WHEN** CI runs the snapshot test suite
- **THEN** tests SHALL verify: card rendering with status-dependent actions, create draft disabled when draft exists, publish/activate/rollback action flows with confirmation dialogs, draft test panel expand/collapse and search flow
