# Interactive tiles (hover highlight + full-screen detail views) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every tile on the Grafana wall lights up on hover and opens a full-screen, correctly sized detail view on click (the top bar opens the whole square; a chip, health light, chart or KPI opens just that thing; Esc closes).

**Architecture:** Grafana's HTML sanitizer is switched off on mini-mac so tile HTML can carry hover CSS and click handlers. Each tile embeds a JSON payload (data attribute) and a 1x1 `<img onload>` bootstrap that loads one shared `viewer.js` (served by the slot-writer) which draws the full-screen overlay with DOM/SVG at the real viewport size. The wrapper page holds auto-reloads while an overlay is open. New optional spec fields (`summary`, `explain`, `history`, `detail`, `breakdown`) are written by the skill's agent and the per-project hooks.

**Tech Stack:** Python 3 stdlib (slot-writer, `server/slot-writer/app.py`), vanilla JS (`viewer.js`), PowerShell (client, hooks), Docker Compose on mini-mac, headless Chrome for viewer tests.

**Spec:** `docs/superpowers/specs/2026-10-07-interactive-fullscreen-design.md`

## Refinements to the spec found while planning (flag these to the user at hand-off)

1. **Viewer is served, not inlined.** The spec says the viewer script is "embedded once per page via the bootstrap". This plan serves it as `GET /wall/viewer.js` from the slot-writer (same host, port 8088) and the bootstrap `<img onload>` loads it once per page. Reason: tiles stay small (6 tiles x 25 KB of script would be repeated on every redraw), the file is testable on its own, and a viewer fix needs no tile redraw. It is still one script, installed once, idempotent, and it is our own server (no third-party script).
2. **Hold flag travels by `postMessage`.** The spec says the viewer sets `window.__wallHold`. The Grafana page runs in an iframe on another origin (`:3000` vs the wrapper on `:8088`), so the wrapper cannot read a flag there. The viewer posts `{wallHold: true|false}` to `window.parent`; the wrapper accepts it only from its own current iframe, and auto-releases after 10 minutes so a crashed viewer can never freeze updates.
3. **Hover tips in the tile use native `title` attributes** on each clickable box (no extra icon, so the existing chip-width estimates stay valid); chart boxes get a small `i` icon in their header. Every element inside the full-screen views gets a real `i` icon with an instant custom tooltip.
4. **Tile-level text field is named `summary`** (the spec's "`explain` on the tile (`summary`)").
5. **KPIs are their own click targets** (spec: "each KPI"); hover lights only the innermost box (CSS `:has`).

## Global Constraints

- Sanitizer setting, verbatim: `GF_PANELS_DISABLE_SANITIZE_HTML: "true"` in mini-mac `~/monitoring/docker-compose.yml`, grafana service `environment`, with the compose file backed up first and the grafana container restarted.
- Back up `~/monitoring/slot-writer/app.py` (and `Dockerfile`) on mini-mac before any deploy; the deployed `app.py` is the source of truth.
- Spec text is HTML-escaped by the server. The viewer renders tile text with `textContent` only, never `innerHTML` (the sanitizer is off).
- Palette: dark blue/black/dark grey, white text, blue accent (`CONFIG` in `app.py`; the payload carries the colours to the viewer, so they stay single-sourced).
- Text stays concise: `explain` and `why` capped at 200 and 240 chars, list `what` at 120.
- Commits are local only, authored `emcnamee-bs <224684024+emcnamee-bs@users.noreply.github.com>` (never the BrightSign work email: the repos are public), each ending with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. **Never push** (the user does that); never use the work email.
- Commit command used in every task (call it `GC`):
  `git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "<msg>" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"`
- This PC has no real Python (only the Windows Store stub). Server unit tests run on mini-mac via `server/slot-writer/tests/run-remote.sh`. Viewer tests run locally in headless Chrome (`C:\Program Files\Google\Chrome\Application\chrome.exe`).
- Grafana's sanitizer was the reason for earlier layout rules (explicit sizes, no flex:1/zoom reliance); do not remove them from existing markup.
- ssh user on mini-mac is `emac` (host `mini-mac.local`). Never print the Grafana token or admin password.
- Protected-path note from earlier sessions: `Remove-Item` under `C:\Users\there` is blocked; use `Copy-Item -Force` to overwrite installed copies.

## Review Focus

Failure modes the spec implies but no task would otherwise test, most likely first. Each is pinned by a named test in the task that owns the code.

1. **Hostile or odd text in any spec field** (quotes, `<script>`, `</style>`, `'`, a 200-character unbroken string) must never become live markup anywhere, because the sanitizer is off. Pinned: Task 3 `test_hostile_text_stays_inert`, Task 4 fixture `hostile`.
2. **Every existing tile (a spec with none of the new fields)** must still render, be clickable, and open minimal views without errors. Pinned: Task 3 `test_old_spec_still_renders`, Task 4 fixture `minimal`.
3. **Charts with 0 or 1 points, a history shorter than the tile's points, or all-zero values** must draw ("No data in this window", a single bar/dot) with no NaN or exception. Pinned: Task 4 fixtures `minimal` and `hostile`.
4. **A redraw arriving while an overlay is open, and a viewer that never releases its hold.** The view must survive, the reload must apply after Esc, and the hold must self-release after 10 minutes. Pinned: Task 5 tests plus the Task 9 live check.
5. **Payload growth:** a tile at the validated maximum (4 charts x 400-point histories, 8 lights x 12 items, 6 stats x 12 items) must stay under the body and payload limits and still fit the screen; an oversize tile must give a 400 that says why, not a 500 or a truncated tile. Pinned: Task 2 `BodyLimit`, Task 3 `test_oversize_payload_is_rejected`, Task 4 fixture `big`.

---

## File map

| File | Responsibility |
|---|---|
| `.gitattributes` (new) | Keep `*.py *.js *.html *.sh` as LF in the working tree (files are deployed to Linux and edited with exact-match tools). |
| `server/slot-writer/app.py` | Validation of new fields, tile markup (hover classes, targets, payload, bootstrap), `/wall/viewer.js` route, body limit, wrapper-page hold. |
| `server/slot-writer/viewer.js` (new) | The whole full-screen viewer. Pure DOM/SVG; no network. |
| `server/slot-writer/Dockerfile` | Copy `viewer.js` into the image. |
| `server/slot-writer/tests/test_app.py` (new) | Unit + HTTP tests for the server. |
| `server/slot-writer/tests/run-remote.sh` (new) | Runs those tests on mini-mac. |
| `server/slot-writer/tests/viewer_harness.html`, `fixtures.js`, `run-viewer-tests.sh` (new) | Headless-Chrome checks of every view, fixture and window size. |
| `server/slot-writer/tests/spike_sanitizer.py` (new) | Throwaway-style probe that proves the sanitizer is off (kept for re-checking after Grafana upgrades). |
| `skills/grafana-wall/references/tile-spec.md`, `refresh-hook.md`, `SKILL.md`, `evals/evals.json`, `scripts/wall-refresh.ps1` | Document and merge the new fields; teach the agent to author them. |
| `C:\Users\there\canaries\.grafana-wall\refresh.ps1` (outside the repo) and `examples/mini-mac/refresh.ps1` | Hooks return `summary`/`explain`/`history`/`detail`/`breakdown`. |

---

### Task 0: Branch base, line endings, remote test runner

**Files:**
- Create: `.gitattributes`, `server/slot-writer/tests/test_app.py`, `server/slot-writer/tests/run-remote.sh`
- Modify: `server/slot-writer/app.py` (line endings only)

**Interfaces:**
- Produces: `server/slot-writer/tests/run-remote.sh [unittest args]` (exit code = tests' exit code); `tests/test_app.py` importing `app` with `GRAFANA_TOKEN`/`WALL_KEY` defaulted.

- [ ] **Step 1: Merge the showcase branch (it carries the deployed `app.py`)**

Run from the worktree root:
```bash
git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com merge claude-skills-showcase --no-edit
```
Expected: merge succeeds (this branch only added the spec/plan under `docs/`; no conflicts).

- [ ] **Step 2: Add `.gitattributes` and convert the working copy to LF**

```
*.py text eol=lf
*.js text eol=lf
*.html text eol=lf
*.sh text eol=lf
```
Save as `.gitattributes`, then:
```bash
sed -i 's/\r$//' server/slot-writer/app.py
git status --short
```
Expected: `.gitattributes` is untracked; `app.py` shows **no** modification (the index already holds LF).

- [ ] **Step 3: Confirm the repo's `app.py` equals the deployed one**

```bash
ssh -o BatchMode=yes emac@mini-mac.local 'cat ~/monitoring/slot-writer/app.py' | diff --strip-trailing-cr - server/slot-writer/app.py && echo IDENTICAL
```
Expected: `IDENTICAL`. If it prints a diff, **stop**: the deployed file wins; copy it over `server/slot-writer/app.py` (`ssh ... cat ... > server/slot-writer/app.py`), re-run Step 3, and note it in the commit message.

- [ ] **Step 4: Write the remote runner**

`server/slot-writer/tests/run-remote.sh`:
```bash
#!/usr/bin/env bash
# Runs the slot-writer unit tests on mini-mac (this PC has no Python). Usage: tests/run-remote.sh [unittest args, e.g. -k NewFields]
set -u
cd "$(dirname "$0")/.."
files="app.py tests"
[ -f viewer.js ] && files="$files viewer.js"
tar cf - $files | ssh -o BatchMode=yes emac@mini-mac.local 'd=$(mktemp -d) && tar xf - -C "$d" && cd "$d" && python3 -m unittest discover -s tests -v '"$*"'; rc=$?; cd /; rm -rf "$d"; exit $rc'
```

- [ ] **Step 5: Write the first test (proves the harness works)**

`server/slot-writer/tests/test_app.py`:
```python
import html, json, os, re, sys, threading, unittest
import urllib.error, urllib.request

os.environ.setdefault("GRAFANA_TOKEN", "test-token")
os.environ.setdefault("WALL_KEY", "test-key")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import app


class ValidateBasics(unittest.TestCase):
    def test_minimal_spec_validates(self):
        sp = app.validate({"project": "demo"})
        self.assertEqual(sp["name"], "demo")
        self.assertEqual(sp["status"], "idle")
```

- [ ] **Step 6: Run it**

```bash
chmod +x server/slot-writer/tests/run-remote.sh && server/slot-writer/tests/run-remote.sh
```
Expected: `test_minimal_spec_validates ... ok` and `OK`.

- [ ] **Step 7: Commit**

```bash
git add .gitattributes server/slot-writer/tests && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "Test harness for slot-writer (runs on mini-mac); LF for deployed sources" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Spike - prove interactive HTML works with the sanitizer off (GATE)

**Files:**
- Create: `server/slot-writer/tests/spike_sanitizer.py`
- Modify (on mini-mac, not in repo): `~/monitoring/docker-compose.yml`

**Interfaces:**
- Produces: a verified fact (hover CSS, inline handlers, `data-*` attributes, script injection, body-level overlay, Esc and an external script load all work in a text panel) and the sanitizer left **off** on mini-mac. If this task fails, **stop** and report: the design falls back to approach A (hotspot overlay in the wrapper page) and needs a short re-brainstorm of that part only.

- [ ] **Step 1: Write the probe script**

`server/slot-writer/tests/spike_sanitizer.py`:
```python
#!/usr/bin/env python3
"""Probe: does Grafana render interactive text-panel HTML (needs GF_PANELS_DISABLE_SANITIZE_HTML=true)?
Runs inside the slot-writer container, which holds the Grafana token (never printed):
  ssh emac@mini-mac.local 'docker exec -i slot-writer python - create' < server/slot-writer/tests/spike_sanitizer.py
  ssh emac@mini-mac.local 'docker exec -i slot-writer python - delete' < server/slot-writer/tests/spike_sanitizer.py
The page publishes its self-test result on <html data-spike='{...}'>; read it with headless Chrome --dump-dom."""
import json, os, sys, urllib.request

GRAFANA = os.environ.get("GRAFANA_URL", "http://grafana:3000")
TOKEN = os.environ["GRAFANA_TOKEN"]
UID = "wall-spike"

CONTENT = """<style>.sp{cursor:pointer;border:1px solid #1f5fae}.sp:hover{border-color:#4da3ff!important;background:rgba(77,163,255,.2)!important}</style>
<div class='sp' id='spk' style='padding:20px;color:#fff' onclick="window.__spikeClicked=1">SPIKE BOX - hover me</div>
<div id='spd' data-wl-data='{&quot;a&quot;:1}'></div>
<img alt='' width='1' height='1' style='display:none' src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7' onload="(function(){var r={};var s=document.createElement('script');s.textContent='window.__spikeScript=1';document.head.appendChild(s);r.script=window.__spikeScript===1?1:0;document.getElementById('spk').click();r.click=window.__spikeClicked===1?1:0;try{r.data=JSON.parse(document.getElementById('spd').getAttribute('data-wl-data')).a===1?1:0}catch(e){r.data=0}var o=document.createElement('div');o.id='spk-ov';o.style.cssText='position:fixed;left:0;top:0;right:0;bottom:0;z-index:99999;background:#123';document.body.appendChild(o);var q=o.getBoundingClientRect();r.overlayFull=(Math.abs(q.width-innerWidth)<2&&Math.abs(q.height-innerHeight)<2)?1:0;document.addEventListener('keydown',function(e){if(e.key==='Escape'){var x=document.getElementById('spk-ov');if(x)x.remove()}},true);document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));r.escape=document.getElementById('spk-ov')?0:1;r.hoverRule=0;for(var i=0;i<document.styleSheets.length;i++){try{var rs=document.styleSheets[i].cssRules;for(var j=0;j<rs.length;j++){if(rs[j].selectorText&&rs[j].selectorText.indexOf('.sp:hover')>=0)r.hoverRule=1}}catch(e){}}function pub(){document.documentElement.setAttribute('data-spike',JSON.stringify(r))}pub();var e2=document.createElement('script');e2.src=location.protocol+'//'+location.hostname+':8088/health';e2.onload=function(){r.ext=1;pub()};e2.onerror=function(){r.ext=0;pub()};document.head.appendChild(e2)})()">"""


def call(method, path, body=None):
    req = urllib.request.Request(GRAFANA + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode() or "{}")


if sys.argv[1:] == ["create"]:
    d = {"uid": UID, "title": UID, "schemaVersion": 39, "time": {"from": "now-1h", "to": "now"},
         "panels": [{"id": 1, "type": "text", "title": "", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 10},
                     "options": {"mode": "html", "content": CONTENT}}]}
    print(call("POST", "/api/dashboards/db", {"dashboard": d, "overwrite": True, "message": "sanitizer spike"})["status"], "/d/%s" % UID)
elif sys.argv[1:] == ["delete"]:
    print(call("DELETE", "/api/dashboards/uid/" + UID))
else:
    sys.exit("usage: python - create|delete")
```

- [ ] **Step 2: Create the scratch dashboard (sanitizer still ON: negative control)**

```bash
ssh -o BatchMode=yes emac@mini-mac.local 'docker exec -i slot-writer python - create' < server/slot-writer/tests/spike_sanitizer.py
```
Expected: `success /d/wall-spike`.

- [ ] **Step 3: Run the check; expect NO result (control)**

```bash
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"
PROF="$(cygpath -m "${TMPDIR:-/tmp}")/wl-chrome-profile"
"$CHROME" --headless=new --disable-gpu --user-data-dir="$PROF" --window-size=1824,1080 --virtual-time-budget=20000 --dump-dom "http://mini-mac.local:3000/d/wall-spike?kiosk&theme=dark" 2>/dev/null | grep -o 'data-spike="[^"]*"' || echo "no data-spike (sanitizer on, as expected)"
```
Expected: `no data-spike (sanitizer on, as expected)`. If a result **does** appear, the sanitizer was already off: continue, but note it.

- [ ] **Step 4: Verify Grafana's data is on a persistent volume before restarting it**

```bash
ssh -o BatchMode=yes emac@mini-mac.local "docker inspect grafana --format '{{json .Mounts}}'"
```
Expected: a mount whose `Destination` is `/var/lib/grafana`. If there is none, **stop** (recreating the container would lose the wall dashboards) and tell the user.

- [ ] **Step 5: Back up the compose file and add the setting**

```bash
ssh -o BatchMode=yes emac@mini-mac.local 'cd ~/monitoring && cp docker-compose.yml docker-compose.yml.bak-pre-sanitize-$(date +%Y%m%d-%H%M%S) && sed -i "/GF_SECURITY_ALLOW_EMBEDDING/a\\      GF_PANELS_DISABLE_SANITIZE_HTML: \"true\"" docker-compose.yml && grep -n "GF_" docker-compose.yml && docker compose config -q && echo COMPOSE-OK'
```
Expected: the new line sits under the other `GF_` lines with the same 6-space indent, then `COMPOSE-OK`. If the indent is wrong, restore from the backup and edit by hand.

- [ ] **Step 6: Restart Grafana (a few seconds of blank wall; kiosk refresh recovers it)**

```bash
ssh -o BatchMode=yes emac@mini-mac.local 'cd ~/monitoring && docker compose up -d grafana && sleep 15 && curl -s http://localhost:3000/api/health'
```
Expected: JSON with `"database": "ok"`.

- [ ] **Step 7: Run the check again; expect every probe to be 1**

Same command as Step 3.
Expected: `data-spike="{&quot;script&quot;:1,&quot;click&quot;:1,&quot;data&quot;:1,&quot;overlayFull&quot;:1,&quot;escape&quot;:1,&quot;hoverRule&quot;:1,&quot;ext&quot;:1}"` (key order may differ).
**Gate:** if `script`, `click` or `data` is 0 or missing, stop here and report. If only `ext` is 0, check that `http://mini-mac.local:8088/health` answers from the Grafana page's host (port 8088 reachable) before deciding.

- [ ] **Step 8: Delete the scratch dashboard, confirm the wall is intact, commit**

```bash
ssh -o BatchMode=yes emac@mini-mac.local 'docker exec -i slot-writer python - delete' < server/slot-writer/tests/spike_sanitizer.py
powershell.exe -NoProfile -File "$HOME/.claude/skills/grafana-wall/scripts/wall.ps1" slots
git add server/slot-writer/tests/spike_sanitizer.py && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "Spike: prove interactive text-panel HTML works with the sanitizer off" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected: the delete prints a "deleted" message; `wall.ps1 slots` lists the occupied/vacant slots exactly as before (the client reads its key from `~/.grafana-wall.json` and never prints it).

---

### Task 2: Validate the new spec fields; raise the body limit

**Files:**
- Modify: `server/slot-writer/app.py` (helpers after `_num`; `validate`; `_body`; constants)
- Test: `server/slot-writer/tests/test_app.py`

**Interfaces:**
- Produces (used by Tasks 3-5): validated spec keys
  - tile: `sp["summary"]` (text ≤240 or `None`)
  - each `sp["stats"][i]` and `sp["health"][i]`: `explain` (≤200 or `None`), `detail` (`None` or `{"why": text|None, "items": [{"name","state","what"}]}`, ≤12 items)
  - each points chart `ch`: `explain`, `history` (`None` or list of `(t, v)` float tuples, ≤400), `history_label` (≤8, `""` default), `breakdown` (`None` or `{"ok_pct"?, "err_pct"?, "total"?, "worst": [{"label","value"}]}`); each `ch["kpis"][j]` gains `explain`
  - constants `app.MAX_BODY = 262144`, `app.MAX_PAYLOAD = 120000`, config `CONFIG["viewer_port"] = 8088`
- Consumes: existing `_s(v, field, n, required)`, `_num(v, field)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_app.py`)

```python
class ServerCase(unittest.TestCase):
    """Real HTTP server on an ephemeral port; Grafana is pointed at a closed port so anything past request parsing fails fast."""
    @classmethod
    def setUpClass(cls):
        app.CONFIG["grafana_url"] = "http://127.0.0.1:9"
        cls.srv = app.ThreadingHTTPServer(("127.0.0.1", 0), app.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def request(self, method, path, body=None, headers=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


class BodyLimit(ServerCase):
    def post(self, size):
        body = json.dumps({"project": "demo", "pad": "x" * size}).encode()
        return self.request("POST", "/snapshot?dry=1", body, {"X-Wall-Key": app.KEY, "Content-Type": "application/json"})

    def test_100kb_body_is_accepted(self):
        code, _, body = self.post(100000)
        self.assertNotIn(b"too large", body)

    def test_300kb_body_is_rejected_with_a_reason(self):
        code, _, body = self.post(300000)
        self.assertEqual(code, 400)
        self.assertIn(b"too large", body)


class NewFields(unittest.TestCase):
    def v(self, **kw):
        d = {"project": "demo"}
        d.update(kw)
        return app.validate(d)

    def chart(self, **kw):
        c = {"title": "Errors", "points": [[1, 0], [2, 3]]}
        c.update(kw)
        return c

    def test_explain_detail_and_summary_pass_through(self):
        sp = self.v(summary="what this tile is",
                    stats=[{"label": "Containers", "value": "5", "explain": "Docker containers",
                            "detail": {"why": "4 of 5 healthy", "items": [{"name": "grafana", "state": "up", "what": "dashboards"}]}}],
                    health=[{"name": "API", "state": "up", "explain": "health endpoint answers"}])
        self.assertEqual(sp["summary"], "what this tile is")
        self.assertEqual(sp["stats"][0]["detail"]["items"][0], {"name": "grafana", "state": "up", "what": "dashboards"})
        self.assertEqual(sp["stats"][0]["detail"]["why"], "4 of 5 healthy")
        self.assertEqual(sp["health"][0]["explain"], "health endpoint answers")
        self.assertIsNone(sp["health"][0]["detail"])

    def test_old_spec_still_valid_with_empty_new_fields(self):
        sp = self.v(stats=[{"label": "PRs", "value": "1"}], health=[{"name": "CI", "state": "up"}], charts=[self.chart()])
        self.assertIsNone(sp["summary"])
        self.assertIsNone(sp["stats"][0]["explain"]); self.assertIsNone(sp["stats"][0]["detail"])
        ch = sp["charts"][0]
        self.assertIsNone(ch["explain"]); self.assertIsNone(ch["history"]); self.assertIsNone(ch["breakdown"]); self.assertEqual(ch["history_label"], "")

    def test_chart_history_breakdown_and_kpi_explain(self):
        sp = self.v(charts=[self.chart(explain="failed runs", history=[[1, 0], [2, 1], [3, 2]], history_label="7d",
                                       breakdown={"ok_pct": 99.5, "err_pct": 0.5, "total": 1840, "worst": [{"label": "Tue 14:00", "value": "3 err"}]},
                                       kpis=[{"label": "ERR 7D", "value": "0.5%", "state": "ok", "explain": "seven day error rate"}])])
        ch = sp["charts"][0]
        self.assertEqual(ch["history"], [(1.0, 0.0), (2.0, 1.0), (3.0, 2.0)])
        self.assertEqual(ch["history_label"], "7d")
        self.assertEqual(ch["breakdown"], {"ok_pct": 99.5, "err_pct": 0.5, "total": 1840.0, "worst": [{"label": "Tue 14:00", "value": "3 err"}]})
        self.assertEqual(ch["kpis"][0]["explain"], "seven day error rate")

    def test_bad_detail_item_state_is_rejected_by_name(self):
        with self.assertRaisesRegex(ValueError, r"stats\.detail\.items\.state"):
            self.v(stats=[{"label": "x", "value": "1", "detail": {"items": [{"name": "a", "state": "great"}]}}])

    def test_more_than_12_detail_items_rejected(self):
        items = [{"name": "i%d" % n, "state": "up"} for n in range(13)]
        with self.assertRaisesRegex(ValueError, r"health\.detail\.items"):
            self.v(health=[{"name": "a", "state": "up", "detail": {"items": items}}])

    def test_history_over_400_points_rejected(self):
        with self.assertRaisesRegex(ValueError, r"charts\.history"):
            self.v(charts=[self.chart(history=[[i, 0] for i in range(401)])])

    def test_breakdown_percent_out_of_range_rejected(self):
        with self.assertRaisesRegex(ValueError, r"charts\.breakdown\.ok_pct"):
            self.v(charts=[self.chart(breakdown={"ok_pct": 101})])

    def test_breakdown_worst_entries_must_be_objects(self):
        with self.assertRaisesRegex(ValueError, r"charts\.breakdown\.worst"):
            self.v(charts=[self.chart(breakdown={"worst": ["Tue"]})])

    def test_text_fields_are_capped(self):
        sp = self.v(summary="s" * 500, stats=[{"label": "x", "value": "1", "explain": "e" * 500, "detail": {"why": "w" * 500, "items": []}}])
        self.assertEqual(len(sp["summary"]), 240)
        self.assertEqual(len(sp["stats"][0]["explain"]), 200)
        self.assertEqual(len(sp["stats"][0]["detail"]["why"]), 240)
```

- [ ] **Step 2: Run to confirm they fail**

```bash
server/slot-writer/tests/run-remote.sh -k NewFields -k BodyLimit
```
Expected: FAIL. The `NewFields` tests fail (no `summary`/`explain`/`detail`/`history` keys yet) and `test_100kb_body_is_accepted` fails (the old 64 KB limit answers `body too large`). `test_300kb_body_is_rejected_with_a_reason` already passes; that is fine, it guards against raising the limit too far.

- [ ] **Step 3: Add constants and helpers**

In `app.py`, next to `SLUG = ...` add:
```python
MAX_BODY = 262144          # request body cap: a tile may now carry chart history and detail lists
MAX_PAYLOAD = 120000       # cap on the JSON embedded in one tile (see tile_payload)
```
In `CONFIG`, add after the `"units"` entry: `"viewer_port": 8088,                      # slot-writer's own port: the tile bootstrap loads /wall/viewer.js from it`.

Insert after `def _num(...)`:
```python
def _points(pts, field, maxn):
    """[[t, v], ...] or [{"t":..,"v":..}, ...] -> [(t, v), ...] as floats; ValueError names the field."""
    if not isinstance(pts, list) or len(pts) > maxn:
        raise ValueError("%s: list of at most %d points" % (field, maxn))
    out = []
    for p in pts:
        t, v = (p.get("t"), p.get("v")) if isinstance(p, dict) else (p[0], p[1]) if isinstance(p, (list, tuple)) and len(p) == 2 else (None, None)
        out.append((_num(t, field + ".t"), _num(v, field + ".v")))
    return out


def _detail(d, field):
    """Optional drill-down for a stat or health light: {"why": text, "items": [{name, state, what}]}; None when empty."""
    if d is None:
        return None
    if not isinstance(d, dict):
        raise ValueError("%s must be an object" % field)
    items = d.get("items") or []
    if not isinstance(items, list) or len(items) > 12:
        raise ValueError("%s.items: list of at most 12 entries" % field)
    out_items = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("%s.items entries must be objects" % field)
        st = _s(it.get("state"), field + ".items.state", 10) or "unknown"
        if st not in CONFIG["health_colors"]:
            raise ValueError("%s.items.state must be one of %s" % (field, sorted(CONFIG["health_colors"])))
        out_items.append({"name": _s(it.get("name"), field + ".items.name", 24, True), "state": st, "what": _s(it.get("what"), field + ".items.what", 120)})
    why = _s(d.get("why"), field + ".why", 240)
    if not why and not out_items:
        return None
    return {"why": why, "items": out_items}


def _breakdown(b, field):
    """Optional chart numbers a hook precomputed: {ok_pct, err_pct, total, worst: [{label, value}]}."""
    if b is None:
        return None
    if not isinstance(b, dict):
        raise ValueError("%s must be an object" % field)
    out = {}
    for k in ("ok_pct", "err_pct"):
        if b.get(k) is not None:
            v = _num(b[k], "%s.%s" % (field, k))
            if not 0 <= v <= 100:
                raise ValueError("%s.%s must be between 0 and 100" % (field, k))
            out[k] = v
    if b.get("total") is not None:
        out["total"] = _num(b["total"], field + ".total")
    worst = b.get("worst") or []
    if not isinstance(worst, list) or len(worst) > 5 or not all(isinstance(w, dict) for w in worst):
        raise ValueError("%s.worst: list of at most 5 objects" % field)
    out["worst"] = [{"label": _s(w.get("label"), field + ".worst.label", 24, True), "value": _s(w.get("value"), field + ".worst.value", 12, True)} for w in worst]
    return out
```

- [ ] **Step 4: Wire the helpers into `validate`**

(If the merged file differs slightly from these anchors, apply the same change to the equivalent line.)

1. After `out["task"] = _s(spec.get("task"), "task", 90)` add:
```python
    out["summary"] = _s(spec.get("summary"), "summary", 240)
```
2. Health entry: replace
`out["health"].append({"name": _s(h.get("name"), "health.name", 18, True), "state": st})` with
```python
        out["health"].append({"name": _s(h.get("name"), "health.name", 18, True), "state": st,
                              "explain": _s(h.get("explain"), "health.explain", 200), "detail": _detail(h.get("detail"), "health.detail")})
```
3. Stats: in the dict inside the `out["stats"] = [...]` comprehension, change the closing of the dict
`... if _s(x.get("trend"), "stats.trend", 5) in ("up", "down", "flat") else None}` to
```python
... if _s(x.get("trend"), "stats.trend", 5) in ("up", "down", "flat") else None,
                     "explain": _s(x.get("explain"), "stats.explain", 200), "detail": _detail(x.get("detail"), "stats.detail")}
```
4. Points chart: replace the block from `if not isinstance(pts, list) or len(pts) > 200:` through the `norm.append(...)` loop (ending before `kind = _s(c.get("kind")...`) with:
```python
            norm = _points(pts, "charts.points", 200)
```
5. KPI dict: add `"explain": _s(k.get("explain"), "charts.kpis.explain", 200)` as a fourth key of the `kpis.append({...})`.
6. Chart dict (`out["charts"].append({"title": title, "points": norm, ...`): add before the closing brace:
```python
, "explain": _s(c.get("explain"), "charts.explain", 200),
                                  "history": _points(c["history"], "charts.history", 400) if c.get("history") is not None else None,
                                  "history_label": _s(c.get("history_label"), "charts.history_label", 8) or "",
                                  "breakdown": _breakdown(c.get("breakdown"), "charts.breakdown")
```
7. Series (legacy) chart dict: add `"explain": None, "history": None, "history_label": "", "breakdown": None` so every chart has the keys.

- [ ] **Step 5: Raise the body limit**

In `_body`, replace
```python
        if n > 65536:
            raise ValueError("body too large (64KB max)")
```
with
```python
        if n > MAX_BODY:
            raise ValueError("body too large (%dKB max)" % (MAX_BODY // 1024))
```

- [ ] **Step 6: Run the tests**

```bash
server/slot-writer/tests/run-remote.sh
```
Expected: all tests `ok`, `OK`.

- [ ] **Step 7: Commit**

```bash
git add server/slot-writer && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "slot-writer: validate summary/explain/history/detail/breakdown; raise body limit to 256KB" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tile markup - hover targets, payload, bootstrap

**Files:**
- Modify: `server/slot-writer/app.py` (new helpers before `tile_v2_html`; replace `tile_v2_html`)
- Test: `server/slot-writer/tests/test_app.py`

**Interfaces:**
- Consumes: Task 2 validated fields (`explain`, `detail`, `history`, `breakdown`, `summary`).
- Produces (used by Task 4): in the tile HTML the root `<div>` carries `data-wl-data='<escaped JSON>'` with this payload shape (the viewer reads exactly this):
```
{ colors:{status:{ok,warn,fail,idle,building}, health:{up,degraded,down,unknown}, accent, text, muted},
  name, status, status_label, branch, activity, task, summary,
  stats:[{label,value,trend,explain,detail}], health:[{name,state,explain,detail}],
  charts:[{title,subtitle,kind,y_max,span_label,points,history,history_label,kpis:[{label,value,state,explain}],explain,breakdown}] }
```
  where `detail` is `null | {why, items:[{name,state,what}]}`, `points`/`history` are `[[t,v],...]`, `breakdown` is `null | {ok_pct?,err_pct?,total?,worst:[{label,value}]}`.
  Click targets are the strings `square`, `stat:<i>`, `health:<i>`, `chart:<i>`, `kpi:<chartIndex>:<kpiIndex>`; each clickable box carries `class='wl-t'`, `data-wl='<target>'`, a `title` tooltip and `onclick="event.stopPropagation();window.wallOpen&&wallOpen(this,'<target>')"`.
  Tile also contains `<style>` (hover CSS) and a 1x1 `<img onload>` that loads `http(s)://<host>:8088/wall/viewer.js` once (`if(!window.wallOpen)`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_app.py`)

```python
def payload_of(page):
    m = re.search(r"data-wl-data='([^']*)'", page)
    assert m, "no data-wl-data attribute"
    return json.loads(html.unescape(m.group(1)))


class TileMarkup(unittest.TestCase):
    def sp(self, **kw):
        d = {"project": "demo", "name": "Demo", "summary": "A demo tile",
             "stats": [{"label": "Containers", "value": "5", "explain": "Docker containers running",
                        "detail": {"why": "4 of 5 healthy", "items": [{"name": "grafana", "state": "up", "what": "dashboards"}]}}],
             "health": [{"name": "API", "state": "up", "explain": "health endpoint answers"}],
             "charts": [{"title": "Errors", "points": [[1, 0], [2, 3]], "explain": "Failed runs per bucket",
                         "kpis": [{"label": "ERR 7D", "value": "1%", "explain": "seven day error rate"}]}]}
        d.update(kw)
        return app.validate(d)

    def test_every_clickable_box_has_a_target(self):
        page = app.tile_v2_html(self.sp())
        for t in ("square", "stat:0", "health:0", "chart:0", "kpi:0:0"):
            self.assertIn("data-wl='%s'" % t, page)
            self.assertIn("wallOpen(this,'%s')" % t, page)
        self.assertIn("click for details", page)
        self.assertIn("Docker containers running", page)       # explain becomes the hover tip

    def test_hover_css_lights_only_the_innermost_box(self):
        page = app.tile_v2_html(self.sp())
        self.assertIn(".wl-t:hover", page)
        self.assertIn(":has(.wl-t:hover)", page)

    def test_bootstrap_loads_the_viewer_once(self):
        page = app.tile_v2_html(self.sp())
        self.assertIn("if(!window.wallOpen)", page)
        self.assertIn(":8088/wall/viewer.js", page)

    def test_payload_round_trips(self):
        p = payload_of(app.tile_v2_html(self.sp()))
        self.assertEqual(p["name"], "Demo")
        self.assertEqual(p["summary"], "A demo tile")
        self.assertEqual(p["stats"][0]["detail"]["items"][0]["name"], "grafana")
        self.assertEqual(p["charts"][0]["kpis"][0]["explain"], "seven day error rate")
        self.assertEqual(p["colors"]["accent"], app.CONFIG["accent"])
        self.assertEqual(p["charts"][0]["points"], [[1.0, 0.0], [2.0, 3.0]])

    def test_hostile_text_stays_inert(self):
        bad = "\"'><img src=x onerror=alert(1)></style><script>alert(2)</script>"
        page = app.tile_v2_html(self.sp(name=bad, summary=bad))
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("</style><script", page)
        self.assertEqual(payload_of(page)["summary"], bad[:240])     # intact inside the attribute

    def test_old_spec_still_renders(self):
        old = app.validate({"project": "old", "charts": [{"title": "T", "points": [[1, 1]]}], "stats": [{"label": "A", "value": "1"}],
                            "health": [{"name": "X", "state": "up"}]})
        page = app.tile_v2_html(old)
        self.assertIn("data-wl='square'", page)
        self.assertIsNone(payload_of(page)["stats"][0]["explain"])

    def test_oversize_payload_is_rejected(self):
        old = app.MAX_PAYLOAD
        app.MAX_PAYLOAD = 200
        try:
            with self.assertRaisesRegex(ValueError, "tile detail too large"):
                app.tile_v2_html(self.sp())
        finally:
            app.MAX_PAYLOAD = old

    def test_render_tile_uses_the_interactive_template(self):
        panels, lay = app.render_tile(1, 0, self.sp())
        self.assertIn("wl-t", panels[0]["options"]["content"])
        self.assertEqual(lay["template"], "v2")
```

- [ ] **Step 2: Run to confirm they fail**

```bash
server/slot-writer/tests/run-remote.sh -k TileMarkup
```
Expected: FAIL (`data-wl-data` missing, `tile_v2_html` has no targets).

- [ ] **Step 3: Add the helpers** (place directly above `def tile_v2_html`)

```python
WL_CSS = ("<style>.wl-t{cursor:pointer;transition:border-color .15s,background-color .15s,box-shadow .15s}"
          ".wl-t:hover{border-color:#4da3ff!important;background:rgba(77,163,255,.20)!important;box-shadow:0 0 14px rgba(77,163,255,.5)}"
          ".wl-t:has(.wl-t:hover):hover{border-color:#1f5fae!important;background:rgba(31,95,174,.10)!important;box-shadow:none}</style>")


def tgt(target, tip=None):
    """Attributes that make a tile box a hover/click target of the full-screen viewer.
    target: square | stat:i | health:i | chart:i | kpi:i:j. The tip (the item's explain text) is the native hover tooltip."""
    t = esc((tip + " \u2014 " if tip else "") + "click for details")
    return (" class='wl-t' data-wl='%s' title='%s' onclick=\"event.stopPropagation();window.wallOpen&&wallOpen(this,'%s')\""
            % (esc(target), t, esc(target)))


def boot_html():
    """1x1 image whose onload installs the viewer script once per page (scripts inside innerHTML do not run, image handlers do)."""
    return ("<img alt='' width='1' height='1' style='display:none' src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7' "
            "onload=\"if(!window.wallOpen){var s=document.createElement('script');"
            "s.src=location.protocol+'//'+location.hostname+':%d/wall/viewer.js';document.head.appendChild(s)}\">" % CONFIG["viewer_port"])


def tile_payload(sp):
    """Everything the full-screen viewer needs, embedded in the tile so a click needs no network call. Plain data only."""
    c = CONFIG
    act = sp["activity"]["state"] + (" \u00b7 " + sp["activity"]["label"] if sp["activity"]["label"] else "")
    return {
        "colors": {"status": c["status_colors"], "health": c["health_colors"], "accent": c["accent"], "text": c["text"], "muted": c["muted"]},
        "name": sp["name"], "status": sp["status"], "status_label": sp["status_label"] or sp["status"], "branch": sp["branch"],
        "activity": act, "task": sp["task"], "summary": sp.get("summary"),
        "stats": [{"label": s["label"], "value": s["value"], "trend": s["trend"], "explain": s.get("explain"), "detail": s.get("detail")} for s in sp["stats"]],
        "health": [{"name": h["name"], "state": h["state"], "explain": h.get("explain"), "detail": h.get("detail")} for h in sp["health"]],
        "charts": [{"title": ch["title"], "subtitle": ch["subtitle"], "kind": ch["kind"], "y_max": ch["y_max"], "span_label": ch["span_label"],
                    "points": ch["points"], "history": ch.get("history"), "history_label": ch.get("history_label") or "", "kpis": ch["kpis"],
                    "explain": ch.get("explain"), "breakdown": ch.get("breakdown")} for ch in sp["charts"]],
    }


def payload_attr(sp):
    """The payload as an HTML-attribute-safe string (ASCII-only JSON, then HTML-escaped incl. quotes)."""
    raw = json.dumps(tile_payload(sp), separators=(",", ":"), ensure_ascii=True)
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("tile detail too large (%d bytes, max %d): shorten history, detail or explain text" % (len(raw), MAX_PAYLOAD))
    return esc(raw)
```

- [ ] **Step 4: Replace `tile_v2_html` with this version** (same layout maths and look as before; additions are the target attributes, `i` icon, root attribute, `<style>` and bootstrap)

```python
def tile_v2_html(sp):
    """Fixed template: a top bar (name, status, git branch, activity, quick stats, key-part health, current task) over a landscape row of
    2-3 equal charts, each with its own KPI chips. Every item has its own border. All sizing is explicit because Grafana's sanitizer
    drops flex:1 / zoom / overflow-style tricks. Every box is also a hover/click target of the full-screen viewer (see tgt)."""
    c = CONFIG
    charts = sp["charts"]; n = len(charts)
    line = "1px solid #1f5fae"; muted = c["muted"]
    sc = c["status_colors"][sp["status"]]
    label = esc((sp["status_label"] or sp["status"]).upper())
    ac = c["activity_colors"][sp["activity"]["state"]]
    alab = esc(sp["activity"]["state"] + (" \u00b7 " + sp["activity"]["label"] if sp["activity"]["label"] else ""))
    chip = "display:inline-block;padding:3px 10px;border-radius:12px;background:rgba(77,163,255,.10);border:1px solid rgba(77,163,255,.35);font-size:14px;margin:0 6px 6px 0;"
    box = "box-sizing:border-box;border:%s;border-radius:8px;background:rgba(31,95,174,.10);" % line

    # ---- top bar
    chips = ["<span style='%s;color:%s'>&#9095; %s</span>" % (chip, muted, esc(sp["branch"][:24])),
             "<span style='%s;color:%s'><span style='color:%s'>&#9679;</span> %s</span>" % (chip, muted, ac, alab)]
    for i, s in enumerate(sp["stats"]):
        arrow = {"up": " <span style='color:#3fb950'>&#9650;</span>", "down": " <span style='color:#f85149'>&#9660;</span>"}.get(s["trend"], "")
        chips.append("<span%s style='%s'><b style='font-size:16px'>%s</b>%s <span style='font-size:11px;letter-spacing:.08em;color:%s'>%s</span></span>"
                     % (tgt("stat:%d" % i, s.get("explain")), chip, esc(s["value"]), arrow, muted, esc(s["label"].upper())))
    pills = "".join("<span%s style='display:inline-block;margin:0 6px 6px 0;padding:3px 9px;%sfont-size:14px'><span style='color:%s'>&#9679;</span> %s</span>"
                    % (tgt("health:%d" % i, h.get("explain")), box, c["health_colors"][h["state"]], esc(h["name"])) for i, h in enumerate(sp["health"]))
    task = ""
    if sp["task"]:
        t = sp["task"]
        t = (t[:51].rstrip() + "\u2026") if len(t) > 52 else t
        task = ("<div style='%spadding:5px 10px;font-size:14px'><span style='color:%s;letter-spacing:.12em;font-size:11px'>NOW</span>&nbsp; %s</div>" % (box, muted, esc(t)))
    # estimate how many rows the wrapping chips / pills need from their text widths (~7px per character + padding)
    avail = CARD_INNER_PX - 24
    chip_w = [len(sp["branch"][:24]) * 7 + 40, len(sp["activity"]["state"]) * 7 + len(sp["activity"]["label"] or "") * 7 + 50] + \
             [(len(s["value"]) * 9 + len(s["label"]) * 7 + 44) for s in sp["stats"]]
    pill_w = [len(h["name"]) * 7.5 + 46 for h in sp["health"]]
    rows_for = lambda widths: max(1, int(math.ceil(sum(widths) / float(avail)))) if widths else 0
    chip_rows, pill_rows = rows_for(chip_w), rows_for(pill_w)
    px = 58 + 36 * chip_rows + 36 * pill_rows + (38 if sp["task"] else 0) + 10
    top_pct = min(max(int(round(px / TILE_PX * 100)), 38), 58)
    chart_pct = 100 - top_pct - 2
    top = ("<div style='height:%d%%'>"
           "<div%s style='%spadding:6px 12px;display:flex;align-items:center;justify-content:space-between'>"
           "<div style='font-size:26px;font-weight:700;letter-spacing:.02em'>%s</div>"
           "<div style='padding:4px 14px;border-radius:14px;background:%s;color:#fff;font-size:14px;font-weight:700;letter-spacing:.12em'>%s</div></div>"
           "<div style='margin-top:8px'>%s</div><div>%s</div>%s</div>"
           % (top_pct, tgt("square", sp.get("summary")), box, esc(sp["name"][:22]), sc, label, "".join(chips), pills, task))

    # ---- charts row
    chart_px = TILE_PX * chart_pct / 100.0
    box_w = (CARD_INNER_PX - 8 * (n - 1)) / float(n)
    state_col = {"ok": "#3fb950", "warn": "#d29922", "bad": "#f85149"}
    cols = []
    for ci, ch in enumerate(charts):
        has_k = bool(ch["kpis"])
        img_h = max(int(chart_px - 16 - 2 - 34 - (40 if has_k else 0) - 18 - 14), 50)
        img_w = max(int(box_w - 18 - 20), 60)          # 20px left for the y-axis labels
        img, ymax = spark_img(ch["points"], ch["kind"], img_w, img_h, ch.get("y_max"))
        vals = [p[1] for p in ch["points"]]
        icon = ("<span title='%s' style='color:%s;font-size:12px;line-height:13px;cursor:help'>&#9432;</span>" % (esc(ch["explain"]), muted)) if ch.get("explain") else ""
        head = ("<div style='display:flex;justify-content:space-between;align-items:baseline'>"
                "<div style='font-size:13px;font-weight:700;letter-spacing:.06em'>%s</div>%s</div>"
                "<div style='font-size:10px;color:%s;min-height:12px'>%s</div>" % (esc(ch["title"].upper()), icon, muted, esc(ch["subtitle"])))
        kp = ""
        if has_k:
            kp = "<div style='display:flex;gap:6px;margin:4px 0'>" + "".join(
                "<div%s style='%swidth:calc((100%% - 6px) / 2);padding:2px 7px'><div style='font-size:10px;letter-spacing:.1em;color:%s'>%s</div>"
                "<div style='font-size:16px;font-weight:700;color:%s'>%s</div></div>"
                % (tgt("kpi:%d:%d" % (ci, ki), k.get("explain")), box, muted, esc(k["label"].upper()), state_col.get(k["state"], c["text"]), esc(k["value"]))
                for ki, k in enumerate(ch["kpis"])) + "</div>"
        axis = ("<div style='display:flex;gap:4px'><div style='width:16px;height:%dpx;display:flex;flex-direction:column;justify-content:space-between;text-align:right;font-size:10px;color:%s'>"
                "<span>%g</span><span>%g</span><span>0</span></div><img src='%s' style='display:block;width:calc(100%% - 20px);height:%dpx'></div>" % (img_h, muted, ymax, ymax / 2.0, img, img_h)) if img else None
        body = axis if img else \
               ("<div style='height:%dpx;color:%s;font-size:13px;text-align:center;padding-top:%dpx'>no data</div>" % (img_h, muted, img_h // 2 - 8))
        foot = ("<div style='display:flex;justify-content:space-between;font-size:10px;color:%s;margin-top:2px'><span>-%s</span><span>max %s</span><span>now</span></div>"
                % (muted, esc(ch["span_label"] or ""), ("%g" % round(max(vals), 2)) if vals else "-"))
        cols.append("<div%s style='%swidth:calc((100%% - %dpx) / %d);height:100%%;padding:8px'>%s%s%s%s</div>" % (tgt("chart:%d" % ci, ch.get("explain")), box, 8 * (n - 1), n, head, kp, body, foot))
    row = "<div style='display:flex;gap:8px;height:%d%%;margin-top:2%%'>%s</div>" % (chart_pct, "".join(cols))

    return ("<div data-wl-data='%s' style='box-sizing:border-box;height:100%%;padding:12px 14px;border:%s;border-radius:%s;box-shadow:%s;background:%s;"
            "font-family:Inter,sans-serif;color:%s'>%s%s%s%s</div>"
            % (payload_attr(sp), c["border"], c["radius"], c["glow"], c["card_bg"], c["text"], WL_CSS, boot_html(), top, row))
```
(If the merged `tile_v2_html` differs from the version in `main` that this replaces, keep any intentional upstream change and re-apply only the additions listed above.)

- [ ] **Step 5: Run the tests**

```bash
server/slot-writer/tests/run-remote.sh
```
Expected: all `ok`.

- [ ] **Step 6: Commit**

```bash
git add server/slot-writer && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "Tiles: hover/click targets, embedded payload and viewer bootstrap" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The viewer, its route, and headless-Chrome layout tests

**Files:**
- Create: `server/slot-writer/viewer.js`, `server/slot-writer/tests/viewer_harness.html`, `server/slot-writer/tests/fixtures.js`, `server/slot-writer/tests/run-viewer-tests.sh`
- Modify: `server/slot-writer/app.py` (`viewer_js`, route), `server/slot-writer/Dockerfile`
- Test: `server/slot-writer/tests/test_app.py` (`ViewerRoute`)

**Interfaces:**
- Consumes: the Task 3 payload shape and the targets `square`, `stat:i`, `health:i`, `chart:i`, `kpi:i:j`.
- Produces: `window.wallOpen(node, target)` (reads the `data-wl-data` of `node.closest('[data-wl-data]')`), `window.wallShow(data, target)` (test entry), `window.wallClose()`; DOM markers `[data-wl-overlay]` (overlay root), `[data-wl-click]` (clickable cards), `[data-wl-btn]` (buttons), `[data-wl-i]` (info icons), `[data-wl-tip]` (floating tip); posts `{wallHold: true|false}` to `window.parent` on open/close. An unknown or out-of-range target falls back to the square view; any exception closes the overlay and releases the hold.

- [ ] **Step 1: Write the route test (fails first)** (append to `tests/test_app.py`)

```python
class ViewerRoute(ServerCase):
    def test_viewer_js_is_served_without_a_key(self):
        code, headers, body = self.request("GET", "/wall/viewer.js")
        self.assertEqual(code, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/javascript"))
        self.assertTrue(body.startswith(b"/* Wall full-screen viewer"))
```

- [ ] **Step 2: Write the test fixtures**

`server/slot-writer/tests/fixtures.js`:
```js
/* Sample tile payloads (same shape as app.tile_payload) used by viewer_harness.html. */
(function () {
  var COL = { status: { ok: '#2f81f7', warn: '#d29922', fail: '#f85149', idle: '#6e7681', building: '#58a6ff' },
              health: { up: '#3fb950', degraded: '#d29922', down: '#f85149', unknown: '#6e7681' }, accent: '#4da3ff', text: '#e8eefc', muted: '#8fa6c8' };
  var NOW = 1791400000;
  function series(n, step, f) { var a = []; for (var i = 0; i < n; i++) a.push([NOW - (n - 1 - i) * step, f(i)]); return a; }
  function kpis() { return [{ label: 'ERR 7D', value: '0.5%', state: 'ok', explain: 'Share of runs in the last 7 days that ended in an error.' }, { label: 'STREAK', value: '128', state: null, explain: null }]; }
  function chart(title, kind, f, extra) {
    var c = { title: title, subtitle: 'errors / 30 min', kind: kind, y_max: null, span_label: '12h', points: series(24, 1800, f), history: null, history_label: '',
              kpis: kpis(), explain: title + ' canary: failed runs per 30 minutes.', breakdown: null };
    for (var k in (extra || {})) c[k] = extra[k];
    return c;
  }
  function members(n) { var a = []; for (var i = 0; i < n; i++) a.push({ name: 'container-' + (i + 1), state: i % 5 === 4 ? 'degraded' : 'up', what: 'Does thing number ' + (i + 1) + ' for the host' }); return a; }
  function health(n, withDetail) { var a = []; for (var i = 0; i < n; i++) a.push({ name: 'Part ' + (i + 1), state: ['up', 'degraded', 'down', 'unknown'][i % 4], explain: 'Part ' + (i + 1) + ' answers its health check.', detail: withDetail ? { why: 'Needs a look.', items: members(12) } : null }); return a; }

  var full = { colors: COL, name: 'Canaries', status: 'warn', status_label: '5 FAILING', branch: 'main', activity: 'idle \u00b7 16d+',
    task: 'PR #44: Add HTTP notice intake to failure-log-capture', summary: 'Always-on checks that provision, update and play content on test players.',
    stats: [
      { label: 'Failures 24h', value: '7', trend: null, explain: 'Failed canary runs in the last 24 hours.', detail: { why: 'Mostly Update probes.', items: [] } },
      { label: 'Checks failing', value: '5', trend: 'up', explain: 'Checks reporting consecutive errors.', detail: null },
      { label: 'Open PRs', value: '1', trend: null, explain: null, detail: null },
      { label: 'Containers', value: '5', trend: null, explain: 'Docker containers on the host.', detail: { why: '4 of 5 healthy', items: members(5) } }],
    health: health(4, false).map(function (h, i) { if (i === 3) h.detail = { why: '2 canaries report consecutive failures.', items: [] }; return h; }),
    charts: [
      chart('Provisioning', 'bar', function (i) { return i % 7 === 3 ? 2 : 0; },
            { history: series(56, 10800, function (i) { return i % 9 === 4 ? 3 : 0; }), history_label: '7d',
              breakdown: { ok_pct: 99.5, err_pct: 0.5, total: 1840, worst: [{ label: 'Tue 14:00', value: '3 err' }, { label: 'Wed 02:00', value: '3 err' }] } }),
      chart('Update', 'bar', function (i) { return i % 3 === 0 ? 4 : 1; }, { history: series(56, 10800, function (i) { return (i * 7) % 5; }), history_label: '7d' }),
      chart('Content', 'line', function (i) { return 10 + (i % 6); })] };

  var minimal = { colors: COL, name: 'Old tile', status: 'idle', status_label: 'idle', branch: '-', activity: 'idle', task: null, summary: null,
    stats: [], health: [], charts: [{ title: 'One point', subtitle: '', kind: 'line', y_max: null, span_label: '12h', points: [[NOW, 1]], history: null, history_label: '', kpis: [], explain: null, breakdown: null }] };

  var bad = '"\'><img src=x onerror=alert(1)></style><script>alert(2)</script>';
  var hostile = { colors: COL, name: bad, status: 'fail', status_label: bad, branch: 'x'.repeat(200), activity: bad, task: bad, summary: bad,
    stats: [{ label: bad, value: bad, trend: 'down', explain: bad, detail: { why: bad, items: [{ name: bad, state: 'down', what: bad }] } }],
    health: [{ name: 'y'.repeat(200), state: 'down', explain: bad, detail: { why: 'z'.repeat(240), items: members(12) } }],
    charts: [{ title: 'a'.repeat(200), subtitle: bad, kind: 'bar', y_max: null, span_label: bad, points: [], history: [], history_label: '', kpis: [{ label: bad, value: bad, state: 'bad', explain: bad }], explain: bad, breakdown: { worst: [{ label: bad, value: bad }] } },
             { title: 'zeros', subtitle: '', kind: 'bar', y_max: null, span_label: '12h', points: series(24, 1800, function () { return 0; }), history: series(5, 3600, function () { return 0; }), history_label: '7d', kpis: [], explain: null, breakdown: { ok_pct: 100, err_pct: 0, worst: [] } }] };

  var big = { colors: COL, name: 'Maximum tile', status: 'warn', status_label: '9 DEGRADED', branch: 'feature/a-fairly-long-branch-name', activity: 'active \u00b7 now',
    task: 'A long current task description that goes on for quite a while to stress the left column of the square view',
    summary: 'A long summary of what this tile is and why it exists, written to be as wordy as the validated limits allow so the layout has to cope with a maximal amount of text in the left column.',
    stats: [0, 1, 2, 3, 4, 5].map(function (i) { return { label: 'Stat ' + i, value: String(1000 + i), trend: i % 2 ? 'up' : null, explain: 'Explains stat ' + i + '.', detail: { why: 'Because.', items: members(12) } }; }),
    health: health(8, true),
    charts: [0, 1, 2, 3].map(function (i) { return chart('Chart ' + i, i % 2 ? 'line' : 'bar', function (k) { return (k * (i + 3)) % 7; }, { history: series(400, 1800, function (k) { return (k * (i + 2)) % 9; }), history_label: '7d', breakdown: { ok_pct: 97.25, err_pct: 2.75, total: 123456, worst: [1, 2, 3, 4, 5].map(function (w) { return { label: 'Mon 0' + w + ':00', value: w + ' err' }; }) } }); }) };

  window.FIXTURES = { full: full, minimal: minimal, hostile: hostile, big: big };
})();
```

- [ ] **Step 3: Write the harness**

`server/slot-writer/tests/viewer_harness.html`:
```html
<!doctype html><meta charset="utf-8"><title>harness</title>
<style>html,body{margin:0;background:#111217}</style>
<script>var alerted = false; window.alert = function () { alerted = true; };</script>
<script src="../viewer.js"></script>
<script src="fixtures.js"></script>
<script>
window.addEventListener('load', function () {
  var q = new URLSearchParams(location.search), fx = q.get('fx') || 'full', view = q.get('view') || 'square', flow = q.get('flow');
  var holds = [], fails = [];
  window.addEventListener('message', function (e) { if (e.data && typeof e.data.wallHold === 'boolean') holds.push(e.data.wallHold); });
  function check(ok, msg) { if (!ok) fails.push(msg); }
  function overlay() { return document.querySelector('[data-wl-overlay]'); }
  wallShow(FIXTURES[fx], view);
  setTimeout(function () {
    var ov = overlay();
    check(!!ov, 'overlay present');
    if (ov) {
      check(ov.scrollWidth <= ov.clientWidth + 1 && ov.scrollHeight <= ov.clientHeight + 1, 'overlay overflows its viewport');
      var bad = 0;
      ov.querySelectorAll('*').forEach(function (n) {
        var r = n.getBoundingClientRect();
        if (r.width && r.height && (r.right > innerWidth + 1 || r.bottom > innerHeight + 1 || r.left < -1 || r.top < -1)) bad++;
      });
      check(bad === 0, bad + ' elements outside the window');
      ov.querySelectorAll('svg').forEach(function (s) { check(s.getBoundingClientRect().width >= 200, 'chart narrower than 200px'); });
      check(!ov.querySelector('img,script,iframe'), 'tile text became markup');
      check(!/NaN|undefined|Infinity/.test(ov.textContent), 'NaN/undefined/Infinity in the view');
    }
    check(!alerted, 'injected script ran');
    check(holds.length > 0 && holds[holds.length - 1] === true, 'hold not announced');
    if (flow && ov) {
      // tooltips first, while the square view (icons + charts) is open
      var icon = ov.querySelector('[data-wl-i]');
      check(!!icon, 'square view has no info icons');
      if (icon) { icon.dispatchEvent(new MouseEvent('mouseenter')); check(!!document.querySelector('[data-wl-tip]'), 'info icon shows no tooltip'); icon.dispatchEvent(new MouseEvent('mouseleave')); check(!document.querySelector('[data-wl-tip]'), 'tooltip stuck after mouseleave'); }
      var svg = ov.querySelector('svg');
      check(!!svg, 'square view has no chart');
      if (svg) { var r = svg.getBoundingClientRect(); svg.dispatchEvent(new MouseEvent('mousemove', { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, bubbles: true })); check(!!document.querySelector('[data-wl-tip]'), 'chart hover shows no tooltip'); svg.dispatchEvent(new MouseEvent('mouseleave')); }
      // clicking a card opens another view, with navigation buttons
      var cards = ov.querySelectorAll('[data-wl-click]');
      check(cards.length > 0, 'no clickable cards in the square view');
      if (cards.length) {
        cards[0].click();
        var ov2 = overlay();
        check(!!ov2 && ov2 !== ov, 'clicking a card did not open another view');
        check(!!(ov2 && ov2.querySelector('[data-wl-btn]')), 'no back/close buttons');
      }
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      check(!overlay(), 'Escape did not close the overlay');
      check(holds[holds.length - 1] === false, 'hold not released on close');
    }
    document.documentElement.setAttribute('data-wlfails', fails.join(' | '));
    document.title = 'WLTEST:' + (fails.length ? 'FAIL' : 'PASS');
  }, 400);
});
</script>
```

- [ ] **Step 4: Write the viewer**

`server/slot-writer/viewer.js`:
```js
/* Wall full-screen viewer. Served by slot-writer at /wall/viewer.js; each tile's bootstrap loads it once per Grafana page.
 * Tile text is untrusted and Grafana's HTML sanitizer is off on this wall, so everything is built with DOM APIs and textContent
 * (never innerHTML). Charts are real SVG drawn at the overlay's pixel size and redrawn on resize, which is what makes every view fit. */
(function () {
  if (window.wallOpen) return;
  var NS = 'http://www.w3.org/2000/svg';
  var D = null, cur = null, overlay = null, stack = [], observers = [], tipEl = null;

  // ---------------------------------------------------------------- helpers
  function el(tag, css, text, parent) {
    var e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text !== null && text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function sv(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function col() { return D.colors; }
  function hold(on) { try { window.parent.postMessage({ wallHold: !!on }, '*'); } catch (e) { /* standalone page */ } }
  function fmtV(v) { return String(Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 100) / 100); }
  function pct(v) { return (Math.round(v * 10) / 10) + '%'; }
  function fmtT(t, spanS) {
    var d = new Date(t * 1000), p = function (n) { return (n < 10 ? '0' : '') + n; };
    return spanS > 2 * 86400 ? (d.getMonth() + 1) + '/' + d.getDate() : p(d.getHours()) + ':' + p(d.getMinutes());
  }
  function niceMax(v) {
    var n = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 100000, 1000000];
    for (var i = 0; i < n.length; i++) if (v <= n[i]) return n[i];
    return Math.ceil(v);
  }
  function kpiColor(s) { return s === 'bad' ? col().health.down : s === 'warn' ? col().health.degraded : s === 'ok' ? col().health.up : col().text; }

  // ---------------------------------------------------------------- tooltips, icons, cards
  function hideTip() { if (tipEl) { tipEl.remove(); tipEl = null; } }
  function floatTip(text, x, y) {
    hideTip();
    tipEl = el('div', 'position:fixed;z-index:2147483600;left:0;top:0;max-width:34vw;padding:.8vh .9vw;border-radius:8px;background:#0b1830;border:1px solid ' + col().accent +
      ';color:' + col().text + ';font:1.9vh/1.35 Inter,"Segoe UI",Arial,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.6);pointer-events:none;overflow-wrap:anywhere', text, document.body);
    tipEl.setAttribute('data-wl-tip', '1');
    var w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    tipEl.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
    tipEl.style.top = Math.max(8, Math.min(y, window.innerHeight - h - 8)) + 'px';
  }
  function tip(node, text) {
    if (!text) return;
    node.addEventListener('mouseenter', function () { var r = node.getBoundingClientRect(); floatTip(text, r.left, r.bottom + 6); });
    node.addEventListener('mouseleave', hideTip);
  }
  function icon(parent, text) {
    var i = el('span', 'display:inline-flex;align-items:center;justify-content:center;width:2.4vh;height:2.4vh;flex:none;border-radius:50%;border:1px solid ' + col().muted +
      ';color:' + col().muted + ';font-size:1.6vh;font-weight:700;cursor:help', 'i', parent);
    i.setAttribute('data-wl-i', '1');
    tip(i, text);
    return i;
  }
  function card(parent, css, onClick) {
    var b = el('div', 'box-sizing:border-box;border:1px solid #1f5fae;border-radius:10px;background:rgba(31,95,174,.10);padding:1.2vh 1.2vw;transition:all .15s;' + (css || ''), null, parent);
    if (onClick) {
      b.style.cursor = 'pointer';
      b.setAttribute('data-wl-click', '1');
      b.addEventListener('mouseenter', function () { b.style.borderColor = col().accent; b.style.background = 'rgba(77,163,255,.20)'; b.style.boxShadow = '0 0 14px rgba(77,163,255,.5)'; });
      b.addEventListener('mouseleave', function () { b.style.borderColor = '#1f5fae'; b.style.background = 'rgba(31,95,174,.10)'; b.style.boxShadow = 'none'; });
      b.addEventListener('click', function (e) { e.stopPropagation(); onClick(); });
    }
    return b;
  }
  function btn(parent, text, fn) {
    var b = el('div', 'flex:none;padding:.8vh 1.2vw;border:1px solid #1f5fae;border-radius:8px;font-size:2vh;letter-spacing:.1em;color:' + col().muted + ';cursor:pointer;transition:all .15s', text, parent);
    b.setAttribute('data-wl-btn', '1');
    b.addEventListener('mouseenter', function () { b.style.borderColor = col().accent; b.style.color = col().text; });
    b.addEventListener('mouseleave', function () { b.style.borderColor = '#1f5fae'; b.style.color = col().muted; });
    b.addEventListener('click', function (e) { e.stopPropagation(); fn(); });
    return b;
  }
  function section(parent, text) { return el('div', 'flex:none;font-size:1.7vh;letter-spacing:.16em;color:' + col().muted, text, parent); }
  function label(parent, text) { return el('div', 'font-size:1.6vh;letter-spacing:.12em;color:' + col().muted, text, parent); }

  // ---------------------------------------------------------------- frame / lifecycle
  function frame(title, sub, pillColor, pillText) {
    close(true);
    overlay = el('div', 'position:fixed;left:0;top:0;right:0;bottom:0;z-index:2147483000;box-sizing:border-box;padding:2.4vh 2.2vw;display:flex;flex-direction:column;gap:1.8vh;' +
      'overflow:hidden;overflow-wrap:anywhere;background:linear-gradient(165deg,#050c16,#0a1626);color:' + col().text + ';font-family:Inter,"Segoe UI",Arial,sans-serif', null, document.body);
    overlay.setAttribute('data-wl-overlay', '1');
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    var head = el('div', 'flex:none;display:flex;align-items:center;gap:1.4vw;min-width:0', null, overlay);
    if (stack.length) btn(head, '\u2190 BACK', function () { show(D, stack.pop(), false); });
    el('div', 'font-size:4.2vh;font-weight:700;letter-spacing:.02em;min-width:0;max-height:10vh;overflow:hidden', title, head);
    if (pillText) el('div', 'flex:none;padding:.5vh 1.2vw;border-radius:2.4vh;background:' + pillColor + ';color:#fff;font-size:2.2vh;font-weight:700;letter-spacing:.12em;max-width:30vw;overflow:hidden', pillText, head);
    if (sub) el('div', 'font-size:2.2vh;color:' + col().muted + ';min-width:0;max-height:6vh;overflow:hidden', sub, head);
    el('div', 'flex:1', null, head);
    btn(head, 'ESC  \u2715', close);
    return el('div', 'flex:1;min-height:0;display:flex;gap:1.6vw', null, overlay);
  }
  function close(keep) {
    observers.forEach(function (o) { o.disconnect(); });
    observers = [];
    hideTip();
    if (overlay) { overlay.remove(); overlay = null; }
    if (!keep) { stack = []; cur = null; hold(false); }
  }
  function show(data, target, push) {
    D = data;
    if (push && cur) stack.push(cur);
    cur = target;
    hold(true);
    try { render(target); } catch (e) { cur = null; close(); if (window.console) console.error('wall viewer', e); }
  }
  function render(t) {
    var p = String(t).split(':'), k = p[0], i = +p[1], j = +p[2];
    if (k === 'chart' && D.charts[i]) return chartView(i);
    if (k === 'stat' && D.stats[i]) return itemView('stat', D.stats[i]);
    if (k === 'health' && D.health[i]) return itemView('health', D.health[i]);
    if (k === 'kpi' && D.charts[i] && D.charts[i].kpis[j]) return itemView('kpi', D.charts[i].kpis[j], D.charts[i]);
    return squareView();
  }

  // ---------------------------------------------------------------- charts
  function summarize(pts) {
    if (!pts || !pts.length) return null;
    var s = { n: pts.length, sum: 0, max: -Infinity, min: Infinity, zero: 0, last: pts[pts.length - 1][1] };
    pts.forEach(function (p) { var v = p[1]; s.sum += v; if (v > s.max) s.max = v; if (v < s.min) s.min = v; if (v === 0) s.zero++; });
    s.avg = s.sum / s.n; s.zeroPct = 100 * s.zero / s.n;
    return s;
  }
  function worst(pts, k) {
    return pts.map(function (p) { return { t: p[0], v: p[1] }; }).filter(function (x) { return x.v > 0; })
      .sort(function (a, b) { return b.v - a.v || b.t - a.t; }).slice(0, k);
  }
  function drawChart(area, pts, ch) {
    var c = col(), wrap = el('div', 'position:relative;width:100%;height:100%', null, area);
    function paint() {
      hideTip();
      while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
      var W = wrap.clientWidth, H = wrap.clientHeight;
      if (W < 60 || H < 40) return;
      if (!pts || !pts.length) { el('div', 'position:absolute;left:0;top:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;color:' + c.muted + ';font-size:2.2vh', 'No data in this window', wrap); return; }
      var padL = 56, padR = 10, padT = 10, padB = 28, pw = W - padL - padR, ph = H - padT - padB;
      var vals = pts.map(function (p) { return p[1]; }), top = Math.max.apply(null, vals), n = pts.length, bar = ch.kind === 'bar';
      var ymax = ch.y_max ? (top <= ch.y_max ? ch.y_max : niceMax(top)) : niceMax(Math.max(top * 1.05, 1e-9));
      var X = function (i) { return padL + (bar ? pw * (i + 0.5) / n : (n === 1 ? pw / 2 : pw * i / (n - 1))); };
      var Y = function (v) { return padT + ph * (1 - Math.min(v, ymax) / ymax); };
      var svg = sv('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H }, wrap);
      svg.style.cssText = 'position:absolute;left:0;top:0;display:block';
      for (var g = 0; g <= 4; g++) {
        var gy = padT + ph * g / 4;
        sv('line', { x1: padL, x2: W - padR, y1: gy, y2: gy, stroke: g === 4 ? '#2a4a7a' : '#1d3050' }, svg);
        sv('text', { x: padL - 8, y: gy + 4, 'text-anchor': 'end', fill: c.muted, 'font-size': 13 }, svg).textContent = fmtV(ymax * (1 - g / 4));
      }
      var span = pts[n - 1][0] - pts[0][0];
      for (var k = 0; k <= 4 && n > 1; k++) {
        var xi = Math.round((n - 1) * k / 4);
        sv('text', { x: X(xi), y: H - 8, 'text-anchor': k === 0 ? 'start' : k === 4 ? 'end' : 'middle', fill: c.muted, 'font-size': 13 }, svg).textContent = fmtT(pts[xi][0], span);
      }
      if (bar) {
        var bw = Math.max(pw / n * 0.7, 1.5);
        pts.forEach(function (p, i) { if (p[1] > 0) sv('rect', { x: X(i) - bw / 2, y: Y(p[1]), width: bw, height: Math.max(padT + ph - Y(p[1]), 0), fill: c.accent }, svg); });
      } else {
        var line = pts.map(function (p, i) { return X(i) + ',' + Y(p[1]); }).join(' ');
        sv('polygon', { points: X(0) + ',' + (padT + ph) + ' ' + line + ' ' + X(n - 1) + ',' + (padT + ph), fill: c.accent, 'fill-opacity': 0.18 }, svg);
        sv('polyline', { points: line, fill: 'none', stroke: c.accent, 'stroke-width': 2.5, 'stroke-linejoin': 'round' }, svg);
        sv('circle', { cx: X(n - 1), cy: Y(vals[n - 1]), r: 4, fill: '#fff' }, svg);
      }
      var cross = sv('line', { y1: padT, y2: padT + ph, stroke: '#fff', 'stroke-opacity': 0.5, visibility: 'hidden' }, svg);
      svg.addEventListener('mousemove', function (e) {
        var r = svg.getBoundingClientRect(), x = e.clientX - r.left;
        var i = Math.min(n - 1, Math.max(0, Math.round(bar ? (x - padL) / (pw / n) - 0.5 : n === 1 ? 0 : (x - padL) / pw * (n - 1))));
        cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
        floatTip(new Date(pts[i][0] * 1000).toLocaleString() + '   ' + fmtV(pts[i][1]), e.clientX + 14, e.clientY - 44);
      });
      svg.addEventListener('mouseleave', function () { cross.setAttribute('visibility', 'hidden'); hideTip(); });
    }
    paint();
    var ro = new ResizeObserver(paint);
    ro.observe(wrap);
    observers.push(ro);
  }

  // ---------------------------------------------------------------- square view
  function kpiChip(parent, k) {
    var b = card(parent, 'flex:none;padding:.5vh .8vw;display:flex;align-items:center;gap:.6vw', null);
    var t = el('div', null, null, b);
    label(t, k.label.toUpperCase());
    el('div', 'font-size:3vh;font-weight:700;color:' + kpiColor(k.state), k.value, t);
    if (k.explain) icon(b, k.explain);
    return b;
  }
  function statCard(parent, s, i) {
    var b = card(parent, 'display:flex;flex-direction:column;gap:.4vh;min-width:0', function () { show(D, 'stat:' + i, true); });
    var top = el('div', 'display:flex;align-items:baseline;gap:.6vw', null, b);
    el('div', 'font-size:3.6vh;font-weight:700', s.value, top);
    if (s.trend === 'up') el('span', 'color:#3fb950;font-size:2vh', '\u25b2', top);
    if (s.trend === 'down') el('span', 'color:#f85149;font-size:2vh', '\u25bc', top);
    el('div', 'flex:1', null, top);
    if (s.explain) icon(top, s.explain);
    label(b, s.label.toUpperCase());
  }
  function healthRow(parent, h, i) {
    var b = card(parent, 'display:flex;align-items:center;gap:.8vw;padding:.8vh 1vw;font-size:2.2vh;min-width:0', function () { show(D, 'health:' + i, true); });
    el('span', 'flex:none;color:' + col().health[h.state] + ';font-size:2.6vh', '\u25cf', b);
    el('span', 'flex:1;min-width:0', h.name, b);
    el('span', 'flex:none;font-size:1.7vh;letter-spacing:.1em;color:' + col().health[h.state], h.state.toUpperCase(), b);
    if (h.explain) icon(b, h.explain);
  }
  function chartCard(parent, i) {
    var ch = D.charts[i], c = col(), s = summarize(ch.points);
    var b = card(parent, 'display:flex;flex-direction:column;gap:.8vh;min-height:0;min-width:0', function () { show(D, 'chart:' + i, true); });
    var top = el('div', 'flex:none;display:flex;align-items:center;gap:.8vw;min-width:0', null, b);
    el('div', 'font-size:2.4vh;font-weight:700;letter-spacing:.06em', ch.title.toUpperCase(), top);
    el('div', 'font-size:1.8vh;color:' + c.muted, ch.subtitle, top);
    el('div', 'flex:1', null, top);
    if (ch.explain) icon(top, ch.explain);
    if (ch.kpis.length) { var kp = el('div', 'flex:none;display:flex;gap:.8vw', null, b); ch.kpis.forEach(function (k) { kpiChip(kp, k); }); }
    drawChart(el('div', 'flex:1;min-height:0', null, b), ch.points, ch);
    var f = el('div', 'flex:none;display:flex;justify-content:space-between;font-size:1.6vh;color:' + c.muted, null, b);
    el('span', null, '-' + (ch.span_label || ''), f); el('span', null, s ? 'max ' + fmtV(s.max) : '-', f); el('span', null, 'now', f);
  }
  function squareView() {
    var c = col();
    var body = frame(D.name, [D.branch ? '\u2387 ' + D.branch : '', D.activity].filter(Boolean).join('   \u00b7   '), c.status[D.status], String(D.status_label || D.status).toUpperCase());
    var left = el('div', 'flex:none;width:32vw;display:flex;flex-direction:column;gap:1.2vh;min-height:0;overflow:auto', null, body);
    if (D.summary) el('div', 'flex:none;font-size:2vh;line-height:1.35;color:' + c.muted, D.summary, left);
    if (D.task) { var t = card(left, 'flex:none;font-size:2.1vh', null); label(t, 'NOW'); el('div', 'margin-top:.4vh', D.task, t); }
    if (D.health.length) {
      section(left, 'HEALTH');
      var hg = el('div', 'flex:none;display:grid;gap:1vh;grid-template-columns:' + (D.health.length > 4 ? '1fr 1fr' : '1fr'), null, left);
      D.health.forEach(function (h, i) { healthRow(hg, h, i); });
    }
    if (D.stats.length) {
      section(left, 'STATS');
      var sg = el('div', 'flex:none;display:grid;gap:1vh;grid-template-columns:1fr 1fr', null, left);
      D.stats.forEach(function (s, i) { statCard(sg, s, i); });
    }
    var n = D.charts.length;
    var right = el('div', 'flex:1;min-width:0;min-height:0;display:grid;gap:1.4vh;grid-auto-rows:minmax(0,1fr);grid-template-columns:' + (n >= 3 ? '1fr 1fr' : '1fr'), null, body);
    D.charts.forEach(function (ch, i) { chartCard(right, i); });
    if (!n) el('div', 'display:flex;align-items:center;justify-content:center;color:' + c.muted + ';font-size:2.4vh', 'No charts on this tile', right);
  }

  // ---------------------------------------------------------------- chart view
  function chartView(i) {
    var ch = D.charts[i], c = col(), long = !!(ch.history && ch.history.length);
    var pts = long ? ch.history : ch.points, span = long ? (ch.history_label || ch.span_label) : ch.span_label;
    var body = frame(ch.title, ch.subtitle, null, null);
    var main = card(body, 'flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;gap:1vh', null);
    label(main, span ? 'LAST ' + span.toUpperCase() : 'HISTORY');
    drawChart(el('div', 'flex:1;min-height:0', null, main), pts, ch);
    var side = el('div', 'flex:none;width:30vw;display:flex;flex-direction:column;gap:1.2vh;min-height:0;overflow:auto', null, body);
    if (ch.explain) { section(side, 'WHAT THIS SHOWS'); el('div', 'flex:none;font-size:2.1vh;line-height:1.35', ch.explain, side); }
    var s = summarize(pts), bar = ch.kind === 'bar';
    if (s) {
      var cells = bar ? [['QUIET BUCKETS', pct(s.zeroPct), 'Share of time buckets with a value of 0 (for an error chart: no errors).'], ['ACTIVE BUCKETS', pct(100 - s.zeroPct), 'Share of time buckets with a value above 0.'], ['TOTAL', fmtV(s.sum), 'Sum over the window.'], ['PEAK', fmtV(s.max), 'Highest single bucket.']]
                      : [['NOW', fmtV(s.last), 'Latest value.'], ['AVERAGE', fmtV(s.avg), 'Mean over the window.'], ['MIN', fmtV(s.min), 'Lowest value.'], ['MAX', fmtV(s.max), 'Highest value.']];
      section(side, 'NUMBERS');
      var g = el('div', 'flex:none;display:grid;gap:1vh;grid-template-columns:1fr 1fr', null, side);
      cells.forEach(function (x) {
        var m = card(g, 'padding:.8vh 1vw', null);
        var r = el('div', 'display:flex;justify-content:space-between;align-items:center', null, m);
        label(r, x[0]); icon(r, x[2]);
        el('div', 'font-size:3vh;font-weight:700', x[1], m);
      });
    }
    var b = ch.breakdown;
    if (b && (b.ok_pct != null || b.err_pct != null)) {
      var okp = b.ok_pct != null ? b.ok_pct : 100 - b.err_pct, erp = b.err_pct != null ? b.err_pct : 100 - b.ok_pct;
      section(side, 'SUCCESS VS ERRORS' + (b.total != null ? '  \u00b7  ' + fmtV(b.total) + ' RUNS' : ''));
      var bb = card(side, 'flex:none;padding:.8vh 1vw', null);
      var bar2 = el('div', 'display:flex;height:2.2vh;border-radius:4px;overflow:hidden;background:#1a2640', null, bb);
      el('div', 'width:' + okp + '%;background:' + c.health.up, null, bar2);
      el('div', 'width:' + erp + '%;background:' + c.health.down, null, bar2);
      var row = el('div', 'display:flex;justify-content:space-between;margin-top:.5vh;font-size:2vh', null, bb);
      el('span', 'color:' + c.health.up, pct(okp) + ' success', row); el('span', 'color:' + c.health.down, pct(erp) + ' errors', row);
    }
    if (ch.kpis.length) { section(side, 'KEY NUMBERS'); var kp = el('div', 'flex:none;display:flex;gap:1vw', null, side); ch.kpis.forEach(function (k) { kpiChip(kp, k); }); }
    var w = (b && b.worst && b.worst.length) ? b.worst : worst(pts, 4).map(function (x) { return { label: new Date(x.t * 1000).toLocaleString(), value: fmtV(x.v) }; });
    if (w.length) {
      section(side, 'WORST PERIODS');
      w.slice(0, 4).forEach(function (x) {
        var r = card(side, 'flex:none;display:flex;justify-content:space-between;padding:.5vh 1vw;font-size:2vh', null);
        el('span', null, x.label, r); el('span', 'font-weight:700', x.value, r);
      });
    }
  }

  // ---------------------------------------------------------------- item view (stat / health light / KPI)
  function itemView(kind, it, ch) {
    var c = col(), name = it.name || it.label;
    var color = kind === 'health' ? c.health[it.state] : kind === 'kpi' ? kpiColor(it.state) : c.text;
    var body = frame(name, kind === 'kpi' && ch ? 'from ' + ch.title : '', null, null);
    body.style.flexDirection = 'column';
    body.style.overflow = 'auto';
    var big = card(body, 'flex:none;display:flex;align-items:center;gap:2vw;padding:3vh 2vw', null);
    if (kind === 'health') {
      el('span', 'color:' + color + ';font-size:7vh;line-height:1', '\u25cf', big);
      el('span', 'color:' + color + ';font-size:6vh;font-weight:700;letter-spacing:.08em', it.state.toUpperCase(), big);
    } else {
      el('span', 'color:' + color + ';font-size:8vh;font-weight:700;line-height:1', it.value, big);
      if (it.trend === 'up') el('span', 'color:#3fb950;font-size:4vh', '\u25b2', big);
      if (it.trend === 'down') el('span', 'color:#f85149;font-size:4vh', '\u25bc', big);
      el('span', 'color:' + c.muted + ';font-size:2.6vh;letter-spacing:.12em', it.label.toUpperCase(), big);
    }
    var d = it.detail, any = false;
    if (it.explain) { any = true; var e = card(body, 'flex:none', null); label(e, 'WHAT IT IS'); el('div', 'font-size:2.4vh;line-height:1.4;margin-top:.5vh', it.explain, e); }
    if (d && d.why) { any = true; var w = card(body, 'flex:none', null); label(w, 'WHAT IS GOING ON'); el('div', 'font-size:2.4vh;line-height:1.4;margin-top:.5vh', d.why, w); }
    if (d && d.items && d.items.length) {
      any = true;
      section(body, 'MEMBERS (' + d.items.length + ')');
      var g = el('div', 'flex:none;display:grid;gap:1vh;grid-template-columns:repeat(3,1fr)', null, body);
      d.items.forEach(function (m) {
        var r = card(g, 'padding:.8vh 1vw;min-width:0', null);
        var t = el('div', 'display:flex;align-items:center;gap:.6vw;font-size:2.2vh', null, r);
        el('span', 'flex:none;color:' + c.health[m.state], '\u25cf', t);
        el('span', 'flex:1;min-width:0;font-weight:700', m.name, t);
        el('span', 'flex:none;font-size:1.6vh;letter-spacing:.1em;color:' + c.health[m.state], m.state.toUpperCase(), t);
        if (m.what) el('div', 'font-size:1.9vh;color:' + c.muted + ';margin-top:.3vh', m.what, r);
      });
    }
    if (!any) el('div', 'flex:none;font-size:2.2vh;color:' + c.muted, 'No further detail has been recorded for this item.', body);
  }

  // ---------------------------------------------------------------- install
  document.addEventListener('keydown', function (e) {
    if (overlay && e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  }, true);
  window.wallOpen = function (node, target) {
    try {
      var root = node.closest('[data-wl-data]');
      stack = [];
      show(JSON.parse(root.getAttribute('data-wl-data')), target, false);
    } catch (e) { close(); }
  };
  window.wallShow = function (data, target) { stack = []; show(data, target, false); };
  window.wallClose = function () { close(); };
  document.documentElement.setAttribute('data-wl-viewer', '1');     // lets a live check see that the bootstrap loaded the script
})();
```
- [ ] **Step 5: Write the viewer test runner**

`server/slot-writer/tests/run-viewer-tests.sh`:
```bash
#!/usr/bin/env bash
# Opens every viewer view for every fixture in headless Chrome and checks layout/behaviour (tests/viewer_harness.html).
# Usage: tests/run-viewer-tests.sh [--shots DIR]     CHROME=path overrides the browser.
# 1824,1080 = the wall's 95% frame on a 1080p TV; the other sizes prove the views fit any screen.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
CHROME="${CHROME:-/c/Program Files/Google/Chrome/Application/chrome.exe}"
PROF="$(cygpath -m "${TMPDIR:-/tmp}")/wl-chrome-profile"
base="file:///$(cygpath -m "$here")/viewer_harness.html"
shots=""; [ "${1:-}" = "--shots" ] && shots="$2" && mkdir -p "$shots"
fail=0; n=0
run() {  # fx view size [flow]
  local fx="$1" view="$2" size="$3" flow="${4:-}" out res
  out="$("$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROF" --window-size="$size" --virtual-time-budget=3000 --dump-dom "$base?fx=$fx&view=$view&flow=$flow" 2>/dev/null)"
  res="$(printf '%s' "$out" | grep -o 'WLTEST:[A-Z]*' | head -1)"
  n=$((n + 1))
  if [ "$res" != "WLTEST:PASS" ]; then
    fail=$((fail + 1)); echo "FAIL $fx $view $size flow=$flow: $(printf '%s' "$out" | grep -o 'data-wlfails="[^"]*"' | head -1)"
  fi
  if [ -n "$shots" ]; then
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$PROF" --window-size="$size" --virtual-time-budget=3000 \
      --screenshot="$(cygpath -m "$shots")/$fx-${view//:/_}-${size/,/x}.png" "$base?fx=$fx&view=$view" >/dev/null 2>&1
  fi
}
for fx in full minimal hostile big; do
  for view in square chart:0 stat:0 health:0 kpi:0:0 health:99 chart:99; do run "$fx" "$view" 1824,1080; done
done
for size in 1280,720 3840,2160 1000,1000; do
  for view in square chart:0 health:0; do run full "$view" "$size"; done
done
run full square 1824,1080 1
echo "$((n - fail))/$n passed"
[ "$fail" -eq 0 ]
```

- [ ] **Step 6: Run the viewer tests and make them pass**

```bash
chmod +x server/slot-writer/tests/run-viewer-tests.sh && server/slot-writer/tests/run-viewer-tests.sh --shots "${TMPDIR:-/tmp}/wl-shots"
```
Expected on the first run: failures are likely in layout (`elements outside the window`, `overlay overflows`) for `big`/`hostile`. **Fix the viewer's sizes (vh/vw values, grid columns, `max-height`s in that view), never relax a check.** Then open the PNGs (Read tool) for `full-square-1824x1080`, `full-chart_0-1824x1080`, `full-health_0-1824x1080`, `big-square-1824x1080`, `hostile-square-1824x1080`, and confirm by eye: nothing clipped, charts fill their cards with readable axes, text is concise and legible at TV distance, palette is dark blue/black with white text and blue accents. Iterate until `N/N passed` and the screenshots look right.

- [ ] **Step 7: Serve the viewer and ship it in the image**

In `app.py`, next to the other constants:
```python
VIEWER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer.js")


def viewer_js():
    with open(VIEWER_PATH, "rb") as f:        # read per request: it is small, and a replaced file needs no restart
        return f.read()
```
In `H._route`, immediately before the line `m = re.fullmatch(r"/wall/([a-z0-9-]+)(/version)?", path)` add:
```python
            if method == "GET" and path == "/wall/viewer.js":     # unauthenticated static script, loaded by each tile's bootstrap
                b = viewer_js()
                self.send_response(200); self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-cache"); self.send_header("Content-Length", str(len(b))); self.end_headers()
                return self.wfile.write(b)
```
In `server/slot-writer/Dockerfile` change `COPY app.py .` to `COPY app.py viewer.js ./`.

- [ ] **Step 8: Run both suites**

```bash
server/slot-writer/tests/run-remote.sh && server/slot-writer/tests/run-viewer-tests.sh
```
Expected: server tests `OK` (incl. `ViewerRoute`); viewer tests `N/N passed`.

- [ ] **Step 9: Commit**

```bash
git add server/slot-writer && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "Full-screen viewer (square, chart, item views) with headless layout tests; serve /wall/viewer.js" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wrapper page holds auto-reloads while an overlay is open

**Files:**
- Modify: `server/slot-writer/app.py` (`wall_page`)
- Test: `server/slot-writer/tests/test_app.py`

**Interfaces:**
- Consumes: viewer's `window.parent.postMessage({wallHold: bool}, '*')` (Task 4).
- Produces: the wrapper defers its version-change reload while held; releases on `wallHold:false` or after 600000 ms; accepts messages only from its current iframe (`e.source===cur.contentWindow`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_app.py`)

```python
class WrapperHold(unittest.TestCase):
    def test_reload_is_deferred_while_an_overlay_is_open(self):
        page = app.wall_page("wall-top", 95)
        self.assertIn("wallHold", page)               # listens for the viewer's hold message
        self.assertIn("e.source!==cur.contentWindow", page)   # ...but only from its own iframe
        self.assertIn("pend=true", page)              # a version change is remembered, not applied
        self.assertIn("if(pend&&!hold)", page)        # ...and applied once the hold is gone
        self.assertIn("600000", page)                 # a crashed viewer can never freeze updates for more than 10 minutes
        self.assertIn("/wall/wall-top/version", page)  # existing behaviour kept
```

- [ ] **Step 2: Run to confirm it fails**

```bash
server/slot-writer/tests/run-remote.sh -k WrapperHold
```
Expected: FAIL (`wallHold` not in page).

- [ ] **Step 3: Edit `wall_page`**

Three replacements inside the returned JS (anchors are the exact existing strings):
1. `"var U=location.protocol+'//'+location.hostname+':3000/d/%s?%s',cur=null,v=null,z=1;"` becomes
   `"var U=location.protocol+'//'+location.hostname+':3000/d/%s?%s',cur=null,v=null,z=1,hold=false,pend=false,holdT=null;"`
2. In `tick`, replace `"if(v!==null&&j.version!==v){load()}v=j.version}).catch(function(){}).then(function(){setTimeout(tick,5000)})}"` with
   `"if(v!==null&&j.version!==v){pend=true}v=j.version;go()}).catch(function(){}).then(function(){setTimeout(tick,5000)})}"`
3. Immediately before `"window.addEventListener('DOMContentLoaded',function(){load();tick()});</script>"` insert:
```python
            "function go(){if(pend&&!hold){pend=false;load()}}"
            "window.addEventListener('message',function(e){if(!cur||e.source!==cur.contentWindow||!e.data||typeof e.data.wallHold!=='boolean')return;"
            "hold=e.data.wallHold;clearTimeout(holdT);if(hold){holdT=setTimeout(function(){hold=false;go()},600000)}else{go()}});"
```
Also update the docstring: add "While a full-screen view is open (the Grafana page posts {wallHold:true}) a pending reload waits until it closes (or 10 minutes)."

- [ ] **Step 4: Run all server tests**

```bash
server/slot-writer/tests/run-remote.sh
```
Expected: all `ok`.

- [ ] **Step 5: Commit**

```bash
git add server/slot-writer && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "Wrapper page: hold reloads while a full-screen view is open" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
(The behaviour itself is exercised end-to-end in Task 9.)

---

### Task 6: Skill documentation, hook merge key, evals

**Files:**
- Modify: `skills/grafana-wall/references/tile-spec.md`, `skills/grafana-wall/references/refresh-hook.md`, `skills/grafana-wall/references/project-discovery.md`, `skills/grafana-wall/SKILL.md`, `skills/grafana-wall/evals/evals.json`, `skills/grafana-wall/scripts/wall-refresh.ps1`

**Interfaces:**
- Consumes: Task 2 field names and limits.
- Produces: the agent-facing contract: which fields to author, who fills what, and the redraw-hash rule for `history`.

- [ ] **Step 1: `tile-spec.md` - add the fields table row and a new section**

Add this row to the main Fields table:
```
| `summary` | text ≤240 | One or two sentences on what the tile is; shown in the full-screen square view. |
```
Add `explain` (≤200, optional) to the descriptions of `stats`, `health` and `charts` items, and add this section before `## Legacy series charts`:
````
## Interactive detail (all optional; every field degrades to a minimal view when absent)

On the wall every box lights on hover and opens a full-screen view on click (top bar = the whole square; a chip, health light, chart or KPI = just that thing; Esc closes). These fields fill those views.

| Field | On | Notes |
|---|---|---|
| `explain` | stat, health light, chart, KPI | ≤200 chars: what it is and what bad looks like. Also the hover tooltip. |
| `detail` | stat, health light | `{ "why": text ≤240, "items": [{ "name" ≤24, "state": up/degraded/down/unknown, "what" ≤120 }] }`, up to 12 items. `why` is what is going on right now (from real data); `items` lists the members (e.g. the 5 containers behind a `Containers 5` chip). |
| `history` | chart | Longer window than `points` (up to 400 `[epoch, value]` pairs) plus `history_label` (≤8, e.g. `7d`). Use clean aligned buckets. |
| `breakdown` | chart | `{ "ok_pct", "err_pct", "total", "worst": [{ "label" ≤24, "value" ≤12 }] }` (≤5 worst). Omit it and the viewer derives quiet/active buckets and the worst buckets from `history`. |

```json
{ "summary": "Always-on checks that provision, update and play content on test players.",
  "stats": [ { "label": "Containers", "value": "5", "explain": "Docker containers on the host.",
               "detail": { "why": "4 of 5 healthy", "items": [ { "name": "grafana", "state": "up", "what": "Dashboards" } ] } } ],
  "charts": [ { "title": "Update", "points": [...], "explain": "Failed update probes per 30 minutes.",
                "history": [...], "history_label": "7d",
                "breakdown": { "ok_pct": 99.5, "err_pct": 0.5, "total": 1840, "worst": [ { "label": "Tue 14:00", "value": "3 err" } ] },
                "kpis": [ { "label": "ERR 7D", "value": "0.5%", "state": "ok", "explain": "Share of runs in the last 7 days that failed." } ] } ] }
```
Whole tile (spec + payload) must stay under 120 KB; the request under 256 KB.
````

- [ ] **Step 2: `refresh-hook.md` - document the merge key and the hash rule**

Add a row to the table of merged keys: `| `summary` | tile description for the full-screen view |`, and extend the `charts`/`stats`/`health` rows with "(items may carry `explain`, `detail`, and for charts `history`/`breakdown`; see tile-spec.md)". Add a bullet to "Rules for hooks":
```
- **Detail follows the same alignment rule as chart points.** `history`, `breakdown` and `detail` are part of the redraw hash, so build them from aligned buckets (e.g. 3 h or 1 h boundaries) and put no ticking timestamps or per-run counters in `why`/`worst` labels. Cache expensive long-range queries (10 min) like the 12 h chart.
```

- [ ] **Step 3: `wall-refresh.ps1` - merge `summary`**

In the loop that reads hook output, change
`foreach ($k in 'status', 'status_label', 'task', 'tests', 'health', 'stats', 'charts') {`
to
`foreach ($k in 'status', 'status_label', 'task', 'summary', 'tests', 'health', 'stats', 'charts') {`

- [ ] **Step 4: `SKILL.md` - teach the agent**

1. In "The template", after the **Charts row** paragraph add:
```
**Explorable**: on the wall every box lights up on hover and opens a full-screen view on click (top bar = the whole square with every chart large; a stat chip, health light, chart or KPI = just that, with more history, percentages and a short explanation; Esc closes). The server draws these views from fields you supply (`summary`, `explain`, `detail`, `history`, `breakdown`; see `references/tile-spec.md`).
```
2. After step 5 of the Workflow ("Write the hook") add:
```
   **Make it explorable.** Write a concise `explain` (≤200 chars: what it is, what bad looks like) for every stat chip, health light, chart and KPI, and a one-sentence `summary` for the tile, in `.grafana-wall/tile.json`. Have the hook return, from real data: `history` for each chart (a longer window than the tile shows, aligned buckets), `breakdown` when success/error counts exist, and `detail` for anything that is a list or has a cause (members of a "5 containers" chip with each one's health and purpose; `why` for a degraded/down light, e.g. which check is failing). Keep every sentence short.
```
3. In "Guardrails" add:
```
- `explain`/`detail` text is shown on a TV: no secrets, and say only what you can support from the project or the live data (a `why` you cannot back with data stays out; the item then opens a minimal view).
```

- [ ] **Step 4b: `project-discovery.md` - look for explanation sources while discovering**

Append this section to the end of `skills/grafana-wall/references/project-discovery.md`:
```
## Also note what could explain each part (for the full-screen views)

While discovering, jot down where an explanation could come from, so the tile can answer "what is this and what is wrong?" on click: what each health light checks (and what a failure of it means), the members behind any count chip (containers, services, workers, queues: name, current health, what each does), the project's own alert rules or dashboard panel descriptions (they define "error" and "bad"), and where longer history exists (a 7-day range query, a ledger table). Record only what you can back with the project or live data; anything unknown stays out and that item opens a minimal view.
```

- [ ] **Step 5: `evals.json` - add an eval**

Read the last eval's `id` (currently 5) and append, before the closing `]` (keep the file's existing PowerShell-JSON indentation style), an object with the next id:
```json
{
  "id": 6,
  "prompt": "when i hover and click the 5 containers chip on the mini-mac tile it just shows a number. make every chip, light and chart explain itself when clicked",
  "expected_output": "Adds a concise explain to every stat, health light, chart and KPI plus a tile summary in tile.json, and extends the hook to return history, breakdown and detail (the five containers with health and purpose, a why for any degraded light) from real data on clean aligned buckets; validates with snapshot -Dry; no secrets, no invented causes.",
  "files": []
}
```

- [ ] **Step 6: Verify the JSON parses and nothing else broke**

```bash
powershell.exe -NoProfile -Command "Get-Content skills/grafana-wall/evals/evals.json -Raw | ConvertFrom-Json | Select-Object -ExpandProperty evals | Measure-Object | Select-Object -ExpandProperty Count"
```
Expected: `6`.

- [ ] **Step 7: Commit**

```bash
git add skills && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "Skill: document interactive detail fields; merge summary from hooks; add eval" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Deploy the server and the skill (with backups) and dry-run real specs

**Files:**
- Modify (on mini-mac): `~/monitoring/slot-writer/{app.py,viewer.js,Dockerfile}`
- Modify (this PC): installed skill copy `C:\Users\there\.claude\skills\grafana-wall\`

**Interfaces:**
- Consumes: everything above. Produces: a live server that renders interactive tiles and serves `/wall/viewer.js`; installed skill/refresher with the `summary` merge key. Existing tiles do not change until their next redraw.

- [ ] **Step 1: Final test run**

```bash
server/slot-writer/tests/run-remote.sh && server/slot-writer/tests/run-viewer-tests.sh
```
Expected: both pass. Do not deploy otherwise.

- [ ] **Step 2: Back up the deployed files**

```bash
ssh -o BatchMode=yes emac@mini-mac.local 'cd ~/monitoring/slot-writer && ts=$(date +%Y%m%d-%H%M%S) && cp app.py app.py.bak-pre-interactive-$ts && cp Dockerfile Dockerfile.bak-pre-interactive-$ts && ls'
```
Expected: the new `.bak-pre-interactive-*` files are listed.

- [ ] **Step 3: Copy and rebuild**

```bash
scp server/slot-writer/app.py server/slot-writer/viewer.js server/slot-writer/Dockerfile emac@mini-mac.local:~/monitoring/slot-writer/ && ssh -o BatchMode=yes emac@mini-mac.local 'cd ~/monitoring && docker compose up -d --build slot-writer && sleep 3 && curl -s localhost:8088/health && curl -s -o /dev/null -w " viewer:%{http_code}\n" localhost:8088/wall/viewer.js'
```
Expected: `{"ok": true} viewer:200`. If the container fails to start, restore the backups (`cp app.py.bak-pre-interactive-<ts> app.py` etc.), `docker compose up -d --build slot-writer`, and report.

- [ ] **Step 4: Install the updated skill and refresher scripts (overwrite copies; do not Remove-Item)**

```powershell
Copy-Item -Recurse -Force "C:\Users\there\Grafana-Dashboard-Skill-Creator\.claude\worktrees\interactive-fullscreen\skills\grafana-wall\*" "$HOME\.claude\skills\grafana-wall\"
```
Expected: no error. (Note: an already-running session keeps serving the old SKILL.md; new sessions load the new one.)

- [ ] **Step 5: Dry-run the existing tiles against the live server**

```powershell
& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" snapshot -File C:\Users\there\canaries\.grafana-wall\tile.json -Dry
& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" snapshot -File C:\Users\there\mini-mac-wall\.grafana-wall\tile.json -Dry
```
Expected: `dry_run` true with `slot` 1 and 8 (`template v2`). Old specs without the new fields must pass.

- [ ] **Step 6: Confirm the wall is unchanged**

```powershell
& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" slots
```
Expected: same occupied/vacant listing as before (no redraw has happened).

(Nothing to commit: deployment only.)

---

### Task 8: Hooks supply the detail (canaries and mini-mac)

**Files:**
- Modify: `C:\Users\there\canaries\.grafana-wall\refresh.ps1` (outside this repo; `.grafana-wall/` is git-excluded there), `examples/mini-mac/refresh.ps1` (repo) and its live copy `C:\Users\there\mini-mac-wall\.grafana-wall\refresh.ps1`, plus `.grafana-wall\tile.json` for both (`summary`).

**Interfaces:**
- Consumes: Task 2 fields. Produces: tiles with `summary`/`explain`/`history`/`detail`/`breakdown` from real data.

- [ ] **Step 1: Canaries hook - `$defs`, history, breakdown, explains**

In `C:\Users\there\canaries\.grafana-wall\refresh.ps1`:

1. Add an `explain` to each entry in `$defs` (append the key inside each `@{ ... }`):
   - Provisioning: `explain = 'Provisioning canary: provisions a test player end to end. An error is a failed or aborted cycle.'`
   - Update: `explain = 'Update canary: probes the player update path. An error is a failed probe.'`
   - Content: `explain = 'Content canary: runs content playback checks. An error is a failed or errored run.'`
2. Inside `if (-not $charts -and $haveFleet) {`, replace everything from `$built = @()`'s following `foreach ($def in $defs) {` through its closing `}` (keep the lines `$now`, `$end30`, `$end5` and `$built = @()` above it, and the `if ($built.Count -gt 0) {...}` line below it) with the block below. It adds one line (`$end3h`) before the loop:
```powershell
  $end3h = [math]::Floor($now / 10800) * 10800      # 7-day history in aligned 3-hour buckets (56 points)
  foreach ($def in $defs) {
    $hist = Invoke-PromRange ($def.err.Replace('{W}', '30m')) ($end30 - 43200) $end30 1800
    if (-not $hist) { continue }                    # no data => no chart (never an empty box)
    $pts = @($hist | ForEach-Object { @{ t = $_.t; v = [math]::Round($_.v) } })
    $h7 = Invoke-PromRange ($def.err.Replace('{W}', '3h')) ($end3h - 7 * 86400) $end3h 10800
    $history = if ($h7) { @($h7 | ForEach-Object { @{ t = $_.t; v = [math]::Round($_.v) } }) } else { $null }
    # 7-day error %
    $e7 = Invoke-Prom ($def.err.Replace('{W}', '7d')); $t7 = Invoke-Prom ($def.tot.Replace('{W}', '7d'))
    $kpis = @(); $breakdown = $null
    if ($null -ne $e7 -and $null -ne $t7 -and $t7 -gt 0) {
      $pct = 100.0 * $e7 / $t7
      $txt = if ($pct -eq 0) { '0%' } elseif ($pct -lt 0.01) { '<0.01%' } elseif ($pct -lt 10) { $pct.ToString('0.00', $inv) + '%' } else { $pct.ToString('0.0', $inv) + '%' }
      $kpis += @{ label = 'ERR 7D'; value = $txt; state = $(if ($pct -lt 1) { 'ok' } elseif ($pct -lt 5) { 'warn' } else { 'bad' }); explain = 'Share of runs in the last 7 days that ended in an error.' }
      $worst = @()
      if ($h7) { $worst = @($h7 | Where-Object { $_.v -ge 1 } | Sort-Object @{ e = { $_.v }; Descending = $true }, @{ e = { $_.t }; Descending = $true } | Select-Object -First 5 |
                 ForEach-Object { @{ label = [DateTimeOffset]::FromUnixTimeSeconds($_.t).LocalDateTime.ToString('ddd HH:mm', $inv); value = ('{0} err' -f [math]::Round($_.v)) } }) }
      # total is rounded to the nearest 100 on purpose: it is part of the redraw hash, and an exact 7-day run count would change every few minutes
      $breakdown = @{ ok_pct = [math]::Round(100 - $pct, 2); err_pct = [math]::Round($pct, 2); total = [math]::Round($t7 / 100) * 100; worst = $worst }
    } else { $kpis += @{ label = 'ERR 7D'; value = '?'; explain = 'Share of runs in the last 7 days that ended in an error.' } }
    # consecutive successful runs: successes after the last 5-minute bucket that held an error, over a 14-day lookback
    $eb = Invoke-PromRange ($def.err.Replace('{W}', '5m')) ($end5 - 14 * 86400) $end5 300
    $sb = Invoke-PromRange ($def.ok.Replace('{W}', '5m')) ($end5 - 14 * 86400) $end5 300
    $sx = 'Successful runs since the last error (14-day lookback; N+ means no error was seen).'
    if ($eb -and $sb) {
      $lastErr = -1; for ($i = 0; $i -lt $eb.Count; $i++) { if ($eb[$i].v -gt 0.5) { $lastErr = $i } }
      $streak = 0.0; $from = if ($lastErr -ge 0) { $eb[$lastErr].t } else { 0 }
      foreach ($b in $sb) { if ($b.t -gt $from) { $streak += $b.v } }
      $kpis += @{ label = 'STREAK'; value = ([string][math]::Round($streak) + $(if ($lastErr -lt 0) { '+' } else { '' })); explain = $sx }
    } else { $kpis += @{ label = 'STREAK'; value = '?'; explain = $sx } }
    $chart = @{ title = $def.title; subtitle = $def.sub; kind = 'bar'; y_max = 10; span_label = '12h'; points = $pts; kpis = $kpis; explain = $def.explain }
    if ($history) { $chart.history = $history; $chart.history_label = '7d' }
    if ($breakdown) { $chart.breakdown = $breakdown }
    $built += $chart
  }
```
3. In the "assemble" section, give each health entry an `explain` (+ a `detail.why` when not `up`) and each stat an `explain`:
```powershell
$health = @(@{ name = 'CI build'; state = $ci; explain = 'Latest Build Canaries workflow run on main.' })
...
  $why = $null
  if ($st -eq 'down') { $why = 'The canary worker reports it is not active.' }
  elseif ($st -eq 'degraded') { $why = "$([int]$bad[$k]) canary instance(s) report consecutive failures." }
  $h = @{ name = $k; state = $st; explain = ($defs | Where-Object { $_.title -eq $k }).explain }
  if ($why) { $h.detail = @{ why = $why } }
  $health += $h
```
(replace the existing `$health += @{ name = $k; state = $st }` line with these lines inside that `foreach ($k in $act.Keys)` loop), and in `$out`:
```powershell
  summary = 'Always-on checks that provision, update and play content on test players, to catch failures early.'
  stats = @(
    @{ label = 'Failures 24h'; value = ...; explain = 'Failed canary runs across all three canaries in the last 24 hours.' },
    @{ label = 'Checks failing'; value = ...; explain = 'Canary checks currently reporting consecutive errors.' },
    @{ label = 'Open PRs'; value = ...; explain = 'Pull requests open on the canaries repository.' }
  )
```
(keep the existing `value = $(...)` expressions; only add `explain`).

- [ ] **Step 2: Run the canaries hook and validate**

```powershell
cd C:\Users\there\canaries
$o = & powershell -NoProfile -File .\.grafana-wall\refresh.ps1; $LASTEXITCODE; ($o | ConvertFrom-Json | ConvertTo-Json -Depth 9 -Compress).Length
$o | Set-Content "$env:TEMP\canaries-hook.json"
```
Expected: exit 0, valid JSON. Then merge into the tile and dry-run:
```powershell
$t = Get-Content .\.grafana-wall\tile.json -Raw | ConvertFrom-Json; $p = $o | ConvertFrom-Json
foreach ($k in 'status','status_label','task','summary','health','stats','charts') { if ($p.PSObject.Properties[$k]) { $t | Add-Member -NotePropertyName $k -NotePropertyValue $p.$k -Force } }
$t | ConvertTo-Json -Depth 10 | Set-Content "$env:TEMP\canaries-tile.json"
& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" snapshot -File "$env:TEMP\canaries-tile.json" -Dry
```
Expected: `dry_run` true (no field-name validation error). Each chart carries `history` (56 points), `explain`, `breakdown`.

- [ ] **Step 3: mini-mac hook (repo example + live copy) - history, explains, containers**

In `examples/mini-mac/refresh.ps1`:

1. Make queries bucket-parametrised: change `Get-Points` to `function Get-Points($query, $bucket = $Bucket, $buckets = $Buckets)` using `$bucket`/`$buckets` in place of `$Bucket`/`$Buckets`, and write the three queries with a `{W}` window token, e.g. `"100 - avg(rate(node_cpu_seconds_total{job=`"$Job`",mode=`"idle`"}[{W}])) * 100"` (memory: `avg_over_time(((1 - ...) * 100)[{W}:1m])`, temp: `avg_over_time(node_hwmon_temp_celsius{...}[{W}])`). For each chart call `Get-Points $q.Replace('{W}','15m')` as before and also `Get-Points $q.Replace('{W}','1h') 3600 168` for a 7-day history.
2. `New-Chart` takes `$explain` and `$hist` and sets `explain`, `history`, `history_label = '7d'`:
   - CPU: `'Average CPU busy %, 15-minute buckets. Sustained values above 90% mean the host is overloaded.'`
   - Memory: `'Average memory in use %, 15-minute buckets. High and rising usually means a container is leaking.'`
   - CPU temp: `'CPU temperature in deg C, 15-minute buckets. Above 90 risks throttling.'`
3. In the ssh probe script add one line before `echo "UPTIME_S=..."`:
```bash
echo "CONTAINER_LIST=$(docker ps --format '{{.Names}}|{{.Status}}' 2>/dev/null | tr '\n' ';')"
```
4. Define `$items = @()` and `$okc = 0` just before the `if ($routerKnown) {` block, then inside that block (after `$net` is filled) build the container detail:
```powershell
$purpose = @{ grafana = 'Dashboards: draws the wall'; prometheus = 'Metrics database (5-year retention)'; pushgateway = 'Receives pushed wall series'
              'node-exporter' = 'Host CPU, memory, disk and temperature metrics'; 'slot-writer' = 'Draws and releases wall tiles; serves the wall page' }
foreach ($e in (($net.CONTAINER_LIST) -split ';' | Where-Object { $_ })) {
  $nm, $stt = $e -split '\|', 2
  $state = if ($stt -match 'unhealthy') { 'degraded' } elseif ($stt -match '^Up') { 'up' } else { 'down' }
  $items += @{ name = $nm; state = $state; what = $(if ($purpose[$nm]) { $purpose[$nm] } else { '' }) }
}
$okc = @($items | Where-Object { $_.state -eq 'up' }).Count
```
   and make the Containers stat: `@{ label = 'Containers'; value = $cont; explain = 'Docker containers running on mini-mac.'; detail = @{ why = "$okc of $($items.Count) healthy"; items = $items } }` (when `$routerKnown` is false, omit `detail`).
5. Add `explain` to the other stats (`UPLINK`: `'Which link carries mini-mac traffic: the wired travel router or the Wi-Fi backup.'`, `Disk free`: `'Free space on the root disk.'`, `Uptime`: `'Time since the host last booted.'`) and to the health lights: Travel router `'Wired gateway answers ping and carries the default route.'`, Internet `'Pings 1.1.1.1 with no packet loss.'`, Wi-Fi backup `'Backup Wi-Fi link answers ping.'`, Grafana/Prometheus/Node exporter/Wall writer `'<name> health endpoint answers.'`; for any light that is `down`/`degraded` set `detail = @{ why = '<the check that failed in one sentence>' }`.
6. Add `summary = 'The always-on host that runs the monitoring stack and the wall.'` to the output object and to `examples/mini-mac/tile.json`.

Copy the finished example over the live hook: `Copy-Item -Force examples\mini-mac\refresh.ps1 C:\Users\there\mini-mac-wall\.grafana-wall\refresh.ps1`.

- [ ] **Step 4: Run the mini-mac hook and dry-run**

```powershell
cd C:\Users\there\mini-mac-wall
$o = & powershell -NoProfile -File .\.grafana-wall\refresh.ps1; $LASTEXITCODE
$p = $o | ConvertFrom-Json; $p.stats | Where-Object label -eq 'Containers' | ConvertTo-Json -Depth 6
```
Expected: exit 0; the Containers stat lists the five containers (`grafana, prometheus, pushgateway, node-exporter, slot-writer`) with state and purpose. Merge into a temp tile as in Step 2 and run `wall.ps1 snapshot -File <temp> -Dry`; expected `dry_run` true.

- [ ] **Step 5: Commit the repo-side parts**

```bash
git add examples/mini-mac && git -c user.name=emcnamee-bs -c user.email=224684024+emcnamee-bs@users.noreply.github.com commit -m "mini-mac hook: explains, 7d history and container detail" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
(The canaries hook is outside this repo; note its path in the final report.)

---

### Task 9: Live verification on the wall, with the user

**Files:** none (verification, plus a memory update).

- [ ] **Step 1: Redraw the two tiles with the new content**

```powershell
& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" refresh
& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" slots
```
Expected: slots 1 (canaries) and 8 (mini-mac) still occupied. The wall's kiosk reloads those monitors within ~10 s.

- [ ] **Step 2: Automated check on the live dashboards (script, click, overlay)**

```bash
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"; PROF="$(cygpath -m "${TMPDIR:-/tmp}")/wl-chrome-profile"
"$CHROME" --headless=new --disable-gpu --user-data-dir="$PROF" --window-size=1824,1080 --virtual-time-budget=20000 --screenshot="$(cygpath -m "${TMPDIR:-/tmp}")/live-top.png" "http://mini-mac.local:3000/d/wall-top?kiosk&theme=dark&hideLogo=true"
"$CHROME" --headless=new --disable-gpu --user-data-dir="$PROF" --window-size=1824,1080 --virtual-time-budget=20000 --dump-dom "http://mini-mac.local:3000/d/wall-top?kiosk&theme=dark" > "${TMPDIR:-/tmp}/live-top.html"
grep -c "data-wl='square'" "${TMPDIR:-/tmp}/live-top.html"; grep -c "data-wl-viewer" "${TMPDIR:-/tmp}/live-top.html"
```
Expected: both counts are ≥1 (the canaries tile has its square target, and its bootstrap loaded `viewer.js` from `:8088`, which sets `data-wl-viewer` on the page). The screenshot looks the same as before to the eye (nothing shifted by the added attributes: top bar, chips, charts, KPIs in place). If the viewer marker is missing, check that `http://mini-mac.local:8088/wall/viewer.js` is reachable from the page's host.

- [ ] **Step 3: Ask the user to try it on the real wall (hands on) and report back**

Checklist to give them (they have the mouse):
1. Hover the name/status bar of a tile: the bar lights; click: the whole square opens full screen, every chart large, health lights and stats explained; hover an `i` for the short explanation; Esc closes.
2. Hover a chart: only the chart box lights; hover its KPI: only the KPI lights. Click a chart: longer history, success/error percentages, worst periods. Esc.
3. On the mini-mac tile click the **Containers** chip: the five containers with health and purpose.
4. Click a degraded/down light on canaries: what is wrong, concisely.
5. Hold an overlay open, then run `wall.ps1 refresh` after changing something visible (or `wall.ps1 snapshot`): the view must stay until Esc, and the monitor then reloads within a few seconds. (Pins Review Focus #4.)

- [ ] **Step 4: Fix what they report, then update the project memory**

Update `C:\Users\there\.claude\projects\C--Users-there\memory\grafana-wall-project.md` with: sanitizer off on mini-mac (`GF_PANELS_DISABLE_SANITIZE_HTML`, compose backup name), viewer at `/wall/viewer.js`, new spec fields, the hold mechanism, where the tests live and how to run them (`tests/run-remote.sh`, `tests/run-viewer-tests.sh`), and that the branch `worktree-interactive-fullscreen` holds the work, unpushed.

- [ ] **Step 5: Final report**

State: what changed and where, the commands to run the tests, that nothing is pushed (give the user's push command pattern from memory: `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push -u origin <branch>` for them to run), the five spec refinements listed at the top, and the canaries hook path outside the repo.

---

## Self-review

**Spec coverage** (each spec section to its task):
- Goal hover/click/Esc/`i`: Task 3 (hover CSS, targets, tooltips), Task 4 (views, Esc, icons).
- Sizing root cause: Task 4 (SVG drawn at viewport size + resize observer; layout assertions at 5 window sizes).
- Decision B (sanitizer): Task 1 (change + probe), Global Constraints.
- Design 1 (tile markup): Task 3. Design 2 (viewer incl. hold): Tasks 4-5. Design 3 (spec additions): Task 2 (+ docs Task 6, hooks Task 8). Design 4 (errors: hook failure, 400 on invalid, payload cap, viewer error containment): Tasks 2-4 (`BodyLimit`, `test_oversize_payload_is_rejected`, try/catch in `show`). Design 5 (testing 1-5): Task 1; Task 4; Task 2/3 and Task 7 Step 5 (`-Dry`); Tasks 7-9 (deploy + live); Task 6 (evals).
- Skill/file changes list: all covered (`app.py`, `tile-spec.md`, `SKILL.md`, `project-discovery.md` and `refresh-hook.md` in Task 6, the two hooks in Task 8, the compose line in Task 1).
- Out of scope respected (no change to Grafana's View, grid, new data sources, touch, push).

**Placeholder scan:** no TBD/TODO or "similar to Task N" left; every code step carries its code. Hook edits (Task 8) show the changed blocks and name the exact lines they replace in files that live outside the repo.

**Type consistency:** payload keys, targets (`square`, `stat:i`, `health:i`, `chart:i`, `kpi:i:j`), `wallOpen/wallShow/wallClose`, `{wallHold}` message, `MAX_BODY`/`MAX_PAYLOAD`, `data-wl-data`, `tgt`/`boot_html`/`tile_payload`/`payload_attr` are used with the same names in Tasks 2-5, the harness and the fixtures.

**Review Focus:** all five items have named tests in the tasks that own the code (Tasks 2, 3, 4, 5/9).
