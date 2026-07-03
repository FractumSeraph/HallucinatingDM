# LLM provider matrix & smoke testing

Every provider is consumed through the OpenAI-compatible `/v1/chat/completions`
dialect (streaming + tools) and `/v1/embeddings`. The app never talks to a
provider-specific API.

## Configuration knobs

| Setting | env | admin UI | Notes |
|---|---|---|---|
| Chat endpoint | `LLM_BASE_URL` | ✓ | must end in `/v1` |
| Chat model | `LLM_MODEL` | ✓ | |
| API key | `LLM_API_KEY` | ✓ (encrypted at rest) | `ollama` placeholder is fine locally |
| Tool mode | `LLM_TOOLCALL_MODE` | ✓ | `native` / `prompted` / `auto` |
| Embeddings endpoint | `EMBEDDING_BASE_URL` | ✓ | may differ from chat |
| Embedding model | `EMBEDDING_MODEL` | ✓ | dimension changes need "Rebuild search index" |

## Provider notes

- **Ollama** (≥0.3): first-class. `llama3.1` and up handle native tool calls; smaller
  models (3B class) are better in `prompted` mode. `nomic-embed-text` gets its
  `search_document:`/`search_query:` prefixes automatically.
- **LM Studio**: enable the local server; native tool support depends on the model —
  `auto` mode probes it. From Docker use `http://host.docker.internal:1234/v1`.
- **vLLM**: use `--enable-auto-tool-choice` with a tool parser for native mode,
  otherwise `prompted`.
- **OpenRouter / OpenAI / Anthropic-compatible gateways**: native tools + streaming
  work out of the box.

## Verifying a setup

1. **Admin → Test connection** round-trips one chat message and one embedding and
   reports what worked.
2. Create a solo scene in `AI runs it` mode and say *"I search the room"* — you should
   see streamed narration and (usually) a real dice roll chip.
3. Upload a small PDF on the Search page and ask the AI about its content in play
   (it uses the `lookup` tool with `kind: "book"`).

## Real-model smoke test

CI runs against the scripted mock provider only. To exercise a real local model:

```bash
docker compose --profile ollama up -d
# wait for ollama-init to pull models, then:
LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=llama3.1 \
  EMBEDDING_BASE_URL=http://localhost:11434/v1 \
  make backend   # then play a solo scene in the browser
```

Loose expectations for small models: narration always works; tool-call rate and
argument quality scale with model size. `prompted` mode + the repair loop keeps
7B-class models playable; 3B-class models work but call fewer tools.
