#!/usr/bin/env bash
# Runs the slot-writer unit tests on mini-mac (this PC has no Python). Usage: tests/run-remote.sh [unittest args, e.g. -k NewFields]
set -u
cd "$(dirname "$0")/.."
files="app.py tests"
[ -f viewer.js ] && files="$files viewer.js"
tar cf - $files | ssh -o BatchMode=yes emac@mini-mac.local 'd=$(mktemp -d) && tar xf - -C "$d" && cd "$d" && python3 -m unittest discover -s tests -v '"$*"'; rc=$?; cd /; rm -rf "$d"; exit $rc'
