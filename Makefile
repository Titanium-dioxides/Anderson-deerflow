# ============================================================================
# archon-deerflow Makefile
# ============================================================================

.PHONY: help dev docker-build docker-up docker-down test lint clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Development ──────────────────────────────────────────────────────────────

dev: ## Start local development server (no Docker)
	chmod +x scripts/dev.sh
	./scripts/dev.sh

test: ## Run all tests
	cd overlay/backend && python3 -m pytest ../../tests/ -q

lint: ## Check Python syntax
	python3 -m py_compile overlay/backend/workflows/*.py

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build: ## Build Docker image
	docker compose build

docker-up: ## Start Docker containers
	docker compose up -d

docker-down: ## Stop Docker containers
	docker compose down

docker-logs: ## Follow gateway logs
	docker compose logs -f gateway

docker-shell: ## Shell into gateway container
	docker compose exec gateway bash

docker-restart: docker-down docker-up ## Restart Docker containers

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean: ## Remove runtime data
	rm -rf data/ workspace/ uploads/ outputs/ .deerflow_runtime/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
