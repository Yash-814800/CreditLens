.PHONY: up down logs test lint fmt seed demo report migrate datagen

up:
	docker compose up --build -d

migrate:
	docker compose exec -T backend alembic upgrade head

down:
	docker compose down

logs:
	docker compose logs -f

datagen:
	rm -rf data/synth data/demo_pack
	cd datagen && uv sync && uv run python -m synthgen.cli all

test:
	docker compose exec -T backend pytest -q
	cd frontend && npm test -- --run
	cd datagen && uv run pytest -q

lint:
	docker compose exec -T backend ruff check .
	cd frontend && npm run lint && npm run typecheck
	cd datagen && uv run ruff check .

fmt:
	docker compose exec -T backend ruff format .
	cd frontend && npm run format
	cd datagen && uv run ruff format .

seed:
	docker compose exec -T backend python -m app.scripts.seed
	docker compose exec -T backend python scripts/seed_history.py

demo:
	@if [ ! -f data/synth/history.parquet ]; then \
		echo "data/synth/history.parquet missing (gitignored, not committed) -- generating synthetic data first..."; \
		$(MAKE) datagen; \
	fi
	$(MAKE) up
	@echo "Waiting for the backend container to report healthy..."
	@for i in $$(seq 1 60); do \
		status="$$(docker compose ps --format '{{.Health}}' backend 2>/dev/null)"; \
		if [ "$$status" = "healthy" ]; then echo "backend is healthy."; break; fi; \
		if [ "$$i" = "60" ]; then echo "backend did not become healthy in time -- check: docker compose logs backend" >&2; exit 1; fi; \
		sleep 2; \
	done
	$(MAKE) seed
	@echo ""
	@echo "CreditLens is up:"
	@echo "  Frontend (underwriter cockpit): http://localhost:8080"
	@echo "  Backend API docs (OpenAPI):     http://localhost:8000/docs"
	@echo ""
	@echo "Demo logins (emails are fixed; passwords come from your local .env, never committed):"
	@echo "  underwriter@creditlens.demo | $$(grep '^DEMO_UNDERWRITER_PASSWORD=' .env | cut -d= -f2-)"
	@echo "  auditor@creditlens.demo     | $$(grep '^DEMO_AUDITOR_PASSWORD=' .env | cut -d= -f2-)"
	@echo "  admin@creditlens.demo       | $$(grep '^DEMO_ADMIN_PASSWORD=' .env | cut -d= -f2-)"

report:
	@echo "Regenerating free/deterministic reports (no LLM spend, run on the host -- these"
	@echo "scripts read data/*.parquet + backend/app/config directly, no DB/container needed)..."
	uv run --project backend python scripts/tier_distribution.py
	uv run --project backend python scripts/calibrate.py
	uv run --project backend python scripts/eval_fraud.py
	uv run --project backend python scripts/validate_scorecard.py
	@if [ -f scripts/fairness_audit.py ]; then uv run --project backend python scripts/fairness_audit.py; fi
	uv run --project backend python scripts/eval_two_signal.py
	python3 scripts/generate_claims_traceability.py
	@echo ""
	@echo "NOT regenerated automatically (each spends a small amount of real Gemini credit):"
	@echo "  uv run --project backend python scripts/eval_extraction.py   # -> docs/extraction_eval.md"
