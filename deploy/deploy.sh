#!/usr/bin/env bash
#
# First-time (and repeatable) deploy for a Labyrinths & Llamas test instance.
# LLM backend: OpenCode Go (hosted, OpenAI-compatible /v1 endpoint).
#
# Run from the repo root on the VPS, passing your OpenCode Zen key:
#
#   OPENCODE_API_KEY=sk-your-key sudo -E ./deploy/deploy.sh
#
# Re-running is safe: it installs Docker if missing, never overwrites an
# existing .env, and rebuilds + restarts the app. To change the model or port,
# export LLM_MODEL / PORT before running (only used when .env is first created).
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LLM_MODEL="${LLM_MODEL:-qwen3.6-plus}"
PORT="${PORT:-8080}"

# --- 1. Docker + compose plugin -------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo ">> Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  echo ">> Installing docker compose plugin..."
  apt-get update && apt-get install -y docker-compose-plugin
fi

# --- 2. .env (secrets live here; it is git-ignored) -----------------------
if [ ! -f .env ]; then
  if [ -z "${OPENCODE_API_KEY:-}" ]; then
    echo "ERROR: set OPENCODE_API_KEY (your OpenCode Zen key) on first run." >&2
    echo "       OPENCODE_API_KEY=sk-... sudo -E ./deploy/deploy.sh" >&2
    exit 1
  fi
  echo ">> Writing .env..."
  if command -v python3 >/dev/null 2>&1; then
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  else
    SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n')"
  fi
  cat > .env <<EOF
# Signs auth tokens and encrypts stored API keys. Keep this secret.
SECRET_KEY=${SECRET_KEY}

# --- LLM: OpenCode Go (hosted, OpenAI-compatible) ---
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://opencode.ai/zen/go/v1
LLM_API_KEY=${OPENCODE_API_KEY}
LLM_MODEL=${LLM_MODEL}
LLM_TOOLCALL_MODE=auto

# OpenCode Go has no embeddings endpoint, so rules/lore search runs
# keyword-only (FTS5) — this is fine for a test instance. To enable semantic
# search later, run a local Ollama and point these at http://ollama:11434/v1.
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=nomic-embed-text

# --- Server ---
DATA_DIR=/data
PORT=${PORT}
# Set to https://your-domain if you put this behind an HTTPS reverse proxy
# (enables secure cookies). Leave empty for plain-HTTP-by-IP testing.
PUBLIC_ORIGIN=
EOF
  chmod 600 .env
  echo ">> .env created (SECRET_KEY generated; key stored)."
else
  echo ">> .env already exists — leaving it untouched."
fi

# --- 3. Firewall (open the app port if ufw is active) ---------------------
PORT_FROM_ENV="$(grep -E '^PORT=' .env | cut -d= -f2 || true)"
PORT="${PORT_FROM_ENV:-$PORT}"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  echo ">> Opening port ${PORT}/tcp in ufw..."
  ufw allow "${PORT}"/tcp || true
fi

# --- 4. Build & start (only the app service; ollama stays behind a profile)
echo ">> Building and starting the app..."
docker compose up -d --build

# --- 5. Wait for health ---------------------------------------------------
echo ">> Waiting for the app to become healthy..."
for _ in $(seq 1 45); do
  if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1; then
    echo
    echo ">> Healthy. Open http://$(curl -fsS ifconfig.me 2>/dev/null || echo YOUR_VPS_IP):${PORT}"
    echo ">> First account you register becomes the admin."
    exit 0
  fi
  sleep 2
done
echo ">> App did not report healthy in time. Inspect logs:"
echo "     docker compose logs -f"
exit 1
