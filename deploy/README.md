# Deployment Assets

This folder provides production deployment scaffolding for systemd and shell-driven rollout.

- `systemd/` includes unit files for Gunicorn, Daphne, and Celery worker.
- `scripts/` includes deploy, migrate, collectstatic, and healthcheck scripts.

These files are templates and must be adjusted for your final server paths, user, and virtualenv location.
