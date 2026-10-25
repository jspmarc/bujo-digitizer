.PHONY: deps install-deps dev dev-open migration-new migration-ls migrate test lint fmt build build-docker docker-build docker-run docker-down docker-logs

# The migration targets honor SQLITE_PATH. Read it from .env when the shell does
# not already provide it, so `SQLITE_PATH=/x make migrate` still wins.
SQLITE_PATH ?= $(shell sed -n 's/^SQLITE_PATH=//p' .env 2>/dev/null | tail -n 1)
ifeq ($(strip $(SQLITE_PATH)),)
SQLITE_PATH := ./bujo_digitizer.sqlite3
endif
export SQLITE_PATH

deps:
	uv sync

install-deps: deps

dev:
	uv run uvicorn bujo_digitizer:app --reload

dev-open:
	uv run uvicorn bujo_digitizer:app --reload --host 0.0.0.0

migration-new:
	uv run yoyo new --sql

migration-ls:
	uv run yoyo list --database "sqlite:///$(SQLITE_PATH)"

migrate:
	uv run yoyo apply --batch --database "sqlite:///$(SQLITE_PATH)"

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

build:
	uv build

build-docker:
	docker build -t bujo-digitizer .

docker-build: build-docker

docker-run:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app
