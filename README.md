# Grafana wall

A wall of 18 live project tiles on three kiosk monitors, fed by a Claude Code skill.

```
Claude Code skill (grafana-wall)  --tile spec JSON-->  slot-writer  --draws-->  Grafana dashboards wall-top / wall-middle / wall-bottom
        |                                                   |
        '-- wall.ps1 series (live numbers) --> slot-writer --> Pushgateway --> Prometheus --> chart panels
```

| Path | What |
|---|---|
| `skills/grafana-wall/` | The skill (`SKILL.md`, `references/`, `scripts/wall.ps1`). Copy to `~/.claude/skills/grafana-wall`. |
| `server/slot-writer/` | Stdlib-Python service (Docker) on the Grafana host: validates specs, claims slots, pushes series, redraws tiles. |
| `board/build_board.ps1` | Builds the blank 18-slot board (3 dashboards x 6 slots). |
| `kiosk/` | Windows supervisor (`GrafanaWall.ps1`, `Install.ps1`, `monitors.example.json`): one fullscreen Chrome window per monitor, restarts crashed windows, and **reloads a window when its dashboard is redrawn** (Grafana never re-reads layout on its own). |

## Slots

Slots 01-06 are the top monitor, 07-12 middle, 13-18 bottom. A new project takes the lowest vacant slot, so a monitor fills before the next one is used. A project keeps its slot when refreshed.

## Server API (`X-Wall-Key` header required except `/health`)

| Call | Purpose |
|---|---|
| `GET /slots` | Slot states and owners |
| `POST /snapshot[?dry=1]` | Validate a tile spec, claim/refresh a slot, redraw (dry = report only) |
| `POST /series` | Push live chart values without redrawing |
| `POST /release/<n>` | Return a slot to vacant |

Tile spec: `skills/grafana-wall/references/tile-spec.md`. Layout and colours live in the `CONFIG` block at the top of `app.py`.

## Deploying the server

On the Grafana host, with the compose stack in `~/monitoring`: copy `server/slot-writer/` to `~/monitoring/slot-writer/`, create `.env` there with `GRAFANA_TOKEN` (service-account token, Editor) and `WALL_KEY` (shared secret), then `docker compose up -d --build slot-writer`. Prometheus should run with `--storage.tsdb.retention.time=5y` so "all-time" charts stay true. Never commit `.env`.

## Client configuration

`WALL_URL` + `WALL_KEY` environment variables, or `~/.grafana-wall.json` = `{"url": "http://<host>:8088", "key": "<WALL_KEY>"}`.

## Automatic refresh

`skills/grafana-wall/scripts/Install-Refresh.ps1` registers a scheduled task that runs `wall-refresh.ps1` every 2 minutes. For each project registered with `wall.ps1 register` it keeps the git branch and activity current, runs the project's optional `.grafana-wall/refresh.ps1` hook (status, tests, health, stats, chart series) and redraws the tile only when something visible changed. Details: `skills/grafana-wall/references/refresh-hook.md`.