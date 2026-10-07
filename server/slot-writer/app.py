#!/usr/bin/env python3
"""slot-writer: holds the Grafana token server-side and renders/releases wall slots.
Stdlib only. Endpoints (all but /health need header X-Wall-Key):
  GET  /health
  GET  /slots                    per-slot vacant/occupied (+ project slug)
  POST /snapshot[?dry=1]         validate a tile spec, claim (or reuse) a slot, push series, redraw the tile
  POST /series                   push live series values only (no redraw): {"project": slug, "series": {name: value}}
  POST /release/<slot>           put the vacant tile back
Tile spec: see skills/grafana-wall/references/tile-spec.md
"""
import hmac, html, json, math, os, re, threading, time, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- CONFIG: tile look + grid constants live here so they are easy to change ----
CONFIG = {
    "grafana_url": os.environ.get("GRAFANA_URL", "http://grafana:3000"),
    "pushgateway_url": os.environ.get("PUSHGATEWAY_URL", "http://pushgateway:9091"),
    "prometheus_url": os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
    "datasource_uid": "prometheus",
    "dashboards": [("wall-top", 1, 6), ("wall-middle", 7, 12), ("wall-bottom", 13, 18)],  # (uid, first, last)
    "cols": 3, "panel_w": 8, "panel_h": 13,   # grid units per slot (24 wide / 3 cols)
    "header_h": 3,                            # units used by the fixed top bar inside the info card
    "min_chart_h": 4,                         # default floor for the chart region when charts exist
    "num_size_px": 43, "num_color": "#1f3a5f", "vacant_size_px": 14, "vacant_color": "#3b4f6b",
    "border": "1px solid #1f5fae", "radius": "8px", "glow": "inset 0 0 18px rgba(31,95,174,.25)",
    "card_bg": "linear-gradient(165deg,#08101c,#0c1a2e)",
    "accent": "#4da3ff", "text": "#e8eefc", "muted": "#8fa6c8",
    "vacant_marker": "wall:vacant",
    "status_colors": {"ok": "#2f81f7", "warn": "#d29922", "fail": "#f85149", "idle": "#6e7681", "building": "#58a6ff"},
    "health_colors": {"up": "#3fb950", "degraded": "#d29922", "down": "#f85149", "unknown": "#6e7681"},
    "activity_colors": {"active": "#4da3ff", "idle": "#6e7681", "stalled": "#d29922"},
    "span_map": {"1h": "1h", "6h": "6h", "24h": "24h", "7d": "7d", "30d": "30d", "90d": "90d", "all": "5y"},
    "units": ["none", "short", "percent", "percentunit", "currencyUSD", "bytes", "s", "ms", "ops", "reqps"],
}
# ---------------------------------------------------------------------------------

TOKEN = os.environ["GRAFANA_TOKEN"]
KEY = os.environ["WALL_KEY"]
LOCK = threading.Lock()
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
SNAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
TAG = re.compile(r"^wall:s(\d\d):(.+)$")
ALL_SLOTS = [s for _, a, b in CONFIG["dashboards"] for s in range(a, b + 1)]


# ------------------------------------------------------------------ http helpers
def grafana(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CONFIG["grafana_url"] + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "{}")


def push(path, text):
    req = urllib.request.Request(CONFIG["pushgateway_url"] + path, data=text.encode(), method="POST",
                                 headers={"Content-Type": "text/plain; version=0.0.4"})
    urllib.request.urlopen(req, timeout=5).read()


def dash_for(slot):
    for uid, a, b in CONFIG["dashboards"]:
        if a <= slot <= b:
            return uid, slot - a
    raise ValueError("slot must be 1-18")


# ------------------------------------------------------------------ validation
def _s(v, field, n, required=False):
    if v is None or v == "":
        if required:
            raise ValueError("%s is required" % field)
        return None
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise ValueError("%s must be text" % field)
    return str(v).strip()[:n]


def _num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError("%s must be a finite number" % field)
    return float(v)


def validate(spec):
    if not isinstance(spec, dict):
        raise ValueError("body must be a JSON object")
    out = {}
    out["project"] = _s(spec.get("project"), "project", 40, True)
    if not SLUG.match(out["project"]):
        raise ValueError("project must be a lowercase slug (a-z 0-9 _ -, max 40)")
    out["name"] = _s(spec.get("name"), "name", 28) or out["project"]
    out["status"] = _s(spec.get("status"), "status", 12) or "idle"
    if out["status"] not in CONFIG["status_colors"]:
        raise ValueError("status must be one of %s" % sorted(CONFIG["status_colors"]))
    out["status_label"] = _s(spec.get("status_label"), "status_label", 14)
    out["branch"] = _s(spec.get("branch"), "branch", 40) or "-"
    a = spec.get("activity") or {}
    out["activity"] = {"state": _s(a.get("state"), "activity.state", 10) or "idle", "label": _s(a.get("label"), "activity.label", 24)}
    if out["activity"]["state"] not in CONFIG["activity_colors"]:
        raise ValueError("activity.state must be one of %s" % sorted(CONFIG["activity_colors"]))
    out["task"] = _s(spec.get("task"), "task", 90)
    t = spec.get("tests")
    if t:
        p, f = int(_num(t.get("passed", 0), "tests.passed")), int(_num(t.get("failed", 0), "tests.failed"))
        out["tests"] = {"passed": max(p, 0), "failed": max(f, 0), "skipped": max(int(_num(t.get("skipped", 0), "tests.skipped")), 0),
                        "label": _s(t.get("label"), "tests.label", 20)}
    hl = spec.get("health") or []
    if len(hl) > 8:
        raise ValueError("health: max 8 entries")
    out["health"] = []
    for h in hl:
        st = _s(h.get("state"), "health.state", 10) or "unknown"
        if st not in CONFIG["health_colors"]:
            raise ValueError("health.state must be one of %s" % sorted(CONFIG["health_colors"]))
        out["health"].append({"name": _s(h.get("name"), "health.name", 18, True), "state": st})
    sl = spec.get("stats") or []
    if len(sl) > 4:
        raise ValueError("stats: max 4 entries")
    out["stats"] = [{"label": _s(x.get("label"), "stats.label", 16, True), "value": _s(x.get("value"), "stats.value", 12, True),
                     "trend": _s(x.get("trend"), "stats.trend", 5) if _s(x.get("trend"), "stats.trend", 5) in ("up", "down", "flat") else None}
                    for x in sl]
    cl = spec.get("charts") or []
    if len(cl) > 4:
        raise ValueError("charts: max 4 entries")
    out["charts"] = []
    for c in cl:
        series = _s(c.get("series"), "charts.series", 40, True)
        if not SNAME.match(series):
            raise ValueError("charts.series must match [A-Za-z0-9_.-]{1,40}")
        kind = _s(c.get("kind"), "charts.kind", 6) or "line"
        span = _s(c.get("span"), "charts.span", 4) or "24h"
        unit = _s(c.get("unit"), "charts.unit", 20) or "none"
        if kind not in ("line", "bar", "stat") or span not in CONFIG["span_map"] or unit not in CONFIG["units"]:
            raise ValueError("charts: kind in line|bar|stat, span in %s, unit in %s" % (sorted(CONFIG["span_map"]), CONFIG["units"]))
        share = _num(c.get("share", 1), "charts.share")
        out["charts"].append({"title": _s(c.get("title"), "charts.title", 30) or series, "series": series, "kind": kind,
                              "span": span, "unit": unit, "share": min(max(share, 0.25), 4.0)})
    ser = spec.get("series") or {}
    if not isinstance(ser, dict) or len(ser) > 20:
        raise ValueError("series: object with max 20 entries")
    out["series"] = {}
    for k, v in ser.items():
        if not SNAME.match(str(k)):
            raise ValueError("series name %r invalid" % k)
        out["series"][str(k)] = _num(v, "series." + str(k))
    lay = spec.get("layout") or {}
    cmh = lay.get("chart_min_h")
    out["chart_min_h"] = int(min(max(_num(cmh, "layout.chart_min_h"), 0), 9)) if cmh is not None else None
    pin = lay.get("pin") or []
    out["pin"] = [p for p in pin if p in ("task", "tests", "health", "stats")]
    return out


# ------------------------------------------------------------------ rendering
def esc(x):
    return html.escape(str(x), quote=True)


def plan(sp):
    """Decide which info blocks fit and how many grid units they take; the rest of the tile goes to charts."""
    c = CONFIG
    H, hdr = c["panel_h"], c["header_h"]
    blocks = {}
    if sp["task"]: blocks["task"] = 1
    if sp.get("tests"): blocks["tests"] = 1
    if sp["health"]: blocks["health"] = 1 if len(sp["health"]) <= 4 else 2
    if sp["stats"]: blocks["stats"] = 2
    if not sp["charts"]:
        return blocks, H                                   # info card fills the whole tile
    want = max(sp["chart_min_h"] if sp["chart_min_h"] is not None else 0, c["min_chart_h"])
    fits = lambda: H - hdr - sum(blocks.values()) >= want
    if "health" in blocks: blocks["health"] = 1            # compact: health chips shrink to one row before anything is dropped
    for k in ("task", "tests", "stats", "health"):         # then drop lowest-priority blocks first (never pinned ones)
        if fits(): break
        if k in blocks and k not in sp["pin"]: del blocks[k]
    return blocks, hdr + sum(blocks.values())


def info_html(sp, blocks, roomy=False):
    c = CONFIG
    sc = c["status_colors"][sp["status"]]
    label = esc((sp["status_label"] or sp["status"]).upper())
    ac = c["activity_colors"][sp["activity"]["state"]]
    alab = esc(sp["activity"]["state"] + (" · " + sp["activity"]["label"] if sp["activity"]["label"] else ""))
    chip = "display:inline-block;padding:3px 10px;border-radius:12px;background:rgba(77,163,255,.10);border:1px solid rgba(77,163,255,.25);"
    # negative margin: grow the card over the panel's own 8px padding so it lines up flush with the chart panels below it
    parts = ["<div style='box-sizing:border-box;margin:-8px;height:calc(100%% + 16px);padding:14px 18px;border:%s;border-radius:%s;box-shadow:%s;background:%s;"
             "display:flex;flex-direction:column;justify-content:space-between;font-family:Inter,sans-serif;color:%s;overflow:hidden'>"
             % (c["border"], c["radius"], c["glow"], c["card_bg"], c["text"])]
    parts.append("<div><div style='display:flex;align-items:center;justify-content:space-between;gap:10px'>"
                 "<div style='font-size:30px;font-weight:700;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>%s</div>"
                 "<div style='flex:none;padding:4px 14px;border-radius:14px;background:%s;color:#fff;font-size:15px;font-weight:700;letter-spacing:.12em'>%s</div></div>"
                 "<div style='margin-top:6px;font-size:14px;color:%s;display:flex;gap:8px;flex-wrap:wrap'>"
                 "<span style='%s'>&#9095; %s</span>"
                 "<span style='%s'><span style='color:%s'>&#9679;</span> %s</span></div></div>"
                 % (esc(sp["name"]), sc, label, c["muted"], chip, esc(sp["branch"]), chip, ac, alab))
    k = 1.35 if roomy else 1.0      # roomy = no charts, so the card is the whole tile: bigger type and more air
    S = lambda n: int(round(n * k))
    body = []
    if "task" in blocks:
        body.append("<div style='font-size:%dpx;color:%s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                    "<span style='color:%s;letter-spacing:.12em;font-size:%dpx'>NOW</span>&nbsp; %s</div>" % (S(15), c["text"], c["muted"], S(12), esc(sp["task"])))
    if "tests" in blocks:
        t = sp["tests"]; tot = max(t["passed"] + t["failed"] + t["skipped"], 1)
        pw, fw = 100.0 * t["passed"] / tot, 100.0 * t["failed"] / tot
        body.append("<div style='font-size:%dpx;color:%s'><div style='display:flex;justify-content:space-between'><span style='letter-spacing:.12em;font-size:%dpx'>%s</span>"
                    "<span style='color:%s'>%d passed%s</span></div><div style='height:%dpx;border-radius:4px;background:#1a2640;margin-top:4px;display:flex;overflow:hidden'>"
                    "<div style='width:%.1f%%;background:#3fb950'></div><div style='width:%.1f%%;background:#f85149'></div></div></div>"
                    % (S(13), c["muted"], S(12), esc((t["label"] or "TESTS").upper()), c["text"], t["passed"], (" &middot; <span style='color:#f85149'>%d failed</span>" % t["failed"]) if t["failed"] else "", S(7), pw, fw))
    if "health" in blocks:
        chips = "".join("<span style='display:inline-block;margin:0 %dpx 4px 0;font-size:%dpx'><span style='color:%s'>&#9679;</span> %s</span>"
                        % (S(12), S(14), c["health_colors"][h["state"]], esc(h["name"])) for h in sp["health"])
        body.append("<div style='line-height:1.35'>%s</div>" % chips)
    if "stats" in blocks:
        cells = []
        for s in sp["stats"]:
            arrow = {"up": "<span style='color:#3fb950'>&#9650;</span>", "down": "<span style='color:#f85149'>&#9660;</span>", "flat": ""}.get(s["trend"], "")
            cells.append("<div style='flex:1;min-width:0'><div style='font-size:%dpx;font-weight:700;white-space:nowrap'>%s %s</div>"
                         "<div style='font-size:%dpx;letter-spacing:.1em;color:%s'>%s</div></div>" % (S(26), esc(s["value"]), arrow, S(11), c["muted"], esc(s["label"].upper())))
        body.append("<div style='display:flex;gap:10px'>%s</div>" % "".join(cells))
    # (Grafana's sanitizer drops flex:1 / zoom, so the body can't be told to grow; auto margins centre it in the free space instead)
    style = "margin:auto 0;display:flex;flex-direction:column;gap:26px;" if roomy else "display:flex;flex-direction:column;gap:8px;"
    parts.append("<div style='%s'>%s</div>" % (style, "".join(body)) if body else "")
    parts.append("</div>")
    return "".join(parts)


def all_span(project, series):
    """'all' = since the series' first sample (a fixed 5y range makes Grafana's query step days wide, so young data vanishes)."""
    try:
        q = urllib.parse.urlencode({"query": 'wall_series{project="%s",series="%s"}' % (project, series),
                                    "start": int(time.time()) - 5 * 365 * 86400, "end": int(time.time()), "step": 86400})
        with urllib.request.urlopen(CONFIG["prometheus_url"] + "/api/v1/query_range?" + q, timeout=8) as r:
            res = json.loads(r.read())["data"]["result"]
        first = min(float(v[0]) for s in res for v in s["values"])
        age = max(time.time() - first, 0)
    except Exception:
        return "6h"
    hours = int(age // 3600) + 2
    return "%dh" % min(hours, 24 * 14) if hours <= 24 * 14 else "%dd" % min(int(hours // 24) + 1, 1825)


def chart_panel(ch, sp, pid, gp, tag):
    c = CONFIG
    expr = 'wall_series{project="%s",series="%s"}' % (sp["project"], ch["series"])   # both validated: no quotes possible
    span = all_span(sp["project"], ch["series"]) if ch["span"] == "all" else c["span_map"][ch["span"]]
    # no description here (it adds an info icon that eats the title); ownership comes from the panel id range instead
    base = {"id": pid, "title": ch["title"], "gridPos": gp, "transparent": False, "hideTimeOverride": True, "maxDataPoints": 600,
            "datasource": {"type": "prometheus", "uid": c["datasource_uid"]}, "timeFrom": span,
            "targets": [{"refId": "A", "expr": expr, "legendFormat": ch["title"], "datasource": {"type": "prometheus", "uid": c["datasource_uid"]}}]}
    color = {"mode": "fixed", "fixedColor": c["accent"]}
    if ch["kind"] == "stat":
        base.update({"type": "stat", "fieldConfig": {"defaults": {"unit": ch["unit"], "color": color}, "overrides": []},
                     "options": {"colorMode": "none", "graphMode": "area", "textMode": "value", "reduceOptions": {"calcs": ["lastNotNull"]}}})
    else:
        bar = ch["kind"] == "bar"
        base.update({"type": "timeseries", "fieldConfig": {"defaults": {"unit": ch["unit"], "color": color, "custom": {
            "drawStyle": "bars" if bar else "line", "lineWidth": 2, "fillOpacity": 70 if bar else 14, "gradientMode": "opacity",
            "showPoints": "never", "lineInterpolation": "smooth", "spanNulls": True, "axisPlacement": "auto"}}, "overrides": []},
            "options": {"legend": {"showLegend": False}, "tooltip": {"mode": "single"}}})
    return base


def render_tile(slot, idx, sp):
    c = CONFIG
    W, H = c["panel_w"], c["panel_h"]
    r, col = divmod(idx, c["cols"])
    ox, oy = col * W, r * H
    base_id = 1000 + slot * 10
    tag = "wall:s%02d:%s" % (slot, sp["project"])
    blocks, info_h = plan(sp)
    panels = [{"id": base_id, "type": "text", "title": "", "transparent": True, "description": tag,
               "gridPos": {"x": ox, "y": oy, "w": W, "h": info_h}, "options": {"mode": "html", "content": info_html(sp, blocks, roomy=not sp["charts"])}}]
    charts, ch_h = sp["charts"], H - info_h
    if charts and ch_h > 0:
        rows = [charts[:2], charts[2:4]] if (len(charts) > 2 and ch_h >= 4) else [charts[:2]]
        row_h = [ch_h // len(rows)] * len(rows); row_h[-1] += ch_h - sum(row_h)
        y = oy + info_h; n = 0
        for rc, rh in zip(rows, row_h):
            tot = sum(x["share"] for x in rc); x0 = ox
            for i, ch in enumerate(rc):
                w = W if len(rc) == 1 else (min(max(round(W * ch["share"] / tot), 3), W - 3) if i == 0 else ox + W - x0)
                n += 1
                panels.append(chart_panel(ch, sp, base_id + n, {"x": x0, "y": y, "w": w, "h": rh}, tag))
                x0 += w
            y += rh
    return panels, {"slot": slot, "info_blocks": sorted(blocks), "info_h": info_h, "chart_h": max(ch_h, 0), "charts": len(charts)}


def vacant_tile(slot, idx):
    c = CONFIG
    r, col = divmod(idx, c["cols"])
    n = "%02d" % slot
    h = ("<div style='box-sizing:border-box;height:100%%;border:%s;border-radius:%s;box-shadow:%s;display:flex;"
         "flex-direction:column;align-items:center;justify-content:center;font-family:Inter,sans-serif;"
         "letter-spacing:.2em'><div style='font-size:%dpx;font-weight:700;color:%s'>%s</div>"
         "<div style='font-size:%dpx;color:%s'>VACANT</div></div>") % (
        c["border"], c["radius"], c["glow"], c["num_size_px"], c["num_color"], n, c["vacant_size_px"], c["vacant_color"])
    return {"id": slot, "type": "text", "title": "", "transparent": True, "description": c["vacant_marker"],
            "gridPos": {"x": col * c["panel_w"], "y": r * c["panel_h"], "w": c["panel_w"], "h": c["panel_h"]},
            "options": {"mode": "html", "content": h}}


# ------------------------------------------------------------------ slot state
def owner(p, uid_first):
    """-> ('vacant', slot) | ('occupied', slot, project) | None for one panel."""
    d = p.get("description", "") or ""
    m = TAG.match(d)
    if m:
        return ("occupied", int(m.group(1)), m.group(2))
    pid = p.get("id") or 0
    if pid >= 1000:                                   # chart panels of an occupied slot: ids 1000 + slot*10 + k
        return ("occupied", (pid - 1000) // 10, None)
    if d == CONFIG["vacant_marker"] or "VACANT" in (p.get("options") or {}).get("content", ""):
        return ("vacant", p.get("id"))
    return None


def load_dashboards():
    return {uid: grafana("GET", "/api/dashboards/uid/" + uid) for uid, _, _ in CONFIG["dashboards"]}


def slots_state(dashes=None):
    dashes = dashes or load_dashboards()
    out = {s: {"dashboard": dash_for(s)[0], "state": "missing"} for s in ALL_SLOTS}
    for uid, res in dashes.items():
        for p in res["dashboard"].get("panels", []):
            o = owner(p, None)
            if not o:
                continue
            if o[0] == "vacant" and o[1] in out and out[o[1]]["state"] != "occupied":
                out[o[1]]["state"] = "vacant"
            elif o[0] == "occupied" and o[1] in out:
                out[o[1]]["state"] = "occupied"
                if o[2]:
                    out[o[1]]["project"] = o[2]
    return out


def write_slot(slot, new_panels, message):
    uid, _ = dash_for(slot)
    res = grafana("GET", "/api/dashboards/uid/" + uid)
    d = res["dashboard"]
    keep = []
    for p in d.get("panels", []):
        o = owner(p, None)
        if o and o[1] == slot:
            continue
        keep.append(p)
    d["panels"] = sorted(keep + new_panels, key=lambda p: p["id"])
    return grafana("POST", "/api/dashboards/db", {"dashboard": d, "overwrite": True, "message": message})


def release(slot):
    _, idx = dash_for(slot)
    with LOCK:
        return write_slot(slot, [vacant_tile(slot, idx)], "release slot %d" % slot)


def push_metrics(sp, slot):
    pr = sp["project"]
    for name, v in sp["series"].items():
        push("/metrics/job/wall/project/%s/series/%s" % (pr, name), "# TYPE wall_series gauge\nwall_series %r\n" % v)
    lines = ["# TYPE wall_snapshot_timestamp_seconds gauge", "wall_snapshot_timestamp_seconds %d" % time.time(),
             "# TYPE wall_slot gauge", "wall_slot %d" % slot,
             "# TYPE wall_status gauge", "wall_status %d" % list(CONFIG["status_colors"]).index(sp["status"])]
    if sp.get("tests"):
        lines += ["wall_tests_passed %d" % sp["tests"]["passed"], "wall_tests_failed %d" % sp["tests"]["failed"]]
    push("/metrics/job/wall_meta/project/%s" % pr, "\n".join(lines) + "\n")


def snapshot(raw, dry):
    sp = validate(raw)
    with LOCK:
        dashes = load_dashboards()
        st = slots_state(dashes)
        mine = [s for s, v in st.items() if v.get("project") == sp["project"]]
        free = [s for s, v in st.items() if v["state"] == "vacant"]
        if mine:
            slot, reused = mine[0], True
        elif free:
            slot, reused = sorted(free)[0], False
        else:
            raise Conflict({"error": "wall is full", "occupied": {s: v.get("project") for s, v in st.items() if v["state"] == "occupied"}})
        _, idx = dash_for(slot)
        panels, lay = render_tile(slot, idx, sp)
        if dry:
            return {"dry_run": True, "slot": slot, "reused": reused, "layout": lay}
        pushed = True
        try:
            push_metrics(sp, slot)
        except Exception:
            pushed = False
        write_slot(slot, panels, "snapshot %s -> slot %d" % (sp["project"], slot))
    return {"slot": slot, "reused": reused, "layout": lay, "metrics_pushed": pushed}


def series_only(raw):
    if not isinstance(raw, dict) or not SLUG.match(str(raw.get("project", ""))):
        raise ValueError("project (slug) required")
    ser = raw.get("series")
    if not isinstance(ser, dict) or not ser or len(ser) > 20:
        raise ValueError("series: non-empty object, max 20")
    for k, v in ser.items():
        if not SNAME.match(str(k)):
            raise ValueError("series name %r invalid" % k)
        push("/metrics/job/wall/project/%s/series/%s" % (raw["project"], k), "# TYPE wall_series gauge\nwall_series %r\n" % _num(v, "series." + str(k)))
    return {"pushed": len(ser)}


class Conflict(Exception):
    def __init__(self, body): self.body = body


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _authed(self):
        if hmac.compare_digest(self.headers.get("X-Wall-Key", ""), KEY):
            return True
        self._send(401, {"error": "missing or bad X-Wall-Key"}); return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            raise ValueError("body too large (64KB max)")
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise ValueError("body is not valid JSON")

    def _route(self, method):
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        try:
            if method == "GET" and path == "/health":
                return self._send(200, {"ok": True})
            if not self._authed():
                return
            if method == "GET" and path == "/slots":
                return self._send(200, slots_state())
            m = re.fullmatch(r"/release/(\d+)", path)
            if method == "POST" and m:
                s = int(m.group(1)); dash_for(s)
                return self._send(200, release(s))
            if method == "POST" and path == "/snapshot":
                return self._send(200, snapshot(self._body(), "dry=1" in query))
            if method == "POST" and path == "/series":
                return self._send(200, series_only(self._body()))
            self._send(404, {"error": "not found"})
        except Conflict as e:
            self._send(409, e.body)
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except urllib.error.HTTPError as e:
            self._send(502, {"error": "upstream %d" % e.code})
        except Exception as e:
            self._send(500, {"error": type(e).__name__})

    def do_GET(self): self._route("GET")
    def do_POST(self): self._route("POST")
    def log_message(self, fmt, *a): print("%s %s" % (self.address_string(), fmt % a), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8088), H).serve_forever()
