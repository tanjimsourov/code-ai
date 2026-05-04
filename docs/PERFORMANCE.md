# Performance and Scalability Guide

This document outlines best practices and tuning parameters to ensure the
`code_editor` backend performs well under real‑world workloads.  It
covers query optimisation, pagination, indexing, caching, quota
enforcement, rate limiting and bulk operations.

## Query Optimisation

- **Avoid N+1 queries**: Use `select_related` for foreign key relations
  and `prefetch_related` for reverse/many‑to‑many relations.  For example,
  `task_runs.select_related('repository')` when displaying task lists.

- **Paginate all lists**: All list endpoints use `PageNumberPagination`
  with a default page size of 20 and a maximum of 100.  Use the
  `page_size` query parameter to customise responses.  Avoid calling
  `.all()` on large querysets without a paginator.

- **Batch large `__in` lookups**: When filtering by a large list of IDs
  use batching to avoid generating extremely long SQL queries.

- **Order by indexed fields**: Order results by fields with database
  indexes such as `created_at` to allow efficient sorting.

## Indexing Strategy

Additional indexes have been added to speed up common queries:

- `Project.name` – for fast project lookup by name.
- `Repository.url`, `Repository.branch`, `Repository.vcs_provider`,
  `Repository.commit_sha` – to support remote sync operations.
- `TaskRun.approval_status`, `TaskRun.effective_apply_mode`,
  `TaskRun.requested_apply_mode` – for efficient review workflows.
- `CandidatePatch.approval_status`, `CandidatePatch.apply_mode_effective` –
  for bulk approval and analytics.

Regularly run `analyze_backend_hotspots` to see counts by status and
detect missing indexes.

## Caching

The system uses multiple caches to accelerate common queries and lookups:

- **Model registry and provider health** – The `ModelRegistryService`
  caches resolved role entries for five minutes to avoid repeated
  provider/model discovery.  Provider health snapshots are also
  cached to prevent redundant health checks on each request.  Use
  the `CacheHelper` utilities or the `code_editor_invalidate_caches`
  management command to clear these caches when model configurations or
  provider availability change.

- **Repository statistics and code maps** – Counts of files and
  chunks, language distributions, generated code maps and context
  packs are cached.  These caches reduce the overhead of repeated
  retrieval and context building.  Ingesting or reindexing a
  repository, updating selected files or applying patches triggers
  invalidation via the cache helper.

- **Navigation and settings** – Caching page navigation trees, site
  settings and published page lookups is recommended in production.
  Invalidate caches whenever pages are published/unpublished or
  settings change.

- **Provider and quota state** – The `QuotaService` stores rate
  counters and quota usage in Redis for efficient atomic checks.  A
  combination of in‑memory caches and database indexes ensures that
  quota checks remain performant even under heavy load.

## Quotas and Rate Limits

- **Per‑API‑key quotas**: Each API key has a `daily_quota` and
  `rpm_limit` (requests per minute).  The `QuotaService` enforces
  quotas atomically using Redis counters and falls back to the
  database if Redis is unavailable.  When a quota is exceeded a
  `QuotaExceededException` is raised and a `429` response is returned.

- **Throttling**: DRF `SimpleRateThrottle` has been extended as
  `AIThrottle` to dynamically adjust rate limits based on the API
  key’s `rpm_limit`.  All AI, retrieval and task creation endpoints
  decorate their views with `@throttle_classes([AIThrottle])`.

## Bulk Operations

The bulk operations API (under `/api/code-editor/bulk/`) provides
endpoints for cancelling tasks and approving candidate patches in
batches.  Bulk operations reduce latency and ensure consistent
permission and quota checks.

## Monitoring and Hotspot Analysis

- Use the management command `python manage.py analyze_backend_hotspots`
  to print counts of tasks, candidate patches, ingestion jobs and
  repositories by status.  It also checks for missing indexes on
  critical fields.

- Integrate the Django debug toolbar in a development environment
  to capture per‑view query counts and timings.  Address any view that
  performs an excessive number of queries.

## Production Tuning

- Deploy with a production‑grade database (e.g. PostgreSQL) and
  configure appropriate connection pooling.
- Use a caching layer such as Redis or Memcached for Django’s cache
  backend and for `QuotaService` counters.
- Configure the application server (e.g. gunicorn or uWSGI) with
  enough worker processes and threads to handle concurrent requests.
- Monitor CPU, memory and I/O metrics; adjust worker counts and
  database pool sizes accordingly.