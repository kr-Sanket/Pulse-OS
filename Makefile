# PulseOS developer entry points. Run `make help` for a list.
# Conventions: infra runs in Docker; backend/web run on the host during development.

COMPOSE := docker compose -f infra/docker-compose.yml
BACKEND := cd backend && . .venv/bin/activate &&

.DEFAULT_GOAL := help

.PHONY: help env up down logs install install-backend install-web \
	dev-api dev-patient dev-doctor dev-hospital dev-web dev-admin \
	api-client format lint typecheck test ci

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

up: env ## Start local infrastructure (Postgres+pgvector, Redis, MinIO)
	$(COMPOSE) up -d --wait

down: ## Stop local infrastructure (volumes are preserved)
	$(COMPOSE) down

logs: ## Tail infrastructure logs
	$(COMPOSE) logs -f

install: install-backend install-web ## Install all dependencies

install-backend: ## Create backend venv and install dependencies
	cd backend && python3 -m venv .venv && . .venv/bin/activate && \
		pip install --upgrade pip && pip install -e ".[dev]"

install-web: ## Install web workspace dependencies
	cd web && pnpm install

dev-api: ## Run the FastAPI backend with reload (http://localhost:8000)
	$(BACKEND) uvicorn app.main:app --reload

dev-patient: ## Run the patient portal (http://localhost:5173)
	cd web && pnpm dev:patient

dev-doctor: ## Run the doctor portal (http://localhost:5174)
	cd web && pnpm dev:doctor

dev-hospital: ## Run the hospital portal (http://localhost:5175)
	cd web && pnpm dev:hospital

dev-web: ## Run all three portals in one terminal (ports 5173 / 5174 / 5175)
	cd web && pnpm -r --parallel --filter "./apps/*" dev

dev-admin: ## Run the hospital portal for the System Admin verification page
	@echo "System Admin hospital verification: http://localhost:5175/admin/verification"
	@echo "(needs the backend running — make dev-api — and a SYSTEM_ADMIN account)"
	cd web && pnpm dev:hospital

api-client: ## Regenerate web/packages/api-client from the backend OpenAPI spec (ADR-003)
	scripts/generate-api-client.sh

format: ## Auto-format backend and web
	$(BACKEND) ruff format .
	cd web && pnpm format

lint: ## Lint backend and web (matches CI)
	$(BACKEND) ruff format --check . && ruff check .
	cd web && pnpm format:check && pnpm lint

typecheck: ## Static type checks (mypy strict, tsc strict)
	$(BACKEND) mypy
	cd web && pnpm typecheck

test: ## Run all tests
	$(BACKEND) pytest
	cd web && pnpm test

ci: lint typecheck test ## Everything CI runs, locally
