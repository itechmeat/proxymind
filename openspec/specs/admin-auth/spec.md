## Purpose

Protect all admin endpoints with a single Bearer API key loaded from environment configuration, with secure defaults and operational visibility.

## ADDED Requirements

### Requirement: Admin API key authentication

All Admin API endpoints (`/api/admin/*`) SHALL require a valid API key provided via the `Authorization: Bearer <key>` header. The key is configured via the `ADMIN_API_KEY` environment variable.

#### Scenario: Valid API key

- **WHEN** a request to `/api/admin/*` includes `Authorization: Bearer <valid-key>`
- **THEN** the request SHALL be processed normally

#### Scenario: Missing API key

- **WHEN** a request to `/api/admin/*` does not include an Authorization header
- **THEN** the system SHALL respond with 401 Unauthorized
- **AND** the response SHALL include `WWW-Authenticate: Bearer` header
- **AND** the response body SHALL be `{"detail": "Invalid or missing API key"}`

#### Scenario: Invalid API key

- **WHEN** a request to `/api/admin/*` includes `Authorization: Bearer <wrong-key>`
- **THEN** the system SHALL respond with 401 Unauthorized
- **AND** the response body SHALL be `{"detail": "Invalid or missing API key"}`
- **AND** the response SHALL include `WWW-Authenticate: Bearer` header

### Requirement: Fail-safe when admin key is not configured

When the `ADMIN_API_KEY` environment variable is not set or empty, the Admin API SHALL be completely inaccessible.

#### Scenario: Key not configured

- **WHEN** `ADMIN_API_KEY` is not set in the environment
- **AND** a request is made to `/api/admin/*` with any Authorization header
- **THEN** the system SHALL respond with 503 Service Unavailable
- **AND** the response body SHALL be `{"detail": "Admin API key not configured"}`
- **AND** the response SHALL include `WWW-Authenticate: Bearer` header

#### Scenario: Application starts without admin key

- **WHEN** `ADMIN_API_KEY` is not set in the environment
- **AND** the application starts
- **THEN** the application SHALL start successfully
- **AND** Chat API and health endpoints SHALL function normally
- **AND** Admin API SHALL return 503 for all requests

### Requirement: Timing-safe key comparison

The API key comparison SHALL use `secrets.compare_digest()` to prevent timing attacks.

#### Scenario: Timing-safe validation

- **WHEN** an API key is validated against the configured key
- **THEN** the comparison SHALL use constant-time comparison (secrets.compare_digest)
- **AND** the response time SHALL NOT vary based on the number of matching characters

### Requirement: OpenAPI integration

The admin auth scheme SHALL be registered in the OpenAPI specification so that Swagger UI shows the lock icon and Authorize button.

#### Scenario: Swagger UI shows auth

- **WHEN** a developer opens the Swagger UI at /docs
- **THEN** admin endpoints SHALL display a lock icon
- **AND** an "Authorize" button SHALL be available to enter the Bearer token

### Requirement: Auth failure logging

Authentication failures SHALL be logged via structlog for operational visibility.

#### Scenario: Failed auth is logged

- **WHEN** an authentication attempt fails (401 or 503)
- **THEN** the system SHALL log a warning with the client IP and request path
- **AND** the API key value SHALL NOT be included in the log

### Requirement: Admin auth isolation from visitor identity

Admin authentication SHALL remain a separate concern from visitor identity, so that future channel connectors (S11-01) can add visitor identification without affecting admin auth.

#### Scenario: Independent auth systems

- **WHEN** admin auth is implemented
- **THEN** it SHALL NOT create user/visitor entities
- **AND** it SHALL NOT require changes to session or message models
- **AND** it SHALL be scoped exclusively to `/api/admin/*` routes
