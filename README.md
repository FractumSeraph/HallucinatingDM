# 🦙 Llamas and Labyrinths

A **self-hosted, LLM-powered multiplayer D&D 5E platform** — running on your own hardware with **Ollama** or any OpenAI-compatible API.

One human is the designated DM; unlimited players join from any device with a browser.
The AI can fully run the game, co-pilot alongside the human DM, or just draft suggestions.
Players drop in and out freely and can run **solo side adventures** with the AI DM while
the main table is idle — all in one persistent, shared world.

### How it's built to dodge the usual AI-DM pain points

The common complaints about hosted AI game masters, and how this design answers each:

- **"It costs credits, and combat burns them fast."** Self-hosted on your own model —
  no per-turn credits, no metering, unlimited play. Combat costs nothing extra.
- **"It forgets what happened / needs constant reminding."** Scenes self-summarize, a
  campaign "story so far" rolls up automatically, and every turn keyword-recalls
  relevant past events, chat, and NPCs into the prompt. The DM can pin facts the AI may
  never forget.
- **"You have to already know which die to roll and how to read a 5e sheet."** You never
  pick a die — when a check is needed a **🎲 Roll** button appears and the server applies
  your real modifiers. The AI translates plain words into mechanics, and 💡 suggests
  actions for stuck players.
- **"It railroads you and ignores what you're trying to do."** The DM is instructed to
  pursue the goal the player actually stated and never hijack the scene toward its own
  hook.
- **"It's a repetitive yes-man with no stakes."** Explicit anti-repetition guidance (no
  recurring verbal tics) and a mandate that choices carry real, visible consequences —
  paired with fail-forward so setbacks open new paths.
- **"An AI can't replace a human DM's judgment."** True — so a human can take the wheel
  anytime via Copilot/Assist/Human modes, one-click Retcon, and private `/whisper`
  steering.

## Features

- **AI Dungeon Master** — narrates, voices NPCs, adjudicates 5E rules, and *acts* through
  audited server-side tools: it rolls real dice, applies real damage, hands out real loot.
  Streams token-by-token to every connected player.
- **Server-authoritative mechanics** — the LLM can never fabricate a roll. Dice use a
  CSPRNG, every die face is shown to players, modifiers come from the actual character
  sheet, HP/death saves/spell slots/rests are enforced by code. Players declare
  *attempts*, not outcomes: "I kill the goblin" gets downgraded to a resolved attack,
  and significant gear that isn't on the sheet ("my rocket launcher") simply doesn't
  exist — while improvising with plausible mundane bits (bootlaces, a torn sleeve)
  stays encouraged.
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
  the DM sees numbers. The DM gets quick damage/heal chips on every row and can add
  reinforcements mid-fight.
- **Character sheets & inventory** — live HP bars, one-tap condition add/remove,
  currency, spell-slot spend/restore tracking; every change broadcast instantly over
  WebSockets.
- **Real leveling (SRD 1-20)** — the level-up dialog grants HP and slots, shows each
  new class feature, offers **new spells** per your class's actual progression
  (spellbook growth, known-spell tables, prepared-caster capacity, higher spell
  levels as they unlock), and handles **Ability Score Improvements** at ASI levels —
  with retroactive Constitution HP, all validated server-side.
- **DM table tools** — one-click **short/long rests** (same 5E rules as the AI's rest
  tool), **secret dice rolls** players never see, an **Award XP** panel that announces
  to the table and flags ready level-ups, an editable **"story so far"** (fix the AI's
  memory at the source), and player management (remove a player; their characters are
  retired, not deleted).
- **Party play** — every message shows who's speaking; players running two characters
  pick who talks from a composer selector; items can be **given to party members**
  straight from the inventory; multiplayer rounds gather everyone's action before the
  AI resolves (with Hold to pass and a DM force-resolve for AFK players).
- **Beginner friendly** — a how-to-play primer opens automatically on a player's
  first scene, every rules term has a plain-words tooltip, and a **Beginner table**
  campaign setting makes the AI DM name each check, explain rules as they come up,
  and always offer concrete options. New players can describe a hero in plain words
  and get a complete legal character sheet.

## Setup

All you need is **Docker** (with Compose). For running from source instead, see
[Development](#development).

**1. Clone and configure**

```bash
git clone <this repo> && cd HallucinatingDM   # repo name unchanged
cp .env.example .env
```

Edit `.env` and set `SECRET_KEY` (it signs logins and encrypts stored API keys):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into .env
```

**2. Pick your LLM and start the app**

*Option A — bundled local LLM (no accounts, fully self-hosted).* The `.env`
defaults already point at the bundled Ollama; first start pulls
`qwen3.6:35b-a3b` and `nomic-embed-text` (~24 GB download, one time):

```bash
# CPU only:
docker compose --profile ollama up -d
# with an NVIDIA GPU (needs the NVIDIA Container Toolkit):
docker compose --profile ollama -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

The default model is picked for a **12 GB GPU (e.g. RTX 3060) + 32–64 GB system
RAM**: it's a mixture-of-experts model with only ~3B active parameters, so the
layers that don't fit in VRAM spill to system RAM without killing speed, while
tool-calling quality (the thing this app leans on hardest) stays flagship-class.
The bundled Ollama is preconfigured for a 32k context window so long sessions
don't get silently truncated. Tighter on RAM? Set `LLM_MODEL=qwen3:14b` in
`.env` — it fits entirely in 12 GB VRAM.

*Option B — an endpoint you already have* (OpenCode Go, LM Studio, vLLM,
OpenRouter, OpenAI, a remote Ollama…). Edit `LLM_BASE_URL`, `LLM_MODEL`, and
`LLM_API_KEY` in `.env` (see the [provider table](#llm-providers) below), then:

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

**4. Updating**

```bash
./update.sh                 # plain app
./update.sh --ollama        # if you run the bundled Ollama profile
./update.sh --ollama --gpu  # bundled Ollama with the GPU override
```

One command: it backs up the database to `data/backups/` (keeping the last ten),
pulls the latest code, rebuilds, restarts, and waits for the health check. Your
campaigns are never touched — schema migrations run automatically on boot.

## Running a game (DM guide)

**Table controls at a glance.** In the game view rail: the combat tracker (▶ marks
whose turn it is; −5/−1/+1 chips apply damage or healing; ＋ adds reinforcements) and
⏳ Short / 🌙 Long rest buttons. In the dice bar: a 🤫 toggle makes your rolls secret.
On the DM screen: Award XP, scene prep, pinned facts, content level, and the AI
proposal queue. In the lobby: the invite code and player management.


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
- **⬇ Log** — download the full scene as a readable Markdown transcript (every message
  in order, attributed, with dice results). The DM's export includes whispers and
  DM-only lines; a player's export includes only what they could see. Nothing is ever
  discarded — the complete history always lives in `./data/app.db` too.
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
   - **New to D&D?** Tap **💡** for three ideas that fit the current moment, or **?**
     in the scene header for a one-minute guide. Plain words are always enough — the
     DM translates "I want to sneak past" into the right rules for you.
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
| Ollama | `http://ollama:11434/v1` (in compose) | default; `qwen3.6:35b-a3b` + `nomic-embed-text` |
| OpenCode Go | `https://opencode.ai/zen/go/v1` | hosted open models, $10/mo — see below |
| LM Studio | `http://host.docker.internal:1234/v1` | enable the local server |
| vLLM | `http://your-host:8000/v1` | |
| OpenRouter | `https://openrouter.ai/api/v1` | set `LLM_API_KEY` |
| OpenAI | `https://api.openai.com/v1` | set `LLM_API_KEY` |

**OpenCode Go** is a low-cost subscription (currently $5 first month, then $10/mo)
from the OpenCode team giving flat-rate access to strong open models (Qwen 3.6/3.7,
GLM, Kimi, DeepSeek, MiniMax) through one OpenAI-compatible endpoint — a good
option when local hardware is the bottleneck:

1. Subscribe at [opencode.ai/go](https://opencode.ai/go) and copy your API key
   from OpenCode Zen.
2. In `.env` (or live on the Admin page):
   `LLM_BASE_URL=https://opencode.ai/zen/go/v1`, `LLM_API_KEY=<your key>`,
   `LLM_MODEL=qwen3.6-plus`.
3. Run **Admin → Test connection**. OpenCode Go is chat-only (no embeddings
   endpoint) — the connection test will say so. Either keep the compose ollama
   profile running just for `nomic-embed-text` (leave `EMBEDDING_BASE_URL`
   as-is), or ignore it: rules/lore search automatically falls back to
   keyword-only mode without embeddings.

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
Llamas and Labyrinths is an independent project, not affiliated with Wizards of the Coast.
