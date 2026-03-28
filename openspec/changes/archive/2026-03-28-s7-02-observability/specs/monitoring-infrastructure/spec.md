## ADDED Requirements

### Requirement: Prometheus Docker Compose service

Docker Compose SHALL define a `prometheus` service using image `prom/prometheus:v3.10.0`. The service SHALL expose port `9090`. The service SHALL mount `monitoring/prometheus/prometheus.yml` as a read-only volume at `/etc/prometheus/prometheus.yml`. The service SHALL use a named volume `prometheus-data` for data persistence.

#### Scenario: Prometheus service starts and scrapes API

- **WHEN** `docker compose up` is executed
- **THEN** the `prometheus` service SHALL start and begin scraping the `api:8000/metrics` endpoint
- **AND** Prometheus SHALL be accessible at `http://localhost:9090`

#### Scenario: Prometheus configuration is valid

- **WHEN** `monitoring/prometheus/prometheus.yml` is inspected
- **THEN** it SHALL contain a `scrape_configs` entry with `job_name: "proxymind-api"`, `targets: ["api:8000"]`, and `metrics_path: /metrics`
- **AND** `scrape_interval` SHALL be `15s`

---

### Requirement: Grafana Docker Compose service

Docker Compose SHALL define a `grafana` service using image `grafana/grafana:12.4.1`. The service SHALL expose port `3000`. The service SHALL mount provisioning files and dashboards:

- `monitoring/grafana/provisioning/datasources/datasources.yml` at `/etc/grafana/provisioning/datasources/datasources.yml`
- `monitoring/grafana/provisioning/dashboards/dashboards.yml` at `/etc/grafana/provisioning/dashboards/dashboards.yml`
- `monitoring/grafana/dashboards/` directory at `/var/lib/grafana/dashboards/`

The service SHALL use a named volume `grafana-data` for data persistence. The service SHALL depend on `prometheus` and `tempo`.

#### Scenario: Grafana starts with provisioned datasources

- **WHEN** `docker compose up` is executed
- **THEN** the `grafana` service SHALL start with pre-configured Prometheus and Tempo data sources
- **AND** Grafana SHALL be accessible at `http://localhost:3000`

#### Scenario: Grafana datasources configuration

- **WHEN** `monitoring/grafana/provisioning/datasources/datasources.yml` is inspected
- **THEN** it SHALL define two data sources:
  - Prometheus: `type: prometheus`, `url: http://prometheus:9090`, `isDefault: true`
  - Tempo: `type: tempo`, `url: http://tempo:3200`

#### Scenario: Grafana dashboard provisioning

- **WHEN** `monitoring/grafana/provisioning/dashboards/dashboards.yml` is inspected
- **THEN** it SHALL define a file-based dashboard provider pointing to `/var/lib/grafana/dashboards`
- **AND** the provider folder SHALL be named `ProxyMind`

---

### Requirement: Tempo Docker Compose service

Docker Compose SHALL define a `tempo` service using image `grafana/tempo:2.10.3`. The service SHALL expose port `3200` (HTTP API) to the host and keep port `4317` (OTLP gRPC receiver) internal to the Compose network. Tempo SHALL run in monolithic mode with local disk storage. The service SHALL mount `monitoring/tempo/tempo.yml` as a read-only volume. The service SHALL use a named volume `tempo-data` for trace storage.

#### Scenario: Tempo service starts and accepts traces

- **WHEN** `docker compose up` is executed
- **THEN** the `tempo` service SHALL start and accept OTLP gRPC traces on port 4317
- **AND** the Tempo HTTP API SHALL be accessible at port 3200

#### Scenario: Tempo configuration is valid

- **WHEN** `monitoring/tempo/tempo.yml` is inspected
- **THEN** it SHALL configure:
  - `server.http_listen_port: 3200`
  - OTLP gRPC receiver on `0.0.0.0:4317`
  - Local storage backend at `/var/tempo/traces`
  - WAL at `/var/tempo/wal`

---

### Requirement: Provisioned Grafana dashboard (Set A metrics)

A Grafana dashboard JSON file SHALL be created at `monitoring/grafana/dashboards/proxymind-overview.json`. The dashboard SHALL include the following panels:

| Panel           | Metric                                                                                                                                                             | Description                       |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- | ------------------- |
| Request Rate    | `sum(rate(http_requests_total[5m])) by (status_code)`                                                                                                              | Request rate by status code       |
| Error Rate      | `sum(rate(http_requests_total{status_code=~"4..                                                                                                                    | 5.."}[5m])) by (status_code)`     | 4xx/5xx error rates |
| Request Latency | Separate `histogram_quantile(0.50, ...)`, `histogram_quantile(0.95, ...)`, and `histogram_quantile(0.99, ...)` queries over `http_request_duration_seconds_bucket` | p50/p95/p99 latency               |
| Chat Responses  | `sum(rate(chat_responses_total[5m])) by (status)`                                                                                                                  | Chat responses by status          |
| Chat Latency    | `histogram_quantile(...)` from `chat_response_latency_seconds`                                                                                                     | Chat response latency percentiles |
| Rate Limit Hits | `rate(rate_limit_hits_total[5m])`                                                                                                                                  | Rate limit rejection rate         |
| Queue Depth     | `sum(arq_queue_depth)`                                                                                                                                             | Current total arq queue depth     |
| Audit Activity  | `rate(audit_logs_total[5m])`                                                                                                                                       | Audit log write rate              |
| Service Health  | `up`                                                                                                                                                               | Scrape target up/down status      |

#### Scenario: Dashboard loads in Grafana

- **WHEN** Grafana starts with provisioned configuration
- **THEN** the ProxyMind Overview dashboard SHALL be available in the ProxyMind folder
- **AND** all panels SHALL render without query errors (when metrics exist)

#### Scenario: Dashboard JSON is valid

- **WHEN** `monitoring/grafana/dashboards/proxymind-overview.json` is parsed as JSON
- **THEN** it SHALL be valid JSON
- **AND** it SHALL contain a `panels` array with at least 9 panels

---

### Requirement: Named volumes for monitoring services

Docker Compose SHALL define three new named volumes for monitoring data persistence:

- `prometheus-data`
- `grafana-data`
- `tempo-data`

#### Scenario: Monitoring data persists across restarts

- **WHEN** `docker compose down` followed by `docker compose up` is executed (without `-v` flag)
- **THEN** Prometheus metrics history, Grafana settings, and Tempo traces SHALL be preserved

---

### Requirement: Configuration file directory structure

The monitoring configuration files SHALL follow this directory structure:

```
monitoring/
  prometheus/
    prometheus.yml
  tempo/
    tempo.yml
  grafana/
    provisioning/
      datasources/
        datasources.yml
      dashboards/
        dashboards.yml
    dashboards/
      proxymind-overview.json
```

#### Scenario: All configuration files exist

- **WHEN** the repository is inspected after implementation
- **THEN** all six configuration files SHALL exist at the specified paths

---

## Test Coverage

### CI tests (deterministic)

- **Dashboard JSON validity test**: parse `proxymind-overview.json` as JSON, verify it contains a `panels` array with at least 9 entries.
- **Prometheus config validity test**: parse `prometheus.yml` as YAML, verify `scrape_configs` contains the expected job.
- **Tempo config validity test**: parse `tempo.yml` as YAML, verify OTLP receiver and local storage are configured.
- **Grafana datasources config test**: parse `datasources.yml` as YAML, verify Prometheus and Tempo datasources are defined.

---

### Requirement: SLOs and quality gates

Monitoring components SHALL ship with explicit operational expectations. Prometheus, Grafana, and Tempo SHALL target 99.9% monthly availability in single-instance deployments. Dashboard queries used by the default overview dashboard SHOULD complete within 5 seconds at the 95th percentile. Metrics retention, trace retention, and WAL/storage settings SHALL be explicitly configured and reviewed during infrastructure changes. CI and manual smoke checks SHALL verify that the configured image versions remain at or above `prom/prometheus:v3.10.0`, `grafana/grafana:12.4.1`, and `grafana/tempo:2.10.3`.

#### Scenario: Monitoring version gates remain compliant

- **WHEN** `docker-compose.yml` and monitoring configs are reviewed in CI or pre-release checks
- **THEN** Prometheus SHALL remain at `v3.10.0` or newer
- **AND** Grafana SHALL remain at `12.4.1` or newer
- **AND** Tempo SHALL remain at `2.10.3` or newer

### Evals (non-deterministic, manual verification)

- **Docker Compose smoke test**: `docker compose up` starts all three monitoring services without errors.
- **Grafana dashboard loads**: navigate to Grafana, verify the ProxyMind Overview dashboard exists and panels render.
- **Prometheus scrapes API**: verify Prometheus targets show the API endpoint as UP.
- **Tempo receives traces**: send a chat request, verify traces appear in Grafana Explore via Tempo.
