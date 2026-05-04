# Security

- Mutating endpoints require API key permission classes.
- Metrics are private by default; token/public flag required.
- Model listing is private by default unless explicitly enabled.
- Patch apply/revert use server-owned paths only.
- Artifact reads are constrained to configured storage root.
- Command execution enforces timeout, output cap, and cwd boundary.
- No paid SDKs required in base install.
- No hard-coded secrets in repository.
- Upstream update flow is approval-gated and not auto-merge.
