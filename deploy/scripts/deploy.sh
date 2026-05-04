#!/usr/bin/env bash
set -euo pipefail
cd /opt/code-editor
source .venv/bin/activate
git pull --ff-only
pip install -e .[postgres,channels_redis]
./deploy/scripts/migrate.sh
./deploy/scripts/collectstatic.sh
sudo systemctl restart code-editor-web code-editor-daphne code-editor-worker
