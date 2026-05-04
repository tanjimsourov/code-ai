#!/usr/bin/env bash
set -euo pipefail
cd /opt/code-editor
source .venv/bin/activate
python manage.py code_editor_health_report --settings=config.settings.production
