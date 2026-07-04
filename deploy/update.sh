#!/usr/bin/env bash
#
# Update the running test instance to the latest code from GitHub.
#
#   sudo ./deploy/update.sh            # update the current branch
#   sudo ./deploy/update.sh main       # switch to and update another branch
#
# Your .env and ./data (SQLite DB + uploads) are never touched.
# Database migrations run automatically when the new container boots.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
PORT="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)"
PORT="${PORT:-8080}"

echo ">> Fetching origin/${BRANCH}..."
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo ">> Rebuilding and restarting..."
docker compose up -d --build

echo ">> Pruning dangling images..."
docker image prune -f >/dev/null 2>&1 || true

echo ">> Waiting for health..."
for _ in $(seq 1 45); do
  if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1; then
    echo ">> Updated and healthy on port ${PORT}."
    exit 0
  fi
  sleep 2
done
echo ">> App did not report healthy in time. Inspect logs:"
echo "     docker compose logs -f"
exit 1
