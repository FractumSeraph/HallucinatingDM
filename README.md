# 🎲 HallucinatingDM

A **self-hosted, LLM-powered multiplayer D&D 5E platform** — think Friends & Fables, but
running on your own hardware with **Ollama** or any OpenAI-compatible API.

One human is the designated DM; unlimited players join from any device with a browser.
The AI can fully run the game, co-pilot alongside the human DM, or just draft suggestions.
Players drop in and out freely and can run **solo side adventures** with the AI DM while
the main table is idle — all in one persistent, shared world.

## Features

- **AI Dungeon Master** — narrates, voices NPCs, adjudicates 5E rules, and *acts* through
  audited server-side tools: it rolls real dice, applies real damage, hands out real loot.
  Streams token-by-token to every connected player.
- **Server-authoritative mechanics** — the LLM can never fabricate a roll. Dice use a
  CSPRNG, every die face is shown to players, modifiers come from the actual character
  sheet, HP/death saves/spell slots/rests are enforced by code.
- **Four DM modes per scene** — `AI runs it` · `Copilot` (big calls need one-click DM
  approval) · `Assist` (every draft approved/edited before players see it) · `Human`
  (AI on demand). Plus private `/whisper` instructions to the AI and a one-click
  **Retcon** that strikes the last AI turn and reverses its state changes.
- **Character creation wizard** — SRD races/subraces/classes/backgrounds, standard
  array/point-buy/server-rolled 4d6, all derived values computed. Or type *"a grumpy
  dwarf cleric who hates the sea"* and let the AI draft a legal build.
- **Persistent world** — NPCs, monsters, locations, factions, quests, and a continuity
  log ("the party burned the mill") are saved as the AI invents them, browsable by
  everyone, and fed back into future prompts. Side adventures see what changed elsewhere.
- **Rules & lore search (RAG)** — the SRD 5.1 ships built-in; the DM can upload PDF
  rulebooks which are chunked, indexed (FTS5 + sqlite-vec hybrid search), and cited by
  the AI when it adjudicates.
- **Combat tracker** — server-rolled initiative, SRD monsters instantiated with real
  stat blocks (`goblin x3`), turn/round tracking, players see monster health as words,
  the DM sees numbers.
- **Character sheets & inventory** — live HP bars, conditions, currency, spell slots,
  XP with level-up flow; every change broadcast instantly over WebSockets.

## Quick start

```bash
git clone <this repo> && cd HallucinatingDM
cp .env.example .env         # set SECRET_KEY!

# with a local LLM (pulls llama3.1 + nomic-embed-text on first run):
docker compose --profile ollama up

# …or point at an existing endpoint (edit LLM_BASE_URL/LLM_API_KEY in .env):
docker compose up
```

Open **http://localhost:8080**, register (the first account becomes the admin), create a
campaign, and share the invite code with your players.

Backups: everything lives in `./data` — `cp data/app.db` is a full backup.

## LLM providers

Any OpenAI-compatible `/v1` endpoint works. Configure via `.env` or the in-app **Admin**
page (which also has a connection test):

| Provider | LLM_BASE_URL | Notes |
|---|---|---|
| Ollama | `http://ollama:11434/v1` (in compose) | default; `llama3.1` + `nomic-embed-text` |
| LM Studio | `http://host.docker.internal:1234/v1` | enable the local server |
| vLLM | `http://your-host:8000/v1` | |
| OpenRouter | `https://openrouter.ai/api/v1` | set `LLM_API_KEY` |
| OpenAI | `https://api.openai.com/v1` | set `LLM_API_KEY` |

**Tool-calling mode** (`auto` by default): capable models use native function calling;
small local models can use `prompted` mode, where tools are called via fenced JSON blocks
with a lenient parser and automatic repair round-trips.

## Development

```bash
# backend (Python 3.11+, uv)
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8080

# frontend (Node 22)
cd frontend && npm install && npm run dev    # Vite on :5173, proxies to :8080

make test        # backend pytest + frontend typecheck/tests
```

The test suite runs entirely against a scripted mock LLM (`LLM_PROVIDER=mock`) — no
model required. See `docs/providers.md` for real-model smoke testing.

## Architecture (short version)

Single-container FastAPI backend (one worker owns the WebSocket hub and the SQLite/WAL
database — no Redis, no Postgres, no vector-DB sidecar; sqlite-vec + FTS5 handle search)
serving the built React frontend from the same origin. Every game mutation flows through
one audited tool layer shared by the REST API and the AI, with inverse patches recorded
for retcon. Full design notes in `docs/`.

## License & attribution

Game content from the **SRD 5.1** by Wizards of the Coast LLC, used under the
**Creative Commons Attribution 4.0** license — see `backend/app/seed/srd/LICENSE.md`.
HallucinatingDM is an independent project, not affiliated with Wizards of the Coast.
