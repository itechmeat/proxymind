# Exploration: OpenTelemetry Tracing Backends for Self-Hosted Docker Compose

Date: 2026-03-27

## Research question

What is the current state of OpenTelemetry tracing backends suitable for a self-hosted, single-instance Python/FastAPI project running via Docker Compose? Specifically: which backends are actively maintained, what are their resource profiles, and what Python instrumentation packages are needed?

## Scope

**In scope:** Jaeger, Grafana Tempo, SigNoz as tracing backends. OpenTelemetry Python SDK and FastAPI instrumentation packages. Docker Compose deployment only. Single-instance, low-to-moderate trace volume.

**Out of scope:** SaaS/cloud-hosted tracing services. Kubernetes deployments. High-volume production scaling. Metrics and logging pipelines (covered separately). Cost optimization for object storage.

**Constraints from project spec:** The project already uses Prometheus 3.10.0+, Grafana 12.4.1+, and specifies OpenTelemetry Collector 1.53.0+ / spec 1.55.0+. No tracing backend is pinned in [docs/spec.md](../../docs/spec.md).

## Findings

### Jaeger: current state and v2 architecture

Jaeger released v2.0 in [November 2024](https://www.cncf.io/blog/2024/11/12/jaeger-v2-released-opentelemetry-in-the-core/), representing a fundamental architecture change. The latest release as of March 2026 is v2.16. Jaeger v1 was [deprecated in January 2026](https://www.jaegertracing.io/docs/2.16/architecture/) following the last v1 release in December 2025. The project remains actively maintained under CNCF, with the [main repository updated March 26, 2026](https://github.com/jaegertracing/jaeger).

The v2 architecture rebuilds Jaeger on top of the OpenTelemetry Collector framework. Key changes:

- **Single binary:** All Jaeger components (collector, query, UI) are now a single binary, replacing the multi-binary v1 deployment.
- **Native OTLP support:** Jaeger v2 natively understands OTLP end-to-end, eliminating translation layers needed in v1.
- **OTel Collector ecosystem:** Built on the Collector, Jaeger v2 inherits receivers, processors, and exporters from the OTel ecosystem (tail-based sampling, PII filtering, etc.).
- **Configuration change:** CLI flags are no longer supported in v2. Configuration uses environment variables or YAML config files.

The `jaegertracing/all-in-one` Docker image remains available for single-node deployments. Default storage is in-memory (data lost on restart). For persistence, [Badger](https://github.com/orgs/jaegertracing/discussions/7487) (embedded key-value store) is available and exclusive to all-in-one mode. Cassandra and Elasticsearch remain supported for larger deployments.

Grafana has a [built-in Jaeger data source](https://grafana.com/docs/grafana/latest/datasources/jaeger/), so traces can be viewed in the project's existing Grafana instance without exposing the Jaeger UI separately.

**Resource profile:** The all-in-one image with Badger storage is lightweight for low-volume use. No external database required. Single container.

**Confidence:** Corroborated -- multiple independent sources confirm v2 architecture, deprecation timeline, and all-in-one capabilities.

### Grafana Tempo: current state

Grafana Tempo's latest stable release is [v2.10.3 (March 17, 2026)](https://github.com/grafana/tempo/releases). Recent minor versions added notable features: v2.8 brought advanced TraceQL queries (parent-span filters, `sum_over_time`, `topk`/`bottomk`), and v2.9 added [MCP server support](https://grafana.com/docs/tempo/latest/release-notes/v2-9/) for LLM integration with tracing data.

Tempo runs in two modes:

- **Monolithic (single binary):** All components in one process -- ingestion, storage, compaction, querying. Suitable for development and small-scale deployments.
- **Microservices:** Separate components for scale. Not relevant for this project.

Storage options:

- **Local disk:** Works for single-binary mode. Not suitable for distributed deployments but fine for a single Docker Compose instance.
- **Object storage (S3, GCS, Azure Blob):** The designed-for-production path. Cheaper than Elasticsearch/Cassandra at scale.

Tempo's design philosophy is [deliberately minimal](https://signoz.io/blog/jaeger-vs-tempo/) -- it stores large volumes of traces cheaply and relies on Grafana for querying. It does not have its own UI. Ad hoc searching across span attributes is more limited than Jaeger or SigNoz; the expectation is that investigations begin with metrics (Prometheus) or logs (Loki) and jump to traces by trace ID.

**Resource profile for monolithic mode:** Community reports suggest [200Mi-1Gi RAM](https://community.grafana.com/t/tempo-memory-requirement-recommendations/114294) for modest volumes. Tempo's official [Docker Compose example](https://grafana.com/docs/tempo/latest/docker-example/) runs Tempo + Grafana with local storage as a minimal stack.

**Native Grafana integration:** Tempo is a first-class Grafana data source. Since the project already uses Grafana 12.4.1+, Tempo traces would appear directly in Grafana dashboards with no additional UI tooling. TraceQL provides a query language for trace exploration within Grafana.

**Confidence:** Corroborated -- official Grafana documentation and GitHub releases confirm version, features, and deployment modes.

### SigNoz: current state

SigNoz is an open-source, full-stack observability platform (traces + metrics + logs) built natively for OpenTelemetry. It uses [ClickHouse as its storage backend](https://signoz.io/docs/install/docker/), providing fast columnar queries.

Docker Compose deployment requires [multiple containers](https://github.com/SigNoz/signoz/blob/main/deploy/docker/docker-compose.yaml): ClickHouse, ZooKeeper, query-service, frontend, OTel Collector, alertmanager, and init/migration containers. Minimum resource requirement is [4GB RAM for Docker, with 8GB recommended](https://signoz.io/docs/install/docker/) and 16GB+ for production ClickHouse workloads.

SigNoz provides its own full UI at `localhost:3301`, covering trace exploration, metrics dashboards, and log querying in one interface.

**Trade-offs for this project:**

- SigNoz duplicates capabilities the project already has: Grafana for dashboards, Prometheus for metrics.
- The ClickHouse + ZooKeeper dependency adds significant container count and resource overhead for a single-instance deployment.
- SigNoz's strength is being an all-in-one replacement for the Grafana/Prometheus/Tempo stack, not a complement to it.

**Confidence:** Substantiated -- based on official SigNoz documentation and Docker Compose configurations.

### Other backends considered

**Uptrace** -- open-source, uses ClickHouse. Similar trade-offs to SigNoz (heavy for single-instance, duplicates existing stack). Less community adoption than SigNoz.

**Zipkin** -- still maintained but has not seen the architectural modernization that Jaeger v2 underwent. OTLP support is available but not native. Generally considered a previous-generation tool in the tracing space.

No significant new lightweight self-hosted tracing backends emerged in 2025-2026 beyond the established options above.

**Confidence:** Substantiated -- based on multiple comparison articles and tool surveys from 2025-2026.

### OpenTelemetry Python instrumentation packages

The OpenTelemetry Python SDK latest stable version is [1.40.0 (March 4, 2026)](https://pypi.org/project/opentelemetry-sdk/). The contrib package `opentelemetry-instrumentation-fastapi` tracks the same release cadence.

Core packages needed for FastAPI tracing:

| Package | Role |
|---------|------|
| `opentelemetry-api` | Core API (stable, 1.40.0) |
| `opentelemetry-sdk` | SDK implementation (stable, 1.40.0) |
| `opentelemetry-instrumentation-fastapi` | Auto-instrumentation for FastAPI routes |
| `opentelemetry-instrumentation-asgi` | ASGI middleware instrumentation (dependency of FastAPI instrumentor) |
| `opentelemetry-exporter-otlp` | OTLP exporter (gRPC + HTTP) to send traces to any OTLP-compatible backend |

Optional complementary packages:

| Package | Role |
|---------|------|
| `opentelemetry-instrumentation-httpx` | Trace outgoing HTTP calls (e.g., to LiteLLM, Gemini) |
| `opentelemetry-instrumentation-sqlalchemy` | Trace database queries |
| `opentelemetry-instrumentation-redis` | Trace Redis operations |
| `opentelemetry-instrumentation-logging` | Inject trace context into log records |

The [FastAPIInstrumentor](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html) provides `instrument_app()` for instrumenting a FastAPI application. It supports request/response hooks, tracer provider configuration, and URL pattern exclusion. Python 3.9+ is required; FastAPI 0.92+ is required (earlier versions dropped in recent releases).

**Export path options:**

1. **Direct export to backend:** Application sends OTLP directly to Jaeger/Tempo (both accept OTLP on ports 4317/gRPC and 4318/HTTP).
2. **Via OTel Collector:** Application sends OTLP to the Collector, which processes and forwards to the backend. The project spec already includes OTel Collector 1.53.0+, so this path aligns with the existing architecture.

**Confidence:** Corroborated -- PyPI releases and official OpenTelemetry documentation confirm versions and package structure.

## Comparison

| Criteria | Jaeger v2 all-in-one | Grafana Tempo (monolithic) | SigNoz |
|----------|---------------------|---------------------------|--------|
| **Latest version** | 2.16.0 | 2.10.3 | Active (ClickHouse-based) |
| **Containers needed** | 1 | 1 | 6-8 (ClickHouse, ZooKeeper, etc.) |
| **Min RAM estimate** | ~256MB-512MB | ~200MB-1GB | ~4GB (8GB recommended) |
| **Persistent storage** | Badger (embedded) or Cassandra/ES | Local disk or object storage (S3/GCS) | ClickHouse + ZooKeeper |
| **OTLP native** | Yes (v2 built on OTel Collector) | Yes (ports 4317, 4318) | Yes (ports 4317, 4318) |
| **Own UI** | Yes (trace viewer) | No (uses Grafana) | Yes (full observability UI) |
| **Grafana data source** | Yes (built-in) | Yes (first-class, TraceQL) | Possible but not primary path |
| **Fits existing stack** | Adds 1 container, works with Grafana | Adds 1 container, native Grafana integration | Duplicates Grafana + Prometheus |
| **Query capabilities** | Trace search by service, operation, tags, duration | TraceQL (structural queries, aggregations) | Full-text search, tag filtering, flamegraphs |
| **OTel Collector needed** | Optional (Jaeger v2 IS an OTel Collector) | Yes, or direct OTLP | Bundles its own Collector |
| **CNCF status** | Graduated project | N/A (Grafana Labs OSS, AGPLv3) | N/A (Apache 2.0) |
| **Maintenance signal** | Active, updated March 26, 2026 | Active, v2.10.3 released March 17, 2026 | Active |

## Key takeaways

- Jaeger v2 (2.16.0) is a fundamentally different product from v1 -- it is now built on the OpenTelemetry Collector framework, runs as a single binary, and natively supports OTLP. Jaeger v1 was deprecated January 2026. (Corroborated)

- Grafana Tempo v2.10.3 runs as a single binary with local disk storage, requires no external database for small deployments, and is a first-class Grafana data source with TraceQL. It has no standalone UI -- it requires Grafana, which this project already runs. (Corroborated)

- SigNoz requires 6-8 containers and 4-8GB RAM minimum, duplicating Grafana and Prometheus capabilities the project already has. Its strength is as a full-stack replacement, not a complement. (Substantiated)

- The OpenTelemetry Python SDK is at v1.40.0 with stable FastAPI instrumentation. The core packages (`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp`) plus library-specific instrumentors (`httpx`, `sqlalchemy`, `redis`) form the standard instrumentation stack. (Corroborated)

- Both Jaeger v2 and Tempo accept OTLP natively (ports 4317/4318), so the application export path is identical regardless of backend choice. The project's specified OTel Collector can sit in front of either. (Corroborated)

## Open questions

- **Jaeger v2 as OTel Collector replacement:** Since Jaeger v2 is built on the OTel Collector, it can potentially serve as both the Collector and the tracing backend. This could eliminate the need for a separate OTel Collector container. Needs testing to confirm whether it can handle the project's non-tracing Collector duties (e.g., metrics forwarding).

- **Tempo TraceQL vs Jaeger search:** For a single-developer or small-team self-hosted instance, which query model is more practical? TraceQL is more powerful but has a learning curve. Jaeger's UI provides simpler point-and-click trace search. This is a UX preference question that cannot be answered by research alone.

- **Badger storage durability:** Jaeger's Badger storage is an embedded key-value store. Its behavior under crash recovery, compaction overhead, and long-term data retention for a Docker Compose setup needs validation if trace data retention matters.

- **Tempo local storage limits:** Grafana's documentation notes local storage works for single-binary mode but warns about scaling. For a single-instance project, the practical upper bound on trace volume before local storage becomes a problem is unknown.

## Sources

1. [Jaeger v2 Released: OpenTelemetry in the Core (CNCF)](https://www.cncf.io/blog/2024/11/12/jaeger-v2-released-opentelemetry-in-the-core/) -- v2 architecture announcement, OTel Collector integration details
2. [Jaeger Architecture docs (v2.16)](https://www.jaegertracing.io/docs/2.16/architecture/) -- current architecture, deployment modes, storage backends
3. [Jaeger GitHub releases](https://github.com/jaegertracing/jaeger/releases/) -- version history, latest release confirmation
4. [Jaeger at 10 (CNCF)](https://www.cncf.io/blog/2025/09/01/jaeger-at-10-forged-in-community-reborn-in-opentelemetry/) -- project health and roadmap
5. [Grafana Tempo release notes](https://grafana.com/docs/tempo/latest/release-notes/) -- v2.8-v2.10 features
6. [Grafana Tempo GitHub releases](https://github.com/grafana/tempo/releases) -- v2.10.3 confirmation
7. [Tempo Docker Compose example](https://grafana.com/docs/tempo/latest/docker-example/) -- official quick-start configuration
8. [Tempo deployment modes](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/plan/deployment-modes/) -- monolithic vs microservices
9. [Tempo memory requirements (community forum)](https://community.grafana.com/t/tempo-memory-requirement-recommendations/114294) -- real-world resource usage
10. [SigNoz Docker Standalone installation](https://signoz.io/docs/install/docker/) -- container requirements, RAM minimums
11. [Jaeger vs Tempo (SigNoz)](https://signoz.io/blog/jaeger-vs-tempo/) -- comparison of design philosophies
12. [7 Open Source Distributed Tracing Tools (Dash0)](https://www.dash0.com/comparisons/open-source-distributed-tracing-tools) -- 2026 landscape overview
13. [opentelemetry-sdk on PyPI](https://pypi.org/project/opentelemetry-sdk/) -- v1.40.0 release confirmation
14. [opentelemetry-instrumentation-fastapi on PyPI](https://pypi.org/project/opentelemetry-instrumentation-fastapi/) -- package details, Python/FastAPI version requirements
15. [FastAPI instrumentation docs](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html) -- API reference, usage patterns
16. [Grafana Jaeger data source](https://grafana.com/docs/grafana/latest/datasources/jaeger/) -- built-in Grafana integration
17. [Jaeger Badger storage discussion](https://github.com/orgs/jaegertracing/discussions/7487) -- persistence configuration for all-in-one
