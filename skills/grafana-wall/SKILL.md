---
name: grafana-wall
description: Put the current project on the user's Grafana monitor wall - claims the next vacant square (18 squares across 3 monitors) and fills it with a live status tile - project name, status, git branch, activity, plus whatever fits this project (current task, test results, API/service/AWS health, stats, data charts such as an all-time earnings line). Also refreshes or releases a project's square. Use this whenever the user mentions the wall, the monitors, the Grafana square/tile/board/dashboard for a project, "put this on the wall", "show this project on my screens", "update my tile", "free up the slot", or wants any project's live status visible on the Grafana displays - even if they don't say "skill". Accepts free-text guidance when invoked (e.g. "make sure it has an all-time earnings chart") and during the run.
---

# Grafana wall

The user has three TVs running a Grafana "wall": 18 squares (slots 01-18, six per monitor: top 01-06, middle 07-12, bottom 13-18). Each running project gets one square. A square is a status card for a project that talks to APIs, so a glance should answer: is it alive, is it healthy, what is it doing, is it making progress.

You build a **tile spec** (a small JSON file) from what you can learn about the project, send it to the wall server, and the server draws the square. You decide *what is worth showing*; the server decides *how it is laid out* so every square looks like part of one wall.

## Before you start

1. Run `& "$HOME\.claude\skills\grafana-wall\scripts\wall.ps1" slots` (call the script by absolute path; you will usually be sitting in the project's folder, not the skill's). It prints all 18 slots. If it fails with a connection error, the wall is not configured or mini-mac is down: tell the user plainly and stop; do not guess keys or URLs. Setup is `WALL_URL`+`WALL_KEY` env vars or `~/.grafana-wall.json` (`{"url":"http://mini-mac:8088","key":"..."}`).
2. Note whether this project already owns a slot (the project slug appears in the listing). If it does, you are *refreshing*, not claiming, and the slot stays the same.
3. If the wall is full, say who occupies what and ask which to release. Never release another project's slot without being told to.

## Treat the user's guidance as the brief

Anything the user said when invoking the skill ("dedicate space to an all-time earnings chart", "show EC2 health", "keep it minimal") is a requirement, not a hint. Satisfy it first, then use judgment for the rest. If they speak up mid-run, fold it in and re-render. When guidance is ambiguous in a way that changes the tile (which number is "earnings"? which instance counts?), ask one short batched question rather than guessing. If it is not ambiguous, do not ask - decide, and tell them what you chose so they can redirect. When the user asked for something you cannot do yet (say, health for an AWS resource you have no access to), do not stall: publish that item as `unknown`, finish the tile, and put one specific question in your report-back (which bucket/profile, may I run which read-only command) so it can be made live next.

## What every tile has, and what is optional

The top bar is fixed and always present: **project name**, **status** pill, **git branch** (small chip) and **activity** (small chip, about equal weight to the branch). Everything below is included only when you have *real* data for it, because an empty or invented module is worse than none. Rough priority when space is tight: charts the user asked for > health > stats > tests > current task.

| Module | Include when | Source ideas |
|---|---|---|
| `task` | there is a clear current objective | latest in-progress todo, current branch/PR title, top of a TODO/plan file |
| `tests` | a test run result exists or is cheap to produce | last pytest/jest/junit result; run the fast suite only if the user agrees |
| `health` | the project depends on external APIs/services/hosts | cheap read-only probes of each dependency (see below) |
| `stats` | 2-4 numbers define "how is it going" | P&L, requests/min, queue depth, jobs done, error rate |
| `charts` | a number evolves over time and the trend matters | any series you can push repeatedly (see below) |

Read `references/project-discovery.md` for how to find the project's APIs, services, tests and metric candidates quickly and safely (what to read, what never to read, how to probe health). Read `references/tile-spec.md` for the exact fields, limits and two worked examples before writing the JSON.

## Workflow

1. **Identify**: slug = the project's folder (or repo) name, lowercased with non-alphanumerics turned into `-`; it is the tile's identity, so keep it stable. The display `name` can come from the README title instead. Also `git branch --show-current`; a missing git remote is fine, just skip it. Keep the name short; it renders at ~30px in a 600px-wide card.
2. **Discover** per `project-discovery.md`. Spend a few minutes, not an hour: manifests, env-var *names*, README, base URLs in code, docker-compose/terraform, test config. Never open `.env` files or print secrets; secrets must not appear in the spec.
3. **Decide the tile.** Choose modules, then choose health probes and series. For each series decide *who will keep it fresh* (next step). Statuses: `ok` working, `warn` degraded or tests failing, `fail` down or broken, `idle` nothing running, `building` uncommitted changes, a deploy in flight, or a feature branch with commits in the last ~15 min. Activity: `active` (work or runs in the last ~15 min), `idle`, `stalled` (should be running but is not).
4. **Make the data live.** A snapshot is a picture at one moment. Two things keep it true; read `references/refresh-hook.md` for both:
   - **Auto-refresh** (do this by default): after the first publish, run `wall.ps1 register` from the project folder. A scheduled task (`GrafanaWallRefresh`, install once per machine with `scripts/Install-Refresh.ps1` if `Get-ScheduledTask GrafanaWallRefresh` finds nothing) then keeps branch and activity current every 2 minutes and redraws only when something visible changed.
   - **A refresh hook** (`.grafana-wall/refresh.ps1`) for anything project-specific: status, tests, health probes, stats and chart series. It prints one JSON object and refresh merges it. Write it yourself from what you discovered, keep it read-only and cheap, and show the user what it checks. For a chart's numbers, the best source is the project's own code at the moment the number changes (a one-line `wall.ps1 series -Project <slug> name=value` after a trade settles); ask before editing their project code.
   History begins at the first push, so say so when the user wants an "all-time" chart on a series that has no history yet.
5. **Validate**: write the spec to `.grafana-wall/tile.json` in the project, then `scripts/wall.ps1 snapshot -File .grafana-wall/tile.json -Dry`. It reports the slot and which modules fit. If a requested module was dropped for space, either shrink something (`layout.chart_min_h`, `layout.pin`) or tell the user what was dropped and why.
6. **Publish**: the same command without `-Dry`. Then run `wall.ps1 slots` to confirm the slot shows your project. If a requested chart's series has no samples yet, still publish it so its space is reserved, but tell the user it will read "No data" on the wall until the first push, and offer to push a first real value now if one can be read cheaply and safely. Never push a placeholder number to fill it.
7. **Report back** in a few lines: which slot/monitor, what the tile shows, what refreshes automatically and what the hook checks, how to release (`wall.ps1 release -Slot N`, which also stops auto-refresh), and anything you chose that they may want changed. A redraw makes that monitor reload for a couple of seconds; mention it once. Ask what to adjust; layout is expected to evolve.

## Layout judgment calls (the server enforces these, you steer them)

- The tile is 13 grid units tall: 3 for the top bar, then info modules (1-2 units each), and charts take the remainder (4 units minimum when charts exist). With no charts the info card fills the tile.
- `layout.chart_min_h` (units, 0-9) reserves chart space; the server drops lowest-priority info modules to honor it, never ones listed in `layout.pin`. Rule of thumb for the user's wording: "some room for a chart" = 4 (the default), "a good chunk" = 6, "a big share" or "mostly the chart" = 8.
- Up to 4 charts; two share a row. `share` (0.25-4) weights widths. Prefer 1-2 charts; more makes each unreadable at TV distance.
- Colours are fixed by the wall palette (dark blue/black/grey, white and blue accents; green/amber/red only for health and status). Do not try to style the tile.

## Guardrails

- Everything you send is rendered on a TV in a shared space: no secrets, tokens, account numbers, customer names, or anything the user would not want visible. Dollar amounts and trade P&L are the user's call; if unsure, ask once.
- Health probes must be read-only and cheap (HTTP GET to a status/health URL, `aws ... describe-*`, a TCP connect). Never trigger side effects, spend money, or hammer an API. If a probe needs credentials the project does not already use, ask first.
- One project, one slot. Refresh in place; do not create duplicates by changing the slug. When the user asks to free a slot, use `wall.ps1 release`: it also unregisters the project, otherwise auto-refresh would redraw it a couple of minutes later.
- If something fails (server 4xx/5xx, validation error), read the error body: validation errors name the offending field. Fix and retry; do not hide failures from the user.
