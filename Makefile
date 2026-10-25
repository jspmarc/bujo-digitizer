.PHONY: deps install-deps dev dev-open migration-new migration-ls migrate test lint fmt build build-docker docker-build docker-run

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
	uv run yoyo list --database "sqlite:///$${SQLITE_PATH:-./bujo_digitizer.sqlite3}"

migrate:
	uv run yoyo apply --batch --database "sqlite:///$${SQLITE_PATH:-./bujo_digitizer.sqlite3}"

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
	docker run --rm -p 8000:8000 --env-file .env bujo-digitizer
