.PHONY: bootstrap up down test lint typecheck backup smoke health checkpoint orchestrator-watch

UV := uv

bootstrap:
	./scripts/bootstrap.sh

up:
	docker compose up -d postgres
	$(UV) run alembic upgrade head

down:
	docker compose down

test:
	$(UV) run pytest --cov --cov-report=term-missing

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy

backup:
	./scripts/backup.sh

smoke:
	./scripts/smoke_test.sh

health:
	$(UV) run argus health

checkpoint:
	./scripts/checkpoint.sh $(PHASE)

orchestrator-watch:
	$(UV) run python scripts/argus_orchestrator_watch.py
