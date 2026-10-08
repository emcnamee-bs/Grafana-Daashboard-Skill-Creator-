# Tile spec (v2)

JSON sent to `POST /snapshot` (via `wall.ps1 snapshot -File tile.json`, or produced each refresh by merging a project's hook output into `.grafana-wall/tile.json`). The server validates strictly; errors name the field. All text is HTML-escaped by the server. Unknown keys are ignored.

## Fields

| Field | Type | Notes |
|---|---|---|
| `project` | slug, required | `[a-z0-9][a-z0-9_-]{0,39}`. The tile's identity; reusing it refreshes the same slot. |
| `name` | text, max 22 shown | Display name in the top bar. Defaults to `project`. |
| `status` | `ok` `warn` `fail` `idle` `building` | Pill colour. Default `idle`. |
| `status_label` | text ≤14 | Pill text that summarises state: `ALL GREEN`, `5 FAILING`, `DOWN`. Defaults to the status word. |
| `branch` | text ≤40 | The git chip. |
| `activity` | `{state, label?}` | `state`: `active` `idle` `stalled`; `label` ≤24 (the client stamps the time if omitted). |
| `stats` | up to **6** × `{label, value, trend?}` | Top-bar chips: `label` ≤16, `value` ≤12 chars of display text, `trend` `up` `down` `flat`. Typical: open PRs, failures 24h, checks failing. |
| `health` | up to 8 × `{name, state}` | Lights for the project's key parts. `state`: `up` `degraded` `down` `unknown`; `name` ≤18. |
| `task` | text ≤90 (52 shown) | What is in flight. |
| `charts` | up to 4 (use 2-3) | See below. |
| `tests`, `layout`, `series` | legacy | Only used by the legacy series-chart layout (below). |

## Charts (template v2: inline points)

```json
{ "title": "Provisioning", "subtitle": "errors / 15 min", "kind": "line", "span_label": "12h",
  "points": [[1791380700, 0], [1791381600, 2], ...],
  "kpis": [ {"label": "ERR 7D", "value": "0.5%", "state": "ok"}, {"label": "STREAK", "value": "128"} ] }
```
- `points`: up to 200 `[epoch_seconds, value]` pairs (or `{"t":..,"v":..}` objects). Use ~24-60 points on clean time buckets.
- `kind`: `line` (default) or `bar`. `title` ≤22, `subtitle` ≤26, `span_label` ≤8 (shows as `-12h` at the left of the footer; the footer also shows the max and `now`).
- `y_max` (optional number): fixes the top of the y-axis; the left axis shows `y_max`, half of it, and `0`, with gridlines at the top and middle. Use it when the viewer should read a fixed scale (e.g. `10` errors per bucket). If a point exceeds it the axis grows to the next clean value so nothing is clipped. Without it the axis auto-fits to a clean value (1, 2, 5, 10, 20, 50, ...).
- `kpis`: up to 2 chips per chart: `label` ≤12, `value` ≤10, optional `state` `ok`/`warn`/`bad` (colours the value).
- 2-3 charts are laid side by side in one landscape row at equal width; do not mix points charts and series charts in one tile.

The tile is one card: top bar (name, status, git chip, activity, stat chips, health lights, task) over the chart row. Every item has its own border. With no charts the top bar fills the square.

## Legacy series charts

`{ "title", "series", "kind": line|bar|stat, "span": 1h..90d|all, "unit", "share" }` draws native Grafana panels reading numbers pushed with `wall.ps1 series` (history starts at the first push). Kept for compatibility and for cases where a live Grafana panel is wanted; the fixed template above is preferred.

## Example (a services project)

```json
{
  "project": "canaries", "name": "Canaries", "status": "warn", "status_label": "5 FAILING", "branch": "main",
  "activity": {"state": "idle", "label": "16d+"}, "task": "PR #44: Add HTTP notice intake to failure-log-capture",
  "health": [{"name": "CI build", "state": "up"}, {"name": "Provisioning", "state": "up"},
             {"name": "Update", "state": "degraded"}, {"name": "Content", "state": "up"}],
  "stats": [{"label": "Failures 24h", "value": "7"}, {"label": "Checks failing", "value": "5"}, {"label": "Open PRs", "value": "1"}],
  "charts": [ {"title": "Provisioning", "subtitle": "errors / 15 min", "points": [...], "span_label": "12h",
               "kpis": [{"label": "ERR 7D", "value": "0.5%", "state": "ok"}, {"label": "STREAK", "value": "128"}]},
              {"title": "Update", "...": "..."}, {"title": "Content", "...": "..."} ]
}
```
