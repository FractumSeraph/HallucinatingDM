#!/usr/bin/env sh
# Update Labyrinths and Llamas to the latest code and restart it.
#
#   ./update.sh                 # plain app (LLM_BASE_URL points elsewhere)
#   ./update.sh --ollama        # app + bundled Ollama profile
#   ./update.sh --ollama --gpu  # app + Ollama with the GPU override file
#
# Safe to run any time: your campaigns live in ./data (a bind mount the
# containers never delete), a timestamped database backup is taken first,
# and schema migrations run automatically when the new version boots.
set -eu
cd "$(dirname "$0")"

PROFILE=""
FILES="-f docker-compose.yml"
for arg in "$@"; do
  case "$arg" in
    --ollama) PROFILE="--profile ollama" ;;
    --gpu) FILES="$FILES -f docker-compose.gpu.yml" ;;
    *) echo "Unknown option: $arg (use --ollama and/or --gpu)" >&2; exit 1 ;;
  esac
done

echo "==> Backing up the database to data/backups/"
if [ -f data/app.db ]; then
  mkdir -p data/backups
  cp data/app.db "data/backups/app-$(date +%Y%m%d-%H%M%S).db"
  # keep the ten most recent backups
  ls -1t data/backups/app-*.db 2>/dev/null | tail -n +11 | xargs -r rm --
else
  echo "    (no data/app.db yet — first run?)"
fi

echo "==> Pulling the latest code"
git pull --ff-only

echo "==> Rebuilding the app image"
# shellcheck disable=SC2086
docker compose $FILES build app

echo "==> Restarting"
# shellcheck disable=SC2086
docker compose $PROFILE $FILES up -d

echo "==> Waiting for the app to come back"
i=0
until curl -sf "http://localhost:${PORT:-8080}/healthz" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "App didn't report healthy after 2 minutes — check: docker compose logs app" >&2
    exit 1
  fi
  sleep 2
done

echo "==> Done. Now running: $(git log --oneline -1)"
