#!/usr/bin/env bash
# Pull code, run the suite, restart. One command, and it REFUSES on a red suite.
#
# Code does not propagate to the server by itself — that was the commander's
# question on 2026-09-02, and the answer is this script.
#
# IT STOPS HOKAGE BEFORE TOUCHING ANYTHING, and that is not politeness. A
# RUNNING Hokage rewrites hokage_brain/portfolio/*.json from memory: on
# 2026-08-26 that silently reverted the CRUDEOIL park within hours and he traded
# a parked asset all day. Any deploy that changes the lineup underneath a live
# process gets undone while reporting success.
#
#   ./deploy/deploy.sh            pull, test, restart
#   ./deploy/deploy.sh --no-test  skip the suite (emergencies only)

set -euo pipefail

ROOT=/opt/hokage
PY=$ROOT/.venv/bin/python
cd "$ROOT"

echo "== current: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

# A deliberate stop, so the liveness probe does not page anyone about a
# migration. The marker is cleared automatically when Hokage is seen up again.
echo "== stopping hokage"
$PY tools/ops/liveness_probe.py --stopped-on-purpose "deploy in progress" || true
sudo systemctl stop hokage || true

echo "== pulling"
git pull --ff-only

if [[ "${1:-}" != "--no-test" ]]; then
  echo "== running the suite"
  if ! $PY -m pytest tests/ -q; then
    echo
    echo "!! TESTS FAILED — NOT restarting. Hokage stays down rather than"
    echo "!! trading on code that cannot prove itself. Fix, or:"
    echo "!!     git reset --hard $(git rev-parse --short HEAD@{1}) && ./deploy/deploy.sh"
    exit 1
  fi
fi

echo "== restarting"
sudo systemctl start hokage
sleep 20

if curl -fsS -m 10 http://127.0.0.1:5000/ >/dev/null 2>&1; then
  echo "== UP: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
  echo "== reminder: the broker token is per-day and still needs a login."
else
  echo "!! dashboard did not answer after 20s — check: journalctl -u hokage -n 50"
  exit 1
fi
