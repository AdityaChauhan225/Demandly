.PHONY: help seed test bench lint dev-api dev-web build up down

help:
	@echo "Demandly Make Commands:"
	@echo "  make seed       - Generate and ingest events through privacy pipeline"
	@echo "  make test       - Run automated pytest test suite"
	@echo "  make bench      - Execute B0-B4 benchmark matrix and generate results.md"
	@echo "  make lint       - Run ruff code linter"
	@echo "  make dev-api    - Run FastAPI backend development server"
	@echo "  make dev-web    - Run Vite frontend development server"
	@echo "  make build      - Build web production bundle"
	@echo "  make up         - Start full container stack with Docker Compose"
	@echo "  make down       - Stop container stack"

seed:
	python -m ingest.seed --events 100000 --batch-size 25000 --days 14

test:
	pytest -v

bench:
	python -m bench.load_test --events 50000 --queries 100

lint:
	ruff check .

dev-api:
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

dev-web:
	cd web && npm run dev

build:
	cd web && npm run build

up:
	docker compose up -d --build

down:
	docker compose down
