## MODIFIED Requirements

### Requirement: Admin routing with VITE_ADMIN_MODE guard

The application SHALL expose `/admin`, `/admin/sources`, `/admin/snapshots`, `/admin/catalog`, and `/admin/sign-in` routes. Navigating to `/admin` SHALL redirect to `/admin/sources` if the user is authenticated with a valid admin API key, or to `/admin/sign-in` if not. All `/admin/*` routes (except `/admin/sign-in`) SHALL be guarded by both the `VITE_ADMIN_MODE` environment flag and admin API key authentication. When `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset, navigating to any `/admin/*` route SHALL redirect the user to `/`. When admin mode is enabled but the user is not authenticated, navigating to any `/admin/*` route (except `/admin/sign-in`) SHALL redirect to `/admin/sign-in`. The admin sign-in page SHALL be a dedicated full-page form (not a modal dialog). The guard is UI-only and does not protect backend endpoints.

#### Scenario: Admin root redirects to sources tab when authenticated

- **WHEN** a user navigates to `/admin` and `VITE_ADMIN_MODE` is `"true"` and the user has a valid admin API key
- **THEN** the browser SHALL redirect to `/admin/sources`

#### Scenario: Admin routes redirect to sign-in when not authenticated

- **WHEN** `VITE_ADMIN_MODE` is `"true"` and the user does not have a valid admin API key
- **AND** the user navigates to `/admin`, `/admin/sources`, `/admin/snapshots`, or `/admin/catalog`
- **THEN** the user SHALL be redirected to `/admin/sign-in`

#### Scenario: Admin sign-in page is a dedicated page

- **WHEN** a user navigates to `/admin/sign-in`
- **THEN** the system SHALL render a full-page form for entering the admin API key
- **AND** the page SHALL NOT be a modal dialog overlay

#### Scenario: Successful admin sign-in redirects to sources

- **WHEN** the user submits a valid admin API key on `/admin/sign-in`
- **THEN** the browser SHALL redirect to `/admin/sources`

#### Scenario: Admin routes blocked when not admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **AND** the user navigates to `/admin`, `/admin/sources`, `/admin/snapshots`, or `/admin/sign-in`
- **THEN** the user SHALL be redirected to `/`
