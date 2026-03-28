## MODIFIED Requirements

### Requirement: Rate limit logging

**[Modified by S7-02]** Rate limit events SHALL be logged for operational visibility. Additionally, when a request is rejected due to rate limiting, the Prometheus metric `rate_limit_hits_total` SHALL be incremented via the code constant `RATE_LIMIT_HITS_TOTAL`.

#### Scenario: Rate limit exceeded logging

- **WHEN** a request is rejected due to rate limiting
- **THEN** the system SHALL log a warning with the client IP, request path, weighted count, and configured limit

#### Scenario: Rate limit Prometheus counter incremented on rejection

- **WHEN** a request is rejected due to rate limiting (429 response)
- **THEN** `RATE_LIMIT_HITS_TOTAL.inc()` SHALL be called
- **AND** the counter increment SHALL happen after the structlog warning is emitted

#### Scenario: Counter not incremented for allowed requests

- **WHEN** a request to `/api/chat/*` is allowed (under rate limit)
- **THEN** `RATE_LIMIT_HITS_TOTAL` SHALL NOT be incremented

#### Scenario: Counter import is resilient

- **WHEN** the `app.services.metrics` module is not available (e.g., in isolated tests)
- **THEN** the rate limiter SHALL still function correctly
- **AND** the missing import SHALL be handled gracefully (try/except or lazy import)

---

## Test Coverage

### CI tests (deterministic)

- **Rate limit counter test**: trigger a rate limit rejection, verify `RATE_LIMIT_HITS_TOTAL` counter is incremented.
- **Rate limit allowed test**: send a request under the limit, verify the counter is NOT incremented.
- **Existing rate limit tests pass**: verify all pre-existing `test_rate_limit.py` tests still pass with the metrics import added.
