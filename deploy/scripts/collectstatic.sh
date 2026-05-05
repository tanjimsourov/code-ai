#!/usr/bin/env bash
set -euo pipefail
cd /opt/code-ai
source .venv/bin/activate
python manage.py collectstatic --settings=config.settings.production --noinput
