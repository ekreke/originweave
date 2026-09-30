#!/bin/sh
# Entrypoint for the originweave server image (M4).
#
# The server and the worker containers it spawns must agree on the run-dir path, so the
# data root is bound host<->container at the SAME absolute path ($ORIGINWEAVE_DATA_ROOT)
# and the server runs from there. Static assets (prompts / built SPA / default config)
# live read-only under /opt/originweave and are linked/copied in on first boot.
set -eu

ROOT="${ORIGINWEAVE_DATA_ROOT:-/srv/originweave}"
mkdir -p "$ROOT"

[ -e "$ROOT/prompts" ] || ln -s /opt/originweave/prompts "$ROOT/prompts"
if [ ! -e "$ROOT/frontend/dist" ]; then
    mkdir -p "$ROOT/frontend"
    ln -s /opt/originweave/dist "$ROOT/frontend/dist"
fi
[ -e "$ROOT/originweave.toml" ] || cp /opt/originweave/originweave.toml "$ROOT/originweave.toml"

cd "$ROOT"
exec originweave ui --host 0.0.0.0 "$@"
