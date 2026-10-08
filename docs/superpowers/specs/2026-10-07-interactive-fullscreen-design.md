# Interactive tiles: hover highlight and full-screen detail views

Date: 2026-10-07. Status: design approved in chat, spec awaiting review.

## Goal

On the Grafana monitor wall, let the viewer (mouse on the PC driving the TVs) explore any tile:

- Hover a clickable element and its whole box lights up faintly, showing it can be selected.
- Click the **top bar** (name + status) and the **whole square** opens full screen, resized to the screen, with a deeper breakdown: every chart large, every health light and stat explained.
- Click an **individual element** (a chart, a stat chip, a health light, a list icon such as mini-mac's 5 containers) and it opens full screen with more data and a short explanation:
  - an error/failing item: what it is, which system, what is going on;
  - a chart (e.g. canary errors): longer history, success/error percentages, what it measures, worst recent periods;
  - a list item (e.g. 5 containers): each member, its health, what it does.
- Esc (or clicking outside) closes the overlay. Text is concise, not verbose.
- `i` icons on elements show a short tooltip explanation on hover.

## Why the current "View" sizes badly

Tiles are Grafana text panels whose HTML uses fixed pixel sizes (`TILE_PX = 443`, `CARD_INNER_PX = 520`) and charts baked in as fixed-size base64 SVG images (`server/slot-writer/app.py`: `tile_v2_html`, `spark_img`). Grafana's built-in three-dots **View** only stretches the panel, so contents do not scale. We do not patch that; we draw our own full-screen views at the real viewport size, so they fit by construction. Grafana's native View is left alone and unused.

## Decision: approach B (approved)

Grafana's HTML sanitizer strips `<script>`, `:hover` styles and event handlers from text panels. Approved by the user: set `GF_PANELS_DISABLE_SANITIZE_HTML: "true"` on mini-mac's Grafana container (`~/monitoring/docker-compose.yml`, stock `grafana/grafana:latest`; back up the compose file first, then restart the grafana container). Rejected alternatives: (A) hotspot overlay in the `/wall/<uid>` wrapper page (hover outlines can drift by pixels because chip wrapping is estimated), (C) Business Text plugin (extra install, unproven).

Security note: the setting is global to that Grafana. Accepted because the wall is LAN-only, anonymous access is Viewer-only, and only the slot-writer (X-Wall-Key) writes wall dashboards. All spec text is still HTML-escaped by the server; only the server's own markup and script reach the page.

## Design

### 1. Tile markup gains interactivity

- Every clickable box (top bar, each stat chip, each health light, each chart box, each KPI) gets a `data-wall-target` id, a hover style and a click handler. Hover raises the border to the accent blue plus a soft glow over the whole box. Only the box under the cursor lights; the top bar lights as the "whole square" target.
- Hover styling comes from one `<style>` block per tile with class selectors. No external scripts or stylesheets.
- `i` icons carry the element's `explain` text as a native tooltip (`title`).
- Handlers are inline (`onclick`), calling a single global function `wallOpen(slot, target)`. Because scripts inside `innerHTML` do not execute, the tile embeds the viewer through a bootstrap element (an `<img onerror>` whose handler installs the viewer script once per page; the install is idempotent). Verified by the spike (Testing, step 1) before anything else is built.

### 2. Full-screen viewer

- One self-contained script, kept as a single constant in the server (`VIEWER_JS`), embedded once per page via the bootstrap above. It builds an overlay appended to `document.body` (not inside the panel, so panel transforms and overflow cannot clip it), filling the viewport.
- Three views, all drawn as real SVG/DOM at screen size, in the wall palette (dark blue/black/grey, white text, blue accent):
  - **Square view**: header (name, status pill, branch, activity); a large grid of all charts each with KPIs; health lights with state and explanation; stat chips with explanation; current task.
  - **Chart view**: one large chart over the long `history`; success vs error percentages and totals; "what this measures / what bad looks like"; worst recent buckets.
  - **Item view**: state, what it is, why it is in this state (from the hook), and a member list when `detail.items[]` exists (name, state, what it does).
- Esc or click outside closes. Hover on any element inside the overlay that has `explain` shows its tooltip.
- Auto-refresh hold: while an overlay is open the viewer sets `window.__wallHold = true`. The wrapper page's version-poll reload (`wall_page`) defers a pending reload until the flag clears; Grafana's 30 s refresh does not re-render unchanged text panels, so only the wrapper reload needs gating.

### 3. Spec additions (all optional, validated and size-capped like existing fields)

| Field | On | Notes |
|---|---|---|
| `explain` | each stat, health light, chart, KPI, and tile (`summary`) | Text, capped (about 200 chars). Written once by the skill's agent. |
| `history` | each chart | Longer window than `points`, same `[epoch, value]` shape, up to 400 points, plus `history_label` (e.g. `7d`). |
| `detail` | each stat and health light | `{ "why": text, "items": [{ "name", "state", "what" }] }`, up to 12 items. `state` as health lights (`up/degraded/down/unknown`). |
| `breakdown` | each chart | Optional `{ "ok_pct", "err_pct", "total", "worst": [{ "label", "value" }] }` precomputed by the hook; otherwise the viewer derives ok/err percentages from `history`. |

Missing data degrades gracefully: an element with no `detail` still opens a minimal view (its label, value, state, and `explain` if present). Existing tiles and hooks keep working unchanged.

Data flows: skill agent writes `explain` at tile creation; each project hook (canaries, mini-mac, others) adds live `history`, `detail`, `breakdown`; slot-writer validates, embeds a JSON payload plus the markup in the tile HTML; the viewer reads that payload on click. No new endpoints and no network call on click.

### 4. Error handling

- Hook failure: tile stays untouched (existing behaviour).
- Invalid new fields: `/snapshot` returns 400 naming the field (existing behaviour).
- Payload size: tiles now carry history and detail; the 64 KB request limit in `_body` is raised to a measured value (target: up to 256 KB) and a per-tile embedded-payload cap is enforced.
- Viewer errors are contained: a throw inside the overlay removes it and releases the hold flag, never leaving the wall stuck or the reload gate closed.

### 5. Testing

1. **Spike (throwaway scratch dashboard):** with the sanitizer off, confirm on this Grafana version that hover CSS, inline click handlers, the bootstrap-installed script, a body-level overlay and Esc all work in a text panel inside the wrapper iframe. Delete the scratch dashboard afterwards. If this fails, stop and fall back to approach A, re-brainstorming only that part.
2. Render the viewer to screenshots in headless Chrome at the wall's 1920x1080 with the 95% frame, one per view type, with and without optional data, long and short text.
3. `/snapshot?dry=1` against sample specs, including validation failures for each new field.
4. Deploy to mini-mac (backup `app.py` and the compose file first), then update the canaries and mini-mac tiles with real data and check hover and every view on the live wall.
5. Update `evals/evals.json` with a case for `explain` authoring, and keep the existing test tiles released afterwards.

## Skill and file changes

- `server/slot-writer/app.py`: field validation, tile markup (hover classes, targets, `i` icons, payload), `VIEWER_JS`, wrapper-page reload hold, larger body limit.
- `skills/grafana-wall/references/tile-spec.md`: document the new fields.
- `skills/grafana-wall/SKILL.md` and `references/project-discovery.md`, `refresh-hook.md`: tell the agent to write `explain` text and the hook to return `history`/`detail`.
- `examples/` hooks for canaries and mini-mac: return `history`, `detail` (the 5 containers with health and purpose), and `breakdown`.
- mini-mac `docker-compose.yml`: one env line, applied by the user-approved process above.

## Out of scope

Changing Grafana's native View, the wall grid layout, new data sources, touch input, and any push to GitHub (pushes stay with the user, per existing rules).

## Implementation base

This branch was cut from `main`. The unpushed `claude-skills-showcase` branch holds later work in the same files (slot `pin`, `showcase`, `wall.ps1` register fix) and the deployed `app.py` on mini-mac is the source of truth. Before implementing, rebase onto that branch (or merge it first) and diff against the deployed `app.py`.
