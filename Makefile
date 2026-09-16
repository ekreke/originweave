SHELL := /bin/bash

UV ?= uv
PKG ?= src/originweave
# RUN_DIR is the committed sample fixture read by replay/ui.
# RUNS_DIR is where the server writes runtime runs (gitignored), never the sample.
RUN_DIR ?= examples/copilot_productivity
RUNS_DIR ?= runs
PORT ?= 8765
LIVE ?= 0

.DEFAULT_GOAL := help
.PHONY: help install run demo fixtures proto test lint fmt ui replay cloc clean \
	frontend-install frontend-gen frontend-dev frontend-build frontend-lint \
	frontend-typecheck frontend-test

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

install: ## Sync runtime + dev dependencies into .venv
	$(UV) sync

run: install ## Start the local test env (offline-first; LIVE=1 to hit the network)
	ORIGINWEAVE_LIVE=$(LIVE) $(UV) run originweave ui --run $(RUN_DIR) --port $(PORT)

demo: ## End-to-end sample (server + frontend; lands in M4, not wired yet)
	@echo "make demo lands in M4 (server + frontend; see docs/1.0/SPEC.md)."
	@echo "Use 'make replay' for the offline sample."

fixtures: ## Regenerate the committed sample fixtures (events.jsonl + capability recordings)
	$(UV) run python scripts/build_sample_fixtures.py

proto: ## Generate Python from proto/ (server; M1c. Requires buf + protoc-gen-connect-python)
	buf generate proto

frontend-install: ## pnpm install in frontend/
	pnpm --dir frontend install

frontend-gen: ## Generate TypeScript from proto/ (frontend; requires buf)
	pnpm --dir frontend gen

frontend-dev: ## Start the frontend dev server
	pnpm --dir frontend dev

frontend-build: ## Type-check + build the frontend
	pnpm --dir frontend build

frontend-lint: ## ESLint the frontend
	pnpm --dir frontend lint

frontend-typecheck: ## tsc -b --noEmit for the frontend
	pnpm --dir frontend typecheck

frontend-test: ## Vitest for the frontend
	pnpm --dir frontend test

test: install ## Run the test suite
	$(UV) run pytest

lint: install ## Static checks (ruff + mypy)
	$(UV) run ruff check src tests scripts
	$(UV) run mypy src

fmt: install ## Format the code
	$(UV) run ruff format src tests scripts

ui: install ## Serve the read-only run view
	$(UV) run originweave ui --run $(RUN_DIR) --port $(PORT)

replay: install ## Replay a run directory offline (deterministic, no network)
	$(UV) run originweave replay $(RUN_DIR)

cloc: ## Count logical lines under src/originweave (excludes tests/fixtures/generated/vendor)
	@if command -v tokei >/dev/null 2>&1; then \
		tokei $(PKG) --exclude tests --exclude fixtures --exclude generated --exclude vendor; \
	elif command -v cloc >/dev/null 2>&1; then \
		cloc $(PKG) --exclude-dir=tests,fixtures,generated,vendor; \
	else \
		$(UV) run python scripts/cloc.py $(PKG); \
	fi

clean: ## Remove caches and temporary runs
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist runs
	rm -rf frontend/dist frontend/node_modules frontend/src/gen src/originweave/gen
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
