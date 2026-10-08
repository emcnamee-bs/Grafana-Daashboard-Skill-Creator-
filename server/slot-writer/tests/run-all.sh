#!/usr/bin/env bash
# Runs both suites: server unit/HTTP tests (on mini-mac) and the viewer layout tests (headless Chrome, here).
set -u
here="$(cd "$(dirname "$0")" && pwd)"
rc=0
"$here/run-remote.sh" || rc=1
"$here/run-viewer-tests.sh" || rc=1
exit $rc
