# Deploying a test instance (VPS + OpenCode Go)

This directory holds two helper scripts for standing up a single-box test
instance of **Labyrinths & Llamas**, using **OpenCode Go** (hosted,
OpenAI-compatible) as the LLM backend. The whole app runs as one Docker
container that serves the API, the WebSocket hub, and the built frontend on one
port. Data (SQLite DB + uploaded PDFs) lives in `./data`.

- `deploy.sh` — first-time (and repeatable) setup: installs Docker, writes
  `.env`, opens the firewall port, builds, and starts the app.
- `update.sh` — pull the latest code and rebuild/restart in place.

Neither script stores your OpenCode key in git — it is written only into the
local, git-ignored `.env`.

---

## 1. First-time deploy

SSH into the VPS as root, clone the repo, and run the deploy script with your
OpenCode Zen key:

```bash
ssh root@YOUR_VPS_IP

# Clone (use HTTPS; if the repo is private you'll be prompted for a
# GitHub username + a personal-access-token as the password)
git clone https://github.com/FractumSeraph/HallucinatingDM.git /opt/hallucinatingdm
cd /opt/hallucinatingdm

# Deploy on the test branch, pointed at OpenCode Go
git checkout claude/vps-test-instance-deploy-ivkrwx
OPENCODE_API_KEY=sk-your-key sudo -E ./deploy/deploy.sh
```

The script installs Docker if needed, generates a `SECRET_KEY`, writes `.env`,
opens the app port in `ufw` (if active), builds the image, and waits for
`/healthz`. First build takes a few minutes (it compiles the frontend and
installs Python deps).

When it prints **Healthy**, open:

```
http://YOUR_VPS_IP:8080
```

### First-run app setup (in the browser)

1. **Register** the first account — it automatically becomes the **admin**.
2. Open the top-right menu → **Admin** → **Test connection**. Chat should
   round-trip against OpenCode Go. Embeddings will report unavailable — that is
   expected (OpenCode Go is chat-only), and rules/lore search falls back to
   keyword search.
3. **Create a campaign** — you're its DM. The invite code is on the campaign
   lobby page (DM-only); players register their own accounts and enter it under
   **Join a campaign**.
4. Create a scene from the lobby and play — type what you do in a scene and the
   AI narrates, calls for rolls, and applies consequences.

Provider settings (base URL, model, key, tool-call mode) can also be changed
live on the **Admin** page — no restart needed. Available OpenCode Go models
include the Qwen 3.6/3.7, GLM, Kimi, DeepSeek, and MiniMax families; the default
here is `qwen3.6-plus`.

---

## 2. Updating after you push changes to GitHub

From the repo directory on the VPS:

```bash
cd /opt/hallucinatingdm
sudo ./deploy/update.sh                 # updates the current branch
# or point at a specific branch:
sudo ./deploy/update.sh main
```

This fetches, fast-forwards, rebuilds the image, and restarts the container.
**Your `.env` and `./data` are left untouched**, and database migrations run
automatically the moment the new container boots. No manual migration step.

---

## 3. Useful operational commands

```bash
cd /opt/hallucinatingdm

docker compose ps                 # container status
docker compose logs -f            # live logs
docker compose restart            # restart without rebuilding
docker compose down               # stop (data in ./data is preserved)
docker compose up -d              # start again

# Full backup: just copy the data directory
tar czf landl-backup-$(date +%F).tgz data
```

To change the port or model after the fact, edit `.env` and run
`docker compose up -d --build`.

---

## 4. Optional: HTTPS behind a reverse proxy

For plain testing, HTTP-by-IP on port 8080 is fine. To serve over HTTPS on a
domain, put a reverse proxy (Caddy is simplest — automatic Let's Encrypt) in
front of `localhost:8080`, then set `PUBLIC_ORIGIN=https://your-domain` in
`.env` and `docker compose up -d` so auth cookies are marked secure.

Example `Caddyfile`:

```
your-domain.com {
    reverse_proxy localhost:8080
}
```
