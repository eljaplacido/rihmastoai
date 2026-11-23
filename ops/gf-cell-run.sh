#!/bin/bash
# Run one Gnomon cell detached from the operator's session, and only one at a time per workspace.
# Usage: gf-cell-run.sh ID TASK_FILE ROLE [gnomon task flags...]
# Writes /tmp/gf-ID.{started,pid,record.json,stderr,exit}; /tmp/gf-ID.refused if the lock is held.
# Why a lock: two gnomon runs in one workspace see each other's audit writes as record_tamper
# and both stop (2026-11-22). Gnomon rewrites its process title, so pgrep on the command line
# cannot find a running cell; the lock and the pid file can.
# Which Gnomon: $GNOMON_CMD if set (as in kernel/model.py, e.g. GNOMON_CMD=gnomon for an installed
# release), else the source build in ~/src/gnomonharness-master (D-0003). Rihma needs Gnomon 0.6.5
# or later; 0.6.6 is recommended. The build identity is written to the .started file.
set -u
ID="$1"; TASK="$2"; ROLE="$3"; shift 3
exec 9>/tmp/gf-cell.lock
if ! flock -n 9; then
  echo "another cell holds the workspace lock /tmp/gf-cell.lock" > "/tmp/gf-$ID.refused"
  exit 75
fi
cd ~/gnomonfactory || exit 1
if [ -n "$(git status --porcelain)" ]; then
  echo "workspace not clean; refusing to start" > "/tmp/gf-$ID.refused"
  exit 75
fi
source ~/.nvm/nvm.sh >/dev/null 2>&1; nvm use 22 >/dev/null 2>&1
if [ -n "${GNOMON_CMD:-}" ]; then
  read -r -a GN <<< "$GNOMON_CMD"
else
  GN=(node ~/src/gnomonharness-master/packages/gnomon-cli/gnomon.js)
fi
rm -f "/tmp/gf-$ID.exit" "/tmp/gf-$ID.refused"
echo $$ > "/tmp/gf-$ID.pid"
{ date -u +%FT%TZ; git rev-parse --abbrev-ref HEAD; git rev-parse HEAD; "${GN[@]}" --version; } > "/tmp/gf-$ID.started"
"${GN[@]}" task --task-file "$TASK" --role "$ROLE" --json "$@" > "/tmp/gf-$ID.record.json" 2> "/tmp/gf-$ID.stderr"
echo $? > "/tmp/gf-$ID.exit"
