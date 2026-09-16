SHELL := /bin/bash

UV ?= uv
PKG ?= src/originweave
# RUN_DIR is the committed sample fixture read by replay/ui.
# RUNS_DIR is where trace writes runtime runs (gitignored) and never the sample.
RUN_DIR ?= examples/copilot_productivity
DEMO_INPUT ?= examples/copilot_productivity/input/document.md
RUNS_DIR ?= runs
PORT ?= 8765
LIVE ?= 0

.DEFAULT_GOAL := help
.PHONY: help install run demo fixtures test lint fmt ui replay cloc clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

install: ## Sync runtime + dev dependencies into .venv
	$(UV) sync

run: install ## Start the local test env (offline-first; LIVE=1 to hit the network)
	ORIGINWEAVE_LIVE=$(LIVE) $(UV) run originweave ui --run $(RUN_DIR) --port $(PORT)

demo: install ## Run the end-to-end sample (writes to runs/; trace lands in M1)
	ORIGINWEAVE_LIVE=$(LIVE) $(UV) run originweave trace $(DEMO_INPUT) --run $(RUNS_DIR)/demo

fixtures: ## Regenerate the committed sample fixtures (events.jsonl + capability recordings)
	$(UV) run python scripts/build_sample_fixtures.py

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
	rm -rf frontend/dist frontend/node_modules
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
