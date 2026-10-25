.PHONY: test deps build

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
	uv run yoyo list

migrate:
	uv run yoyo apply --batch

test:
	uv run pytest

build:
	uv build

build-docker:
	docker build -t bujo-digitizer .

docker-build: build-docker

docker-run:
	docker run --rm -p 8000:8000 --env-file .env bujo-digitizer
