# Upstream Governance

- Upstream sources are allowlisted via `CODE_EDITOR_UPSTREAM_SOURCES`.
- Sync command creates review candidates only; it does not auto-apply code.
- Dry-run mode previews candidate generation.
- Human approval is required before patch apply.
- Rollback metadata is tracked through task/candidate records.
- Silent auto-merge is explicitly not implemented.
