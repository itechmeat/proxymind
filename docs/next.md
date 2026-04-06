# Future Ideas Backlog

Ideas and improvements to be converted into stories when prioritized.

---

## Security & Auth

- **Immediate token revocation via Redis blacklist** — Add Redis-based JWT blacklist for instant
  access token revocation (currently access tokens live up to 15 min after logout). Trivial to
  implement (~20 lines in auth dependency). Origin: S7-03 brainstorm, Decision D1 Option C.

- **OAuth / social login** — Google, GitHub, and other identity providers for end-user sign-in.
  Reduces friction for users who don't want to create a separate account.

- **Multi-factor authentication (MFA/2FA)** — TOTP-based second factor for end-user accounts.

- **Per-user rate limiting** — Rate limit by authenticated user_id instead of (or in addition to)
  IP address. Fairer for shared networks, better abuse prevention.

- **Account deletion / GDPR compliance** — Allow users to delete their account and all associated
  data (sessions, messages, profile).

## Infrastructure

_(empty — add ideas here)_

## UX

_(empty — add ideas here)_

## Knowledge & RAG

_(empty — add ideas here)_
