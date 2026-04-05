## MODIFIED Requirements

### Requirement: Session persistence via localStorage

The system SHALL persist the current session ID in `localStorage` under the key `proxymind_session_id`. On page load, if a session ID exists in localStorage, the system SHALL attempt to restore the session by calling `GET /api/chat/sessions/:id` with the current user's access token. If the backend returns 200, the session messages SHALL be loaded as initial chat history. If the backend returns 404 (session expired or invalid) or 403 (session belongs to a different user), the system SHALL create a new session via `POST /api/chat/sessions` and update localStorage. On user sign-out, the system SHALL clear `proxymind_session_id` from localStorage. On user sign-in, the system SHALL NOT restore a previous session — it SHALL create a new session for the authenticated user.

#### Scenario: Session restored from localStorage

- **WHEN** the page loads and `localStorage` contains a valid `proxymind_session_id`
- **AND** the backend returns 200 for `GET /api/chat/sessions/:id`
- **THEN** the chat SHALL render with the restored message history

#### Scenario: Expired session creates new session

- **WHEN** the page loads and `localStorage` contains a `proxymind_session_id`
- **AND** the backend returns 404 for that session
- **THEN** the system SHALL create a new session via `POST /api/chat/sessions`
- **AND** localStorage SHALL be updated with the new session ID

#### Scenario: Foreign session creates new session

- **WHEN** the page loads and `localStorage` contains a `proxymind_session_id`
- **AND** the backend returns 403 (session belongs to a different user)
- **THEN** the system SHALL create a new session via `POST /api/chat/sessions`
- **AND** localStorage SHALL be updated with the new session ID

#### Scenario: First visit creates new session

- **WHEN** the page loads and `localStorage` does not contain `proxymind_session_id`
- **THEN** the system SHALL create a new session via `POST /api/chat/sessions`
- **AND** the new session ID SHALL be saved to localStorage

#### Scenario: Sign-out clears session

- **WHEN** the user signs out
- **THEN** `proxymind_session_id` SHALL be removed from localStorage

#### Scenario: Sign-in starts fresh session

- **WHEN** a user signs in (regardless of whether localStorage contains a previous session ID)
- **THEN** the system SHALL create a new session for the authenticated user
- **AND** localStorage SHALL be updated with the new session ID

---

## ADDED Requirements

### Requirement: Chat route requires authentication

The chat page at `/` SHALL be wrapped in a `ProtectedRoute` component. If the user is not authenticated (no valid access token and silent refresh fails), the system SHALL redirect to `/auth/sign-in`. While the authentication state is loading (silent refresh in progress), the system SHALL display a loading indicator instead of the chat UI.

#### Scenario: Authenticated user sees chat

- **WHEN** an authenticated user navigates to `/`
- **THEN** the chat page SHALL render normally

#### Scenario: Unauthenticated user redirected to sign-in

- **WHEN** an unauthenticated user navigates to `/`
- **AND** silent refresh fails (no valid refresh token cookie)
- **THEN** the user SHALL be redirected to `/auth/sign-in`

#### Scenario: Loading state during silent refresh

- **WHEN** a user navigates to `/` and the silent refresh is in progress
- **THEN** the system SHALL display a loading indicator
- **AND** the chat UI SHALL NOT render until authentication resolves
