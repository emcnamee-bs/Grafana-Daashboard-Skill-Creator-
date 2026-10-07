# Tile spec (v1)

JSON sent to `POST /snapshot` (via `wall.ps1 snapshot -File tile.json`). The server validates strictly; errors name the field. All text is HTML-escaped by the server. Unknown keys are ignored.

| Field | Type | Notes |
|---|---|---|
| `project` | slug, required | `[a-z0-9][a-z0-9_-]{0,39}`. The tile's identity; reusing it refreshes the same slot. |
| `name` | text ≤28 | Display name in the top bar. Defaults to `project`. |
| `status` | `ok` `warn` `fail` `idle` `building` | Pill colour. Default `idle`. |
| `status_label` | text ≤14 | Optional pill text (e.g. `LIVE`, `PAPER`); defaults to the status word. |
| `branch` | text ≤40 | From `git branch --show-current`. |
| `activity` | `{state, label?}` | `state`: `active` `idle` `stalled`. `label` ≤24 (the client stamps local time if omitted). |
| `task` | text ≤90 | Current objective. |
| `tests` | `{passed, failed, skipped?, label?}` | Renders a pass/fail bar. |
| `health` | up to 8 × `{name, state}` | `state`: `up` `degraded` `down` `unknown`. Name ≤18 (e.g. `Kalshi API`, `EC2 trader`). Up to 4 fit one row. |
| `stats` | up to 4 × `{label, value, trend?}` | `value` ≤12 chars as display text (`+$184`, `61%`). `trend`: `up` `down` `flat`. |
| `charts` | up to 4 × chart | See below. |
| `series` | `{name: number}` (≤20) | Current values, pushed to Prometheus as `wall_series{project, series}`. Charts read these by name. |
| `layout` | `{chart_min_h?, pin?}` | `chart_min_h` 0-9 grid units reserved for charts; `pin` lists info modules (`task` `tests` `health` `stats`) that must not be dropped. |

**chart** = `{title ≤30, series, kind, span, unit, share}`
- `series`: name of a series (`[A-Za-z0-9_.-]{1,40}`) pushed in `series` or via `wall.ps1 series`.
- `kind`: `line` (default), `bar`, `stat` (big number with sparkline).
- `span`: `1h` `6h` `24h` `7d` `30d` `90d` or `all` (since the first sample; widened on each snapshot refresh).
- `unit`: `none` `short` `percent` `percentunit` `currencyUSD` `bytes` `s` `ms` `ops` `reqps`.
- `share`: width weight 0.25-4 when two charts share a row (default 1).

## Live vs snapshot

Header, task, tests, health and stats are drawn at snapshot time (static until the next snapshot). Charts are live: Grafana re-queries Prometheus every 30 s, and Prometheus samples whatever was last pushed every 15 s. Push series continuously with `wall.ps1 series -Project slug earnings=4821.5`; re-snapshot when the static parts change. Retention is 5 years.

## Example 1: trading bot (user said: "dedicate space to an all-time earnings line chart")

```json
{
  "project": "kalshi-bot", "name": "Kalshi Trader", "status": "ok", "branch": "feat/maker-orders",
  "activity": {"state": "active"},
  "tests": {"passed": 128, "failed": 2},
  "health": [{"name": "Kalshi API", "state": "up"}, {"name": "Postgres", "state": "up"}, {"name": "EC2 trader", "state": "degraded"}],
  "stats": [{"label": "P&L today", "value": "+$184", "trend": "up"}, {"label": "Open pos", "value": "7"}, {"label": "Win rate", "value": "61%"}],
  "charts": [{"title": "All-time earnings", "series": "earnings", "kind": "line", "span": "all", "unit": "currencyUSD", "share": 2},
             {"title": "Fills / hr", "series": "fills", "kind": "bar", "span": "24h"}],
  "series": {"earnings": 4821.5, "fills": 12},
  "layout": {"chart_min_h": 6}
}
```
Result: top bar + tests/health/stats (task dropped to honor 6 units of chart space).

## Example 2: small API integration, nothing to chart

```json
{
  "project": "weather-sync", "name": "Weather Sync", "status": "warn", "branch": "main",
  "activity": {"state": "idle"}, "task": "Retry queue draining after 429s",
  "health": [{"name": "OpenWeather", "state": "degraded"}, {"name": "S3 bucket", "state": "up"}]
}
```
Result: the info card fills the whole tile.
