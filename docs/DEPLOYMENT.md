# Deployment

## VPS / Ubuntu / Dedicated Server

1. Create app dir `/opt/code-editor`
2. Install Python and create virtualenv
3. Install project dependencies
4. Configure `.env` for production
5. Run migrations and collectstatic
6. Install systemd units from `deploy/systemd/`
7. Configure Nginx from `nginx/code_editor_backend.conf`
8. Start services and enable on boot

## Docker

- Build: `docker compose build`
- Run: `docker compose up -d`

## Rollback Basics

- Roll back to previous git commit
- Re-run migrations if needed
- Restart services
