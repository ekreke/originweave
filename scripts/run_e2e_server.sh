#!/usr/bin/env bash
# Boot the fake-provider server that the Playwright e2e drives (M1c-2b 2b-5).
# Runs from the repo root so `uv run` finds the project and the script can import
# `smoke`/`originweave`. Called by frontend/playwright.config.ts (webServer).
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python scripts/e2e_server.py
