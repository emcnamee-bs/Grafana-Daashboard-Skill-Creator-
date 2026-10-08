#!/usr/bin/env bash
# Opens every viewer view for every fixture in headless Chrome and checks layout/behaviour (tests/viewer_harness.html + viewer_frame.html).
# Usage: tests/run-viewer-tests.sh [--shots DIR]     CHROME=path overrides the browser.
# The viewer runs in an iframe of an exact viewport (the harness's ?vp=WxH): 1824x1080 = the wall's 95% frame on a 1080p TV;
# the other sizes prove the views fit any screen.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
CHROME="${CHROME:-/c/Program Files/Google/Chrome/Application/chrome.exe}"
PROF="$(cygpath -m "${TMPDIR:-/tmp}")/wl-chrome-profile"
base="file:///$(cygpath -m "$here")/viewer_harness.html"
shots=""; [ "${1:-}" = "--shots" ] && shots="$2" && mkdir -p "$shots"
fail=0; n=0
run() {  # fx view WxH [flow]
  local fx="$1" view="$2" vp="$3" flow="${4:-}" out res w h win
  w="${vp%x*}"; h="${vp#*x}"; win="$((w + 40)),$((h + 160))"          # the window must be bigger than the iframe (browser chrome eats some of it)
  out="$("$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROF" --window-size="$win" --virtual-time-budget=4000 --dump-dom "$base?fx=$fx&view=$view&vp=$vp&flow=$flow" 2>/dev/null)"
  res="$(printf '%s' "$out" | grep -o 'WLTEST:[A-Z]*' | head -1)"
  n=$((n + 1))
  if [ "$res" != "WLTEST:PASS" ]; then
    fail=$((fail + 1)); echo "FAIL $fx $view $vp flow=$flow: $(printf '%s' "$out" | grep -o 'data-wlfails="[^"]*"' | head -1)"
  fi
  if [ -n "$shots" ]; then
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROF" --window-size="$win" --virtual-time-budget=4000 \
      --screenshot="$(cygpath -m "$shots")/$fx-${view//:/_}-$vp.png" "$base?fx=$fx&view=$view&vp=$vp" >/dev/null 2>&1
  fi
}
for fx in full minimal hostile big; do
  for view in square chart:0 stat:0 health:0 kpi:0:0 health:99 chart:99; do run "$fx" "$view" 1824x1080; done
done
run full stat:3 1824x1080            # a stat with a members list (the 5 containers)
run big stat:0 1824x1080             # 12 members + explain + why
for vp in 1280x720 3840x2160 1000x1000 1920x1080; do
  for view in square chart:0 health:0; do run full "$view" "$vp"; done
  # the maximal tile must fit every 16:9 screen; a square viewport (1000x1000) is not a wall shape and no layout fits that much content there without scrolling
  [ "$vp" != "1000x1000" ] && run big square "$vp"
done
run full square 1824x1080 1
echo "$((n - fail))/$n passed"
[ "$fail" -eq 0 ]
