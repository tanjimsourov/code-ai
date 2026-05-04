# Operations

## Logs

- Application logs go to stdout/stderr by default.
- Systemd journal captures service logs in production.

## Health

- `python manage.py code_editor_health_report --settings=config.settings.production`
- `GET /health/live/`
- `GET /health/ready/`

## Maintenance

- Cleanup workspaces: `python manage.py cleanup_code_editor_workspaces`
- Prune artifacts: `python manage.py code_editor_prune_artifacts`
- Reindex repository: `python manage.py reindex_code_editor_repository --repository-id <id>`

## Backups

- PostgreSQL DB dump
- `var/` storage root backups (tasks/repos/artifacts)
