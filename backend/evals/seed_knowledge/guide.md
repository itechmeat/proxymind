# ProxyMind User Guide

## Chapter 1: Installation

ProxyMind runs as a self-hosted application with separate backend, frontend,
and infrastructure services. A typical local environment uses Docker Compose to
start PostgreSQL, Redis, Qdrant, SeaweedFS, the API service, and the frontend.

Before starting the stack, verify that the environment file contains the admin
API key, model credentials, and storage endpoints. After the services start,
the API becomes available on port 8000 and the frontend on port 5173.

## Chapter 2: Knowledge Ingestion

Knowledge enters the system through the admin API. Each uploaded source is
stored in object storage, parsed into normalized text, chunked, embedded, and
indexed for hybrid retrieval. Published snapshots isolate stable knowledge from
draft work so that a dialogue session always references a concrete snapshot.

The ingestion flow keeps metadata about source type, language, and anchors.
Those anchors later power citations such as pages, chapters, or timecodes.

## Chapter 3: Deployment

Deployment requires three steps: configure the environment, start the service
stack, and verify observability. Operators first review the `.env` values for
database, Redis, Qdrant, SeaweedFS, and LLM settings. They then run the Docker
Compose stack and confirm that the backend can connect to all required services.

After the stack is online, operators check health endpoints and telemetry.
Prometheus should scrape metrics, Grafana should load dashboards, and Tempo
should receive traces when observability is enabled. A deployment is considered
ready only after application health, retrieval, and tracing are all verified.

## Chapter 4: Evaluation Workflow

The evaluation workflow uses curated datasets to measure retrieval quality and
answer quality. Retrieval metrics show whether relevant chunks are found, while
answer metrics show whether the final response is grounded, well cited, aligned
with persona, and able to refuse appropriately when the system lacks context.

Operators promote a good report into the baselines directory and compare later
runs against it before adopting retrieval upgrades.
