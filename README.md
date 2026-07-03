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
- **Long-term memory** — scenes self-summarize as they grow, a campaign-wide "story so
  far" is rolled up automatically, past events/chat/NPCs are retrieved into every AI
  turn, and the DM can **pin facts** the AI must never forget or contradict.
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

## Setup

All you need is **Docker** (with Compose). For running from source instead, see
[Development](#development).

**1. Clone and configure**

```bash
git clone <this repo> && cd HallucinatingDM
cp .env.example .env
```

Edit `.env` and set `SECRET_KEY` (it signs logins and encrypts stored API keys):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into .env
```

**2. Pick your LLM and start the app**

*Option A — bundled local LLM (no GPU config, no accounts).* The `.env` defaults
already point at the bundled Ollama; first start pulls `llama3.1` and
`nomic-embed-text` (several GB, one time):

```bash
docker compose --profile ollama up -d
```

*Option B — an endpoint you already have* (LM Studio, vLLM, OpenRouter, OpenAI, a
remote Ollama…). Edit `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` in `.env`
(see the [provider table](#llm-providers) below), then:

```bash
docker compose up -d
```

**3. First run**

1. Open **http://localhost:8080** (set `PORT` in `.env` to change).
2. **Register** — the first account automatically becomes the **admin**.
3. Visit **Admin** (top-right menu) → **Test connection** to confirm chat + embeddings
   round-trip. Provider settings can also be changed here at runtime, no restart needed.
4. Create a campaign — you're its DM. The **invite code** is on the campaign lobby
   page (only the DM sees it); players register their own accounts and enter it under
   **Join a campaign**.

Everything (SQLite DB + uploaded PDFs) lives in `./data` — copying that folder is a
full backup.

## Running a game (DM guide)

**Campaign & scenes.** Create the campaign (name, description, tone — the AI honors
these), then from the lobby create your first scene. The **main** table is the shared
game; **side** scenes are for splitting the party. Each scene has its own DM mode:

| Mode | What it means |
|---|---|
| **AI runs it** | The AI narrates and acts autonomously; you play or supervise. |
| **Copilot** | The AI runs the scene, but big calls (creating NPCs, quest changes, scene ends, pinned facts…) queue on your DM screen for one-click approval. |
| **Assist** | Every AI narration is a private draft you approve, edit, or reject before players see it. |
| **Human** | You narrate. The AI stays quiet (scene recaps still happen automatically). |

Switch modes anytime from **DM screen → Scenes & AI mode** — e.g. drop to `Copilot`
for a boss negotiation, back to `AI runs it` for travel.

**At the table** (in a scene):

- Type to narrate/speak as the DM; players' messages trigger the AI's turn in AI modes.
- `/whisper <instruction>` — private instruction to the AI ("the innkeeper is the
  cult leader, start dropping hints"). Players never see it.
- `/roll 2d6+3` — server-side dice, visible to all (`4d6kh3` = keep highest 3).
- **✨ Continue** — nudge the AI to keep going without player input.
- **⎌ Retcon** — strike the last AI turn *and* reverse its state changes (HP, items,
  new NPCs…). Follow with a whisper about what should have happened.
- **OOC** checkbox — table talk the AI ignores.

**DM screen** (`lobby → DM screen`) is your control panel:

- **AI proposals** — the approval queue for `Copilot`/`Assist`. Rejections can carry a
  private note the AI reads ("no, make it cheaper").
- **Pinned facts** — facts injected into *every* AI prompt ("Aldric owes the party 50
  gold"). Pin anything the AI must never forget; the AI can also propose pins.
- **World event log** — the campaign's continuity ledger, appended as play happens.
- **Documents** — upload PDF rulebooks/lore; they're indexed for the Search page and
  for the AI's `lookup` tool.

**World page** — browse and edit every NPC, location, faction, and quest the game has
produced. DM-only fields (secrets, hidden twists) stay hidden from players.

**Memory is automatic.** Scenes summarize themselves as they grow; every ~5 scene
recaps the campaign's "story so far" refreshes; each AI turn automatically recalls
relevant old events, dialogue, and entities. Ending a scene (or letting the AI end it)
writes the recap players see under **"Previously on…"** in the lobby.

## Playing (player guide)

1. **Join** — register, then enter the DM's invite code on the Campaigns page.
2. **Make a character** — the wizard walks race → class → background → abilities
   (standard array, point-buy, or server-rolled 4d6) → skills, and computes the rest.
   In a hurry? Type a concept like *"a grumpy dwarf cleric who hates the sea"* and let
   the AI draft a legal build you can tweak.
3. **Play** — open the active scene and say what you do, in character: *"I check the
   door for traps."* The AI narrates the outcome, calls for checks, and applies real
   consequences.
   - When the AI asks for a roll, a **🎲 Roll** button appears — it uses *your* sheet's
     real modifiers.
   - `/roll d20`, `/roll 2d6+3`, `/roll 4d6kh3` for manual dice — every face is shown,
     no fudging (the DM can't fudge either).
   - **OOC** checkbox for table talk; the AI ignores it.
   - You can't be forced: the AI never speaks or decides for your character.
4. **Solo adventures** — from the lobby, start a *solo adventure* anytime. The AI runs
   it, and consequences flow back into the shared world ("meanwhile, elsewhere…").
5. **Your sheet** — live HP, conditions, spell slots, inventory, and currency, updated
   as you play. When you have the XP, a **Level up** button appears.
6. **Catch up** — missed a session? The lobby's **"Previously on…"** card has the story
   so far plus recent scene recaps, and the World page shows everything your party has
   discovered.

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
with a lenient parser and automatic repair round-trips. See `docs/providers.md` for
per-provider notes and a real-model smoke test.

## Troubleshooting

- **The AI never responds** — check the scene isn't in `Human` mode, then run
  **Admin → Test connection**. With the ollama profile, the first startup is still
  pulling models if `docker compose logs ollama-init` shows activity.
- **Narration works but no dice/damage** — the model is skipping tool calls. Try
  `LLM_TOOLCALL_MODE=prompted` (best for ≤7B models) or a larger model.
- **AI "forgot" something important** — pin it: DM screen → Pinned facts.
- **Wrong port / already in use** — set `PORT` in `.env`.

## Development

```bash
# backend (Python 3.11+, uv) — http://localhost:8080
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8080

# frontend (Node 22) — Vite on :5173, proxies /api and /ws to :8080
cd frontend && npm install && npm run dev

make test        # backend pytest + frontend typecheck/tests
make lint        # ruff
```

There's also a hot-reloading Docker setup:
`docker compose -f docker-compose.yml -f docker-compose.dev.yml up`.

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
