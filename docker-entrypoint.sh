#!/bin/sh
# Runs as root: fix bind-mount ownership, then drop to app user.
# GIGAAM_CACHE: baked /models layer OR external mount (download if empty).
set -e
DATA_DIR="${DATA_DIR:-/app/data}"
CACHE_DIR="${GIGAAM_CACHE:-/models}"
mkdir -p "$DATA_DIR" "$CACHE_DIR"
chown -R app:app "$DATA_DIR" "$CACHE_DIR" 2>/dev/null || true
if [ -z "$(ls -A "$CACHE_DIR" 2>/dev/null)" ]; then
  echo "entrypoint: $CACHE_DIR empty, downloading ${MODEL_NAME:-v3_e2e_ctc} (~422MB)..."
  su app -s /bin/sh -c 'python -c "import os, gigaam; gigaam.load_model(os.environ.get(\"MODEL_NAME\",\"v3_e2e_ctc\"), download_root=os.environ[\"GIGAAM_CACHE\"])"'
else
  echo "entrypoint: using cached weights in $CACHE_DIR"
fi
exec su app -s /bin/sh -c 'exec $0' "$*"
