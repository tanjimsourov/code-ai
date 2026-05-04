# Observability Guide

This document describes the observability features built into the Code Editor backend.

## Logging

The application emits structured JSON logs using the standard Python `logging` module.  The helper `code_editor.observability.logging_utils.log_event` should be used to log significant events with context.  Logs include high‑level information such as the request endpoint, provider name, model, request kind, latency and user identifier.  Sensitive values like API keys, tokens or secrets are automatically filtered out before emission.

To change the log format or destination, configure the Django logging settings in your project's settings module.  By default, the `code_editor` logger writes to the console at the `INFO` level.

## Metrics

When the optional [`prometheus_client`](https://github.com/prometheus/client_python) library is installed, the backend exposes Prometheus metrics at `/metrics/`.  The following metrics are available:

- `code_editor_requests_total{endpoint,method,status}` – total API requests.
- `code_editor_request_latency_seconds{endpoint,method}` – histogram of API request latencies.
- `code_editor_provider_latency_seconds{provider,request_type}` – latency of calls to AI providers.
- `code_editor_input_tokens_total{provider,request_type}` – estimated input tokens/characters processed.
- `code_editor_output_tokens_total{provider,request_type}` – estimated output tokens/characters generated.
- `code_editor_task_status_total{status}` – count of tasks by final status.
- `code_editor_indexing_duration_seconds{repository}` – time spent indexing repositories.
- `code_editor_validation_duration_seconds{task}` – time spent validating patches.

If `prometheus_client` is not installed, the `/metrics/` endpoint returns a `503` status code and no metrics are collected.

## Health Checks

Two health check endpoints are provided:

- **Liveness**: `GET /health/live` returns `{"status": "ok"}` if the process is running.
- **Readiness**: `GET /health/ready` performs a series of dependency checks (database connectivity, pending migrations, cache availability, provider configuration and storage availability).  It returns a JSON object with `status` (`ok` or `degraded`) and a `checks` dictionary detailing each sub‑check.  These endpoints are unauthenticated to allow infrastructure probes to monitor service health.

## Throttling

Several throttling classes under `code_editor.api.throttles` implement rate limits for different request categories.  These include:

- `AIThrottle` – limits chat, completion and embedding requests.
- `PublicReadThrottle` – limits unauthenticated read‑only endpoints such as health checks.
- `RepoMutationThrottle` – limits repository mutation operations.
- `TaskMutationThrottle` – limits task creation and cancellation operations.
- `ProviderHealthThrottle` – limits calls to provider health status endpoints.
- `UpstreamSyncThrottle` – limits upstream repository synchronisation tasks.

Rate limits are defined in the throttle classes but can be customised via DRF settings or by subclassing these throttles.

## Tracing

OpenTelemetry integration has been stubbed into the codebase.  When the relevant libraries are installed and tracing is enabled via environment variables, request spans and provider calls will automatically propagate trace context.  Refer to the deployment documentation for configuring exporters (Jaeger, Zipkin, OTLP, etc.) and enabling tracing.