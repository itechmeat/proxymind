## Purpose

Frontend test infrastructure — Vitest + React Testing Library setup, test organization, required test suites, CI-compatible scripts. Introduced by S5-01.

## ADDED Requirements

### Requirement: Vitest test runner with happy-dom

The frontend test runner SHALL be Vitest configured with the `happy-dom` environment. The Vitest configuration SHALL be defined either in a standalone `vitest.config.ts` or as a `test` block in `vite.config.ts`. The environment SHALL provide a lightweight DOM implementation sufficient for React component rendering without a real browser.

#### Scenario: Vitest uses happy-dom environment

- **WHEN** a test file is executed by Vitest
- **THEN** the test environment SHALL be `happy-dom`
- **AND** DOM APIs (document, window, etc.) SHALL be available in the test context

#### Scenario: Vitest config is valid

- **WHEN** Vitest is initialized
- **THEN** the configuration SHALL specify `environment: "happy-dom"` and include any necessary setup files

---

### Requirement: React Testing Library with jest-dom matchers

The test setup SHALL include `@testing-library/react` for component rendering and querying, `@testing-library/jest-dom` for DOM assertion matchers (e.g., `toBeInTheDocument`, `toBeDisabled`, `toHaveTextContent`), and `@testing-library/user-event` for simulating user interactions (typing, clicking, keyboard events). A setup file SHALL import `@testing-library/jest-dom/vitest` to register the custom matchers globally.

#### Scenario: jest-dom matchers available in tests

- **WHEN** a test uses `expect(element).toBeInTheDocument()`
- **THEN** the assertion SHALL work without per-file imports of jest-dom

#### Scenario: user-event simulates interactions

- **WHEN** a test calls `userEvent.type(input, "hello")`
- **THEN** the input element SHALL receive the typed characters as if a real user typed them

---

### Requirement: Test file organization

Test files SHALL be organized in `src/tests/` with a structure mirroring the source tree. Unit tests for `lib/` modules SHALL be in `src/tests/lib/`. Component tests SHALL be in `src/tests/components/`. Integration tests SHALL be in `src/tests/integration/`. Test files SHALL use the `.test.ts` or `.test.tsx` extension.

#### Scenario: Test files mirror source structure

- **WHEN** a test is written for `src/lib/sse-parser.ts`
- **THEN** the test file SHALL be located at `src/tests/lib/sse-parser.test.ts`

#### Scenario: Component test location

- **WHEN** a test is written for the `ChatInput` component
- **THEN** the test file SHALL be located at `src/tests/components/ChatInput.test.tsx`

---

### Requirement: Unit tests for library modules

The following library modules SHALL have unit tests covering their core behavior:

- **`sse-parser.ts`**: Parsing complete events, partial chunk buffering, heartbeat skipping, malformed data handling, all five event types.
- **`api.ts`** (API client): Session creation request, session retrieval request, error response handling.
- **`message-adapter.ts`**: Conversion of all message statuses (complete, received, partial, failed), citation preservation, user vs assistant role mapping.
- **`transport.ts`**: SSE event-to-UI-state mapping (meta, token, citations, done, error), idempotency key generation, HTTP error handling (409, 422, network failure).
- **`useSession` hook**: First visit creates session, localStorage restore, 404 triggers new session creation, session ID persisted to localStorage.

#### Scenario: SSE parser unit tests

- **WHEN** the SSE parser test suite runs
- **THEN** tests SHALL verify: parsing a complete event, buffering across chunk boundaries, skipping heartbeats, handling invalid JSON in data lines, yielding all five event types with correct payloads

#### Scenario: API client unit tests

- **WHEN** the API client test suite runs
- **THEN** tests SHALL verify: `POST /api/chat/sessions` creates a session, `GET /api/chat/sessions/:id` retrieves a session, HTTP error responses are properly propagated

#### Scenario: Message adapter unit tests

- **WHEN** the message adapter test suite runs
- **THEN** tests SHALL verify: complete messages map correctly, "received" status maps to complete, partial status preserves content with indicator, failed status maps to error state, citations stored as metadata, user messages map correctly

#### Scenario: Transport unit tests

- **WHEN** the transport test suite runs with mocked fetch
- **THEN** tests SHALL verify: meta event stores metadata, token event produces text delta, citations event invokes callback, done event signals completion, error event signals error, HTTP 409 surfaces error, HTTP 422 surfaces error, network failure surfaces error, each send uses a unique idempotency key

#### Scenario: useSession hook unit tests

- **WHEN** the useSession hook test suite runs
- **THEN** tests SHALL verify: new session created when localStorage is empty, session restored from localStorage on valid 200, new session created on 404, session ID written to localStorage after creation

---

### Requirement: Component tests

The following components SHALL have tests verifying their rendering and interaction behavior:

- **`ChatHeader`**: Renders twin name, renders avatar from URL, renders initials fallback when no URL.
- **`MessageBubble`**: Renders user message (right-aligned, plain text), renders assistant message (left-aligned, Markdown), shows streaming indicator during streaming status, shows retry button on failed status, shows incomplete indicator on partial status.
- **`ChatInput`**: Enter key sends message, Shift+Enter inserts newline, empty input disables send button, input disabled during streaming/submitted states, textarea auto-resizes.
- **`MessageList`**: Renders a list of messages, renders empty state when no messages, scroll container is present.

#### Scenario: ChatHeader component tests

- **WHEN** the ChatHeader test suite runs
- **THEN** tests SHALL verify: twin name is displayed, avatar image renders when URL is provided, initials render when URL is absent

#### Scenario: MessageBubble component tests

- **WHEN** the MessageBubble test suite runs
- **THEN** tests SHALL verify: user message is right-aligned with plain text, assistant message renders Markdown as HTML, streaming indicator appears for streaming status, retry button appears for failed status, incomplete indicator appears for partial status

#### Scenario: ChatInput component tests

- **WHEN** the ChatInput test suite runs
- **THEN** tests SHALL verify: Enter sends the message and clears input, Shift+Enter inserts a newline without sending, send button is disabled when input is empty, textarea and send button are disabled when status is "submitted" or "streaming"

#### Scenario: MessageList component tests

- **WHEN** the MessageList test suite runs
- **THEN** tests SHALL verify: multiple messages render in order, empty state renders when messages array is empty, a scroll container element is present

---

### Requirement: Integration tests

An integration test for the `ChatPage` SHALL verify the full send-stream-render flow with a mocked transport. Additional integration tests SHALL cover history restoration and error handling.

- **Full flow**: Render ChatPage → type message → send → verify streaming tokens render incrementally → verify final complete message.
- **History restoration**: Render ChatPage with mocked session containing existing messages → verify all messages appear.
- **Error handling (422)**: Render ChatPage → send message → mock 422 response → verify "knowledge not ready" error is displayed.

#### Scenario: ChatPage full flow integration test

- **WHEN** the ChatPage integration test runs
- **THEN** the test SHALL: render the ChatPage with a mocked transport, simulate typing a message, simulate sending, verify streaming tokens appear incrementally in the assistant bubble, verify the final complete message is displayed after the stream ends

#### Scenario: History restoration integration test

- **WHEN** the history restoration integration test runs
- **THEN** the test SHALL: mock a session with 4 messages (2 user, 2 assistant), render the ChatPage, verify all 4 messages are displayed in correct order

#### Scenario: Error 422 integration test

- **WHEN** the 422 error integration test runs
- **THEN** the test SHALL: render the ChatPage, simulate sending a message, mock a 422 HTTP response, verify a "knowledge not ready" error message is displayed to the user

---

### Requirement: CI compatibility

All frontend tests SHALL be deterministic and SHALL NOT depend on external services (no real backend, no network calls, no real LLM). Tests SHALL mock all HTTP interactions via `fetch` mocks or transport mocks. Running `bun run test` SHALL execute the full test suite and exit with code 0 on success, non-zero on failure.

#### Scenario: Tests are deterministic

- **WHEN** the full test suite is run twice consecutively
- **THEN** both runs SHALL produce identical pass/fail results

#### Scenario: No external dependencies

- **WHEN** the test suite runs in a CI environment with no network access to backend services
- **THEN** all tests SHALL pass

#### Scenario: Exit code on success

- **WHEN** `bun run test` completes and all tests pass
- **THEN** the process SHALL exit with code 0

#### Scenario: Exit code on failure

- **WHEN** `bun run test` completes and at least one test fails
- **THEN** the process SHALL exit with a non-zero code

---

### Requirement: Test scripts in package.json

The frontend `package.json` SHALL include the following scripts:

- `"test"`: Runs the full Vitest test suite in single-run mode (not watch mode). This is the script used by CI.
- `"test:watch"`: Runs Vitest in watch mode for local development.

#### Scenario: test script runs full suite

- **WHEN** `bun run test` is executed
- **THEN** Vitest SHALL run all test files matching the configured pattern and exit after completion

#### Scenario: test:watch script runs in watch mode

- **WHEN** `bun run test:watch` is executed
- **THEN** Vitest SHALL start in watch mode, re-running tests on file changes

---

### Requirement: Stable behavior coverage before archive

Per Phase 5 requirements, all stable implemented behavior MUST be covered by tests before the S5-01 change is archived. If test coverage is missing or weak after implementation, additional tests MUST be proposed and added. The following areas are considered stable behavior that MUST have coverage:

- SSE parsing (all event types, edge cases)
- Message adapter (all status mappings)
- Transport (event mapping, error handling)
- Session hook (create, restore, fallback)
- ChatInput (keyboard behavior, disabled states)
- MessageBubble (all visual states)
- ChatPage integration (send-stream-render flow)

#### Scenario: Coverage audit before archive

- **WHEN** the S5-01 change is ready for archive
- **THEN** a review SHALL confirm that every stable behavior area listed above has at least one passing test
- **AND** any coverage gap SHALL be documented or filled before archive proceeds
