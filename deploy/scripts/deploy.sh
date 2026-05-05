#!/usr/bin/env bash
set -euo pipefail
cd /opt/code-ai
source .venv/bin/activate
git pull --ff-only
pip install -e .[postgres,channels_redis,celery,providers,observability]
./deploy/scripts/migrate.sh
./deploy/scripts/collectstatic.sh
sudo systemctl restart code-ai-web code-ai-daphne code-ai-worker
