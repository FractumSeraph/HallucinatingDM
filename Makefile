.PHONY: dev backend frontend test test-backend test-frontend lint migrate revision seed smoke-ollama build up

# --- Development --------------------------------------------------------------
dev: ## run backend (reload) + frontend (vite) — needs two terminals or use &
	$(MAKE) -j2 backend frontend

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8080

frontend:
	cd frontend && npm run dev

# --- Quality -------------------------------------------------------------------
test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -q

test-frontend:
	cd frontend && npm run typecheck && npm test

lint:
	cd backend && uv run ruff check app tests

# --- Database ------------------------------------------------------------------
migrate:
	cd backend && uv run alembic upgrade head

revision:
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

# --- Docker ----------------------------------------------------------------------
build:
	docker compose build

up:
	docker compose up

up-ollama:
	docker compose --profile ollama up

up-ollama-gpu:
	docker compose --profile ollama -f docker-compose.yml -f docker-compose.gpu.yml up

# Smoke test against a real local Ollama (pulls a small model).
smoke-ollama:
	cd backend && LLM_SMOKE=1 uv run pytest -q tests/test_smoke_ollama.py
