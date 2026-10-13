SHELL := /bin/bash
.DEFAULT_GOAL := help
ENV_FILE ?= $(CURDIR)/.env
COMPOSE := docker compose --env-file "$(ENV_FILE)" -f "$(CURDIR)/compose.yaml"
INFRA_COMPOSE := docker compose --env-file "$(ENV_FILE)" -f "$(CURDIR)/deploy/compose.yaml"
.PHONY: help env bootstrap infra infra-down up docker-env down status logs dev-api dev-web migrate check test generate-api
help:
	@echo "Docker: make up / down / status / logs"
	@echo "Development: make bootstrap / infra / migrate / dev-api / dev-web"
env:
	python3 scripts/env.py
bootstrap: env install-hooks
	uv sync --frozen --directory backend
	pnpm --dir frontend install --frozen-lockfile
docker-env:
	sh scripts/docker-env.sh "$(ENV_FILE)"
up: docker-env
	$(COMPOSE) up --build --detach --wait --wait-timeout 240
infra: env
	pnpm --dir frontend build:identity
	$(INFRA_COMPOSE) up --build --detach --wait --wait-timeout 240
infra-down:
	$(INFRA_COMPOSE) down
down:
	$(COMPOSE) down
status:
	$(COMPOSE) ps --all
logs:
	$(COMPOSE) logs --follow --tail 100 app migrate keycloak
migrate:
	uv run --frozen --directory backend alembic upgrade head
dev-api:
	uv run --frozen --directory backend uvicorn app.main:app --host 127.0.0.1 --port 5195 --reload --no-access-log
dev-web:
	pnpm dev
check: public-check
	uv run --frozen --directory backend ruff check app tests migrations
	uv run --frozen --directory backend ruff format --check app tests migrations
	uv run --frozen --directory backend mypy app
	uv run --frozen --directory backend python ../scripts/export-openapi.py --check
	pnpm check
	pnpm build
test:
	uv run --frozen --directory backend python ../scripts/test-backend.py
generate-api:
	uv run --frozen --directory backend python ../scripts/export-openapi.py
	pnpm --dir frontend exec openapi-typescript ../docs/api/openapi.json -o src/lib/schema.d.ts

.PHONY: cli-bootstrap cli-check cli-test
cli-bootstrap:
	uv sync --frozen --directory cli
cli-check:
	uv run --frozen --directory cli ruff check src tests
	uv run --frozen --directory cli ruff format --check src tests
	uv run --frozen --directory cli mypy src
cli-test:
	uv run --frozen --directory cli pytest -q

# Production server operations always retain all same-origin Compose files.
SERVER_ENV ?= $(CURDIR)/.env.server
SERVER_PYTHON ?= python3
SERVER := $(SERVER_PYTHON) scripts/server.py --env-file "$(SERVER_ENV)"
.PHONY: server-up server-upgrade server-status server-logs server-check server-stop
server-up:
	$(SERVER) up
server-upgrade:
ifdef HOST
	$(SERVER_PYTHON) scripts/server-remote.py --host "$(HOST)" $(if $(REMOTE_PATH),--path "$(REMOTE_PATH)",)
else
	$(SERVER) upgrade $(if $(BUNDLE),--bundle "$(BUNDLE)",)
endif
server-status:
	$(SERVER) status
server-logs:
	$(SERVER) logs
server-check:
	$(SERVER) check
server-stop:
	$(SERVER) stop

.PHONY: public-check install-hooks
public-check:
	python3 scripts/check-public-content.py
install-hooks:
	git config core.hooksPath .githooks
