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
import base64, hmac, html, json, math, os, re, textwrap, threading, time, urllib.parse, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- CONFIG: tile look + grid constants live here so they are easy to change ----
CONFIG = {
    "grafana_url": os.environ.get("GRAFANA_URL", "http://grafana:3000"),
    "pushgateway_url": os.environ.get("PUSHGATEWAY_URL", "http://pushgateway:9091"),
    "prometheus_url": os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
    "datasource_uid": "prometheus",
    "dashboards": [("wall-top", 1, 6), ("wall-middle", 7, 12), ("wall-bottom", 13, 18)],  # (uid, first, last)
    "cols": 3, "panel_w": 8, "panel_h": 13,   # grid units per slot (24 wide / 3 cols)
    "header_h": 4,                            # units used by the fixed top bar inside the info card (name box + branch/activity chips)
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
    "viewer_port": 8088,                      # slot-writer's own port: the tile bootstrap loads /wall/viewer.js from it
}
# ---------------------------------------------------------------------------------

TOKEN = os.environ["GRAFANA_TOKEN"]
KEY = os.environ["WALL_KEY"]
LOCK = threading.Lock()
MAX_BODY = 262144          # request body cap: a tile may now carry chart history and detail lists
MAX_PAYLOAD = 120000       # cap on the JSON embedded in one tile (see tile_payload)
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
    out["summary"] = _s(spec.get("summary"), "summary", 240)
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
        out["health"].append({"name": _s(h.get("name"), "health.name", 18, True), "state": st,
                              "explain": _s(h.get("explain"), "health.explain", 200), "detail": _detail(h.get("detail"), "health.detail")})
    sl = spec.get("stats") or []
    if len(sl) > 6:
        raise ValueError("stats: max 6 entries")
    out["stats"] = [{"label": _s(x.get("label"), "stats.label", 16, True), "value": _s(x.get("value"), "stats.value", 12, True),
                     "trend": _s(x.get("trend"), "stats.trend", 5) if _s(x.get("trend"), "stats.trend", 5) in ("up", "down", "flat") else None,
                     "explain": _s(x.get("explain"), "stats.explain", 200), "detail": _detail(x.get("detail"), "stats.detail")}
                    for x in sl]
    cl = spec.get("charts") or []
    if len(cl) > 4:
        raise ValueError("charts: max 4 entries")
    out["charts"] = []
    for c in cl:
        pts = c.get("points")
        if pts is not None:
            # points chart (template v2): data travels with the spec as [[t, v], ...] or [{"t":..,"v":..}, ...]
            norm = _points(pts, "charts.points", 200)
            kind = _s(c.get("kind"), "charts.kind", 6) or "line"
            if kind not in ("line", "bar"):
                raise ValueError("points charts: kind in line|bar")
            kp = c.get("kpis") or []
            if len(kp) > 2:
                raise ValueError("charts.kpis: max 2 per chart")
            kpis = []
            for k in kp:
                stt = _s(k.get("state"), "charts.kpis.state", 5)
                if stt and stt not in ("ok", "warn", "bad"):
                    raise ValueError("charts.kpis.state must be ok|warn|bad")
                kpis.append({"label": _s(k.get("label"), "charts.kpis.label", 12, True), "value": _s(k.get("value"), "charts.kpis.value", 10, True), "state": stt,
                             "explain": _s(k.get("explain"), "charts.kpis.explain", 200)})
            title = _s(c.get("title"), "charts.title", 22, True)
            y_max = _num(c["y_max"], "charts.y_max") if c.get("y_max") is not None else None
            if y_max is not None and not (0 < y_max <= 1e6):
                raise ValueError("charts.y_max must be between 0 and 1000000")
            out["charts"].append({"title": title, "points": norm, "kind": kind, "kpis": kpis, "y_max": y_max, "span_label": _s(c.get("span_label"), "charts.span_label", 8) or "",
                                  "subtitle": _s(c.get("subtitle"), "charts.subtitle", 26) or "", "series": None, "share": 1.0,
                                  "explain": _s(c.get("explain"), "charts.explain", 200),
                                  "history": _points(c["history"], "charts.history", 400) if c.get("history") is not None else None,
                                  "history_label": _s(c.get("history_label"), "charts.history_label", 8) or "",
                                  "breakdown": _breakdown(c.get("breakdown"), "charts.breakdown")})
            continue
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
                              "span": span, "unit": unit, "share": min(max(share, 0.25), 4.0), "points": None,
                              "explain": None, "history": None, "history_label": "", "breakdown": None})
    if out["charts"] and len({ch.get("points") is not None for ch in out["charts"]}) > 1:
        raise ValueError("charts: do not mix points charts (inline data) with series charts (live Prometheus)")
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
    # optional: ask for a specific vacant slot (a project that already owns a slot keeps it)
    want = spec.get("slot")
    out["slot"] = None
    if want is not None:
        w = int(_num(want, "slot"))
        if w not in ALL_SLOTS:
            raise ValueError("slot must be 1-18")
        out["slot"] = w
    # optional: rotating showcase tile (one item at a time, animated, loops forever) instead of the status template
    sc = spec.get("showcase")
    out["showcase"] = None
    if sc:
        items = sc.get("items") or []
        if not isinstance(items, list) or not (1 <= len(items) <= 100):
            raise ValueError("showcase.items: 1-100 entries")
        every = _num(sc.get("interval", 10), "showcase.interval")
        if not (3 <= every <= 60):
            raise ValueError("showcase.interval must be 3-60 seconds")
        out["showcase"] = {"interval": every, "items": [
            {"group": _s(i.get("group"), "showcase.items.group", 20), "title": _s(i.get("title"), "showcase.items.title", 34, True),
             "text": _s(i.get("text"), "showcase.items.text", 140, True)} for i in items]}
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


def info_html(sp, blocks, roomy=False, framed=False):
    """The info card. Every 'thing' (name+status, branch, activity, task, tests, each health dot, each stat) sits in its own bordered box.
    Grafana's sanitizer drops several CSS properties (flex:1, zoom, and apparently white-space/overflow), so: sizes are explicit,
    text is truncated here instead of with CSS, and the card fits its panel exactly (no negative-margin tricks: at a fractional display
    scale they overflow by a sub-pixel and the panel grows scrollbars)."""
    c = CONFIG
    sc = c["status_colors"][sp["status"]]
    label = esc((sp["status_label"] or sp["status"]).upper())
    ac = c["activity_colors"][sp["activity"]["state"]]
    alab = esc(sp["activity"]["state"] + (" \u00b7 " + sp["activity"]["label"] if sp["activity"]["label"] else ""))
    k = 1.25 if roomy else 1.0
    S = lambda n: int(round(n * k))
    line = "1px solid #1f5fae"
    def box(inner, extra=""):
        return ("<div style='box-sizing:border-box;border:%s;border-radius:8px;background:rgba(31,95,174,.10);padding:%dpx %dpx;%s'>%s</div>"
                % (line, S(6), S(10), extra, inner))
    chip = "display:inline-block;padding:3px 10px;border-radius:12px;background:rgba(77,163,255,.10);border:1px solid rgba(77,163,255,.35);"
    # framed = a chart panel sits below, so this panel keeps Grafana's own chrome (same edges as the chart panels) and the card adds none
    outer = "border:0;" if framed else "border:%s;border-radius:%s;box-shadow:%s;" % (c["border"], c["radius"], c["glow"])
    parts = ["<div style='box-sizing:border-box;height:100%%;padding:12px 14px;%sbackground:%s;"
             "display:flex;flex-direction:column;justify-content:space-between;font-family:Inter,sans-serif;color:%s;overflow:hidden'>"
             % (outer, c["card_bg"], c["text"])]
    name = esc(sp["name"][:22])
    parts.append("<div>" + box(
        "<div style='display:flex;align-items:center;justify-content:space-between;gap:10px'>"
        "<div style='font-size:%dpx;font-weight:700;letter-spacing:.02em'>%s</div>"
        "<div style='padding:4px 14px;border-radius:14px;background:%s;color:#fff;font-size:%dpx;font-weight:700;letter-spacing:.12em'>%s</div></div>"
        % (S(26), name, sc, S(14), label)) +
        "<div style='margin-top:6px;font-size:%dpx;color:%s;display:flex;gap:8px'><span style='%s'>&#9095; %s</span>"
        "<span style='%s'><span style='color:%s'>&#9679;</span> %s</span></div></div>"
        % (S(14), c["muted"], chip, esc(sp["branch"][:24]), chip, ac, alab))
    body = []
    if "task" in blocks:
        t = sp["task"]; lim = 40 if roomy else 56
        if len(t) > lim:
            t = t[:lim - 1].rstrip() + "\u2026"
        body.append(box("<span style='color:%s;letter-spacing:.12em;font-size:%dpx'>NOW</span>&nbsp; <span style='font-size:%dpx'>%s</span>"
                        % (c["muted"], S(12), S(15), esc(t))))
    if "tests" in blocks:
        t = sp["tests"]; tot = max(t["passed"] + t["failed"] + t["skipped"], 1)
        pw, fw = 100.0 * t["passed"] / tot, 100.0 * t["failed"] / tot
        body.append(box("<div style='font-size:%dpx;color:%s;display:flex;justify-content:space-between'><span style='letter-spacing:.12em;font-size:%dpx'>%s</span>"
                        "<span style='color:%s'>%d passed%s</span></div><div style='height:%dpx;border-radius:4px;background:#1a2640;margin-top:4px;display:flex;overflow:hidden'>"
                        "<div style='width:%.1f%%;background:#3fb950'></div><div style='width:%.1f%%;background:#f85149'></div></div>"
                        % (S(13), c["muted"], S(12), esc((t["label"] or "TESTS").upper()), c["text"], t["passed"],
                           (" &middot; <span style='color:#f85149'>%d failed</span>" % t["failed"]) if t["failed"] else "", S(7), pw, fw)))
    if "health" in blocks:
        pills = "".join("<span style='display:inline-block;margin:0 6px 6px 0;padding:%dpx %dpx;border:%s;border-radius:8px;background:rgba(31,95,174,.10);font-size:%dpx'>"
                        "<span style='color:%s'>&#9679;</span> %s</span>" % (S(3), S(9), line, S(14), c["health_colors"][h["state"]], esc(h["name"])) for h in sp["health"])
        body.append("<div>%s</div>" % pills)
    if "stats" in blocks:
        n = len(sp["stats"]); cells = []
        for s in sp["stats"]:
            arrow = {"up": " <span style='color:#3fb950'>&#9650;</span>", "down": " <span style='color:#f85149'>&#9660;</span>", "flat": ""}.get(s["trend"], "")
            cells.append(box("<div style='font-size:%dpx;font-weight:700'>%s%s</div><div style='font-size:%dpx;letter-spacing:.1em;color:%s'>%s</div>"
                             % (S(24), esc(s["value"]), arrow, S(11), c["muted"], esc(s["label"].upper())),
                             "width:calc((100%% - %dpx) / %d);" % (8 * (n - 1), n)))
        body.append("<div style='display:flex;gap:8px'>%s</div>" % "".join(cells))
    style = "margin:auto 0;display:flex;flex-direction:column;gap:%dpx;" % (14 if roomy else 8)
    if body:
        parts.append("<div style='%s'>%s</div>" % (style, "".join(body)))
    parts.append("</div>")
    return "".join(parts)


TILE_PX = 443          # CSS px of usable card height inside a 13-unit slot (measured on the wall: 469px panel minus padding and border)
CARD_INNER_PX = 520    # usable CSS px width inside the card at the wall's 95% frame


def nice_max(v):
    for n in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 100000, 1000000):
        if v <= n:
            return n
    return int(math.ceil(v))


def spark_img(points, kind, w, h, y_max=None):
    """Chart as a base64 SVG <img> (Grafana's text panel strips inline <svg> and utf8 data URIs but keeps base64 image data URIs).
    Returns (data_uri, y_axis_max). y_max fixes the top of the axis; data above it makes the axis grow to a clean higher value so a bar is never clipped."""
    vals = [p[1] for p in points]
    if not vals:
        return None, (y_max or 1)
    top = max(vals)
    ymax = nice_max(top * 1.05) if y_max is None else (y_max if top <= y_max else nice_max(top))
    n = len(vals); pad = 4
    X = lambda i: pad + (w - 2 * pad) * (i / (n - 1 if n > 1 else 1))
    Y = lambda v: h - pad - (h - 2 * pad) * (min(v, ymax) / float(ymax))
    grid = "".join("<line x1='0' x2='%d' y1='%.1f' y2='%.1f' stroke='#1d3050' stroke-width='1'/>" % (w, Y(ymax * f), Y(ymax * f)) for f in (0.5, 1.0))
    if kind == "bar":
        slot_w = (w - 2 * pad) / float(n)
        bw = max(slot_w * 0.7, 1.5)
        body = "".join("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='#4da3ff'/>" % (pad + slot_w * (i + 0.5) - bw / 2, Y(v), bw, max(h - pad - Y(v), 0)) for i, v in enumerate(vals) if v > 0)
        body += "<line x1='0' x2='%d' y1='%.1f' y2='%.1f' stroke='#2a4a7a' stroke-width='1'/>" % (w, h - pad, h - pad)
    else:
        line = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(vals))
        area = "%.1f,%.1f %s %.1f,%.1f" % (X(0), h - pad, line, X(n - 1), h - pad)
        body = ("<defs><linearGradient id='a' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#4da3ff' stop-opacity='.35'/>"
                "<stop offset='1' stop-color='#4da3ff' stop-opacity='0'/></linearGradient></defs>"
                "<polygon points='%s' fill='url(#a)'/><polyline points='%s' fill='none' stroke='#4da3ff' stroke-width='2' stroke-linejoin='round'/>"
                "<circle cx='%.1f' cy='%.1f' r='3' fill='#fff'/>") % (area, line, X(n - 1), Y(vals[-1]))
    svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 %d %d' width='%d' height='%d'>%s%s</svg>" % (w, h, w, h, grid, body)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(), ymax

def tile_v2_html(sp):
    """Fixed template: a top bar (name, status, git branch, activity, quick stats, key-part health, current task) over a landscape row of
    2-3 equal charts, each with its own KPI chips. Every item has its own border. All sizing is explicit because Grafana's sanitizer
    drops flex:1 / zoom / overflow-style tricks."""
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
    for s in sp["stats"]:
        arrow = {"up": " <span style='color:#3fb950'>&#9650;</span>", "down": " <span style='color:#f85149'>&#9660;</span>"}.get(s["trend"], "")
        chips.append("<span style='%s'><b style='font-size:16px'>%s</b>%s <span style='font-size:11px;letter-spacing:.08em;color:%s'>%s</span></span>"
                     % (chip, esc(s["value"]), arrow, muted, esc(s["label"].upper())))
    pills = "".join("<span style='display:inline-block;margin:0 6px 6px 0;padding:3px 9px;%sfont-size:14px'><span style='color:%s'>&#9679;</span> %s</span>"
                    % (box, c["health_colors"][h["state"]], esc(h["name"])) for h in sp["health"])
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
           "<div style='%spadding:6px 12px;display:flex;align-items:center;justify-content:space-between'>"
           "<div style='font-size:26px;font-weight:700;letter-spacing:.02em'>%s</div>"
           "<div style='padding:4px 14px;border-radius:14px;background:%s;color:#fff;font-size:14px;font-weight:700;letter-spacing:.12em'>%s</div></div>"
           "<div style='margin-top:8px'>%s</div><div>%s</div>%s</div>"
           % (top_pct, box, esc(sp["name"][:22]), sc, label, "".join(chips), pills, task))

    # ---- charts row
    chart_px = TILE_PX * chart_pct / 100.0
    box_w = (CARD_INNER_PX - 8 * (n - 1)) / float(n)
    state_col = {"ok": "#3fb950", "warn": "#d29922", "bad": "#f85149"}
    cols = []
    for ch in charts:
        has_k = bool(ch["kpis"])
        img_h = max(int(chart_px - 16 - 2 - 34 - (40 if has_k else 0) - 18 - 14), 50)
        img_w = max(int(box_w - 18 - 20), 60)          # 20px left for the y-axis labels
        img, ymax = spark_img(ch["points"], ch["kind"], img_w, img_h, ch.get("y_max"))
        vals = [p[1] for p in ch["points"]]
        head = ("<div style='font-size:13px;font-weight:700;letter-spacing:.06em'>%s</div>"
                "<div style='font-size:10px;color:%s;min-height:12px'>%s</div>" % (esc(ch["title"].upper()), muted, esc(ch["subtitle"])))
        kp = ""
        if has_k:
            kp = "<div style='display:flex;gap:6px;margin:4px 0'>" + "".join(
                "<div style='%swidth:calc((100%% - 6px) / 2);padding:2px 7px'><div style='font-size:10px;letter-spacing:.1em;color:%s'>%s</div>"
                "<div style='font-size:16px;font-weight:700;color:%s'>%s</div></div>"
                % (box, muted, esc(k["label"].upper()), state_col.get(k["state"], c["text"]), esc(k["value"])) for k in ch["kpis"]) + "</div>"
        axis = ("<div style='display:flex;gap:4px'><div style='width:16px;height:%dpx;display:flex;flex-direction:column;justify-content:space-between;text-align:right;font-size:10px;color:%s'>"
                "<span>%g</span><span>%g</span><span>0</span></div><img src='%s' style='display:block;width:calc(100%% - 20px);height:%dpx'></div>" % (img_h, muted, ymax, ymax / 2.0, img, img_h)) if img else None
        body = axis if img else \
               ("<div style='height:%dpx;color:%s;font-size:13px;text-align:center;padding-top:%dpx'>no data</div>" % (img_h, muted, img_h // 2 - 8))
        foot = ("<div style='display:flex;justify-content:space-between;font-size:10px;color:%s;margin-top:2px'><span>-%s</span><span>max %s</span><span>now</span></div>"
                % (muted, esc(ch["span_label"] or ""), ("%g" % round(max(vals), 2)) if vals else "-"))
        cols.append("<div style='%swidth:calc((100%% - %dpx) / %d);height:100%%;padding:8px'>%s%s%s%s</div>" % (box, 8 * (n - 1), n, head, kp, body, foot))
    row = "<div style='display:flex;gap:8px;height:%d%%;margin-top:2%%'>%s</div>" % (chart_pct, "".join(cols))

    return ("<div style='box-sizing:border-box;height:100%%;padding:12px 14px;border:%s;border-radius:%s;box-shadow:%s;background:%s;"
            "font-family:Inter,sans-serif;color:%s'>%s%s</div>" % (c["border"], c["radius"], c["glow"], c["card_bg"], c["text"], top, row))

def first_sample_age(project, series):
    """Seconds since this series' first Prometheus sample, or None. Tiered subqueries (fine resolution first) because a fixed 5y range
    makes Grafana's query step days wide, so young data would fall between steps and the chart would say 'No data'."""
    sel = 'wall_series{project="%s",series="%s"}' % (project, series)       # both validated: no quotes possible
    for rng_s, rng, step_s, step in ((3600, "1h", 15, "15s"), (172800, "2d", 60, "1m"), (7776000, "90d", 900, "15m"), (157680000, "5y", 21600, "6h")):
        try:
            q = urllib.parse.urlencode({"query": "min_over_time(timestamp(%s)[%s:%s])" % (sel, rng, step)})
            with urllib.request.urlopen(CONFIG["prometheus_url"] + "/api/v1/query?" + q, timeout=8) as r:
                res = json.loads(r.read())["data"]["result"]
        except Exception:
            return None
        if res:
            age = max(time.time() - float(res[0]["value"][1]), 0)
            if age < rng_s - 2 * step_s:          # the window was not saturated, so this really is the first sample
                return age
    return None


def span_text(seconds):
    if seconds < 2 * 3600:
        return "%dm" % max(15, int(seconds // 60) + 5)
    if seconds < 3 * 86400:
        return "%dh" % (int(seconds // 3600) + 2)
    return "%dd" % min(int(seconds // 86400) + 1, 1825)


SPAN_SECONDS = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000, "90d": 7776000}


def chart_panel(ch, sp, pid, gp, tag):
    c = CONFIG
    expr = 'wall_series{project="%s",series="%s"}' % (sp["project"], ch["series"])   # both validated: no quotes possible
    if ch["span"] == "all":
        age = first_sample_age(sp["project"], ch["series"])
        span, max_pts = span_text(age if age is not None else 3600), 600
    else:
        span = c["span_map"][ch["span"]]
        max_pts = min(10000, max(300, SPAN_SECONDS[ch["span"]] // 30))        # ~30s step up to a week, so a few minutes of history already draws
    # no description here (it adds an info icon that eats the title); ownership comes from the panel id range instead
    base = {"id": pid, "title": ch["title"], "gridPos": gp, "transparent": False, "hideTimeOverride": True, "maxDataPoints": max_pts,
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


def showcase_svg(sc, w=520, h=360):
    """One self-contained animated SVG (CSS keyframes only, no script) that shows each item for `interval` seconds, then slides/fades to
    the next, looping forever. It travels as a base64 <img> because Grafana's text-panel sanitizer drops inline <svg>, <style> and scripts
    but keeps images. Every item owns a group whose animation-delay is its turn in the loop; all share one period so the loop never drifts."""
    items, every = sc["items"], float(sc["interval"])
    n = len(items); total = n * every
    pct = lambda t: "%.4f%%" % (t / total * 100.0)
    ein, eout = 0.7, 0.7          # entrance / exit seconds
    css = (
        ".g{opacity:0;animation:k1 %(T)gs linear infinite}"
        ".d{opacity:0;animation:k2 %(T)gs linear infinite}"
        ".u{transform-box:fill-box;transform-origin:0 50%%;transform:scaleX(0);animation:k3 %(T)gs linear infinite}"
        ".p{transform-box:fill-box;transform-origin:0 50%%;animation:kp %(I)gs linear infinite}"
        ".q{transform-box:fill-box;transform-origin:0 50%%;animation:kp %(T)gs linear infinite}"
        "@keyframes k1{0%%{opacity:0;transform:translateX(70px)}%(a)s{opacity:1;transform:translateX(0)}%(b)s{opacity:1;transform:translateX(0)}"
        "%(c)s{opacity:0;transform:translateX(-70px)}100%%{opacity:0;transform:translateX(-70px)}}"
        "@keyframes k2{0%%{opacity:0;transform:translateY(16px)}%(d)s{opacity:0;transform:translateY(16px)}%(e)s{opacity:1;transform:translateY(0)}"
        "%(b)s{opacity:1;transform:translateY(0)}%(c)s{opacity:1}100%%{opacity:1}}"
        "@keyframes k3{0%%{transform:scaleX(0)}%(d)s{transform:scaleX(0)}%(f)s{transform:scaleX(1)}%(b)s{transform:scaleX(1)}%(c)s{transform:scaleX(1)}100%%{transform:scaleX(1)}}"
        "@keyframes kp{0%%{transform:scaleX(0)}100%%{transform:scaleX(1)}}"
        "@keyframes gl{0%%,100%%{opacity:.35}50%%{opacity:.75}}"
        % {"T": total, "I": every, "a": pct(ein), "b": pct(every - eout), "c": pct(every), "d": pct(0.30), "e": pct(1.05), "f": pct(0.95)})
    parts = ["<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 %d %d' width='%d' height='%d' font-family='Inter,Segoe UI,Helvetica,Arial,sans-serif'>" % (w, h, w, h),
             "<defs><radialGradient id='r' cx='50%' cy='45%' r='70%'><stop offset='0' stop-color='#1f5fae' stop-opacity='.45'/><stop offset='1' stop-color='#1f5fae' stop-opacity='0'/></radialGradient></defs>",
             "<style>%s</style>" % css,
             "<rect x='-300' width='%d' height='%d' fill='url(#r)' style='animation:gl 6s ease-in-out infinite'/>" % (w + 600, h)]
    for i, it in enumerate(items):
        title = it["title"]
        fs = int(min(40, 480.0 / (0.6 * max(len(title), 1))))
        lines = textwrap.wrap(it["text"], 38)[:4]
        group = (it["group"] or "").upper()
        gw = len(group) * 8 + 24
        chip = ("<rect x='24' y='24' width='%d' height='24' rx='12' fill='#4da3ff' fill-opacity='.12' stroke='#4da3ff' stroke-opacity='.45'/>"
                "<text x='36' y='40' font-size='11' font-weight='700' letter-spacing='1.6' fill='#4da3ff'>%s</text>" % (gw, esc(group))) if group else ""
        tl = "".join("<tspan x='28' dy='%d'>%s</tspan>" % (0 if k == 0 else 32, esc(ln)) for k, ln in enumerate(lines))
        parts.append(
            "<g class='g' style='animation-delay:%gs'>%s"
            "<text x='%d' y='40' font-size='13' font-weight='600' letter-spacing='1' text-anchor='end' fill='#8fa6c8'>%02d / %02d</text>"
            "<text x='28' y='138' font-size='%d' font-weight='700' fill='#e8eefc'>%s</text>"
            "<rect class='u' x='28' y='156' width='96' height='4' rx='2' fill='#4da3ff' style='animation-delay:%gs'/>"
            "<text class='d' x='28' y='212' font-size='22' fill='#b9c9e6' style='animation-delay:%gs'>%s</text></g>"
            % (i * every, chip, w - 24, i + 1, n, fs, esc(title), i * every, i * every, tl))
    parts.append("<rect x='0' y='%d' width='%d' height='4' fill='#1f3a5f' fill-opacity='.6'/><rect class='p' x='0' y='%d' width='%d' height='4' fill='#4da3ff'/>"
                 "<rect class='q' x='0' y='%d' width='%d' height='2' fill='#8fa6c8' fill-opacity='.7'/></svg>" % (h - 10, w, h - 10, w, h - 4, w))
    return "".join(parts)


def tile_showcase_html(sp):
    c = CONFIG; sc = sp["showcase"]
    line = "1px solid #1f5fae"
    box = "box-sizing:border-box;border:%s;border-radius:8px;background:rgba(31,95,174,.10);" % line
    img = "data:image/svg+xml;base64," + base64.b64encode(showcase_svg(sc).encode("utf-8")).decode("ascii")
    label = esc((sp["status_label"] or ("%d ITEMS" % len(sc["items"]))).upper())
    top = ("<div style='%spadding:6px 12px;display:flex;align-items:center;justify-content:space-between'>"
           "<div style='font-size:26px;font-weight:700;letter-spacing:.02em'>%s</div>"
           "<div style='padding:4px 14px;border-radius:14px;background:%s;color:#fff;font-size:14px;font-weight:700;letter-spacing:.12em'>%s</div></div>"
           % (box, esc(sp["name"][:22]), c["status_colors"][sp["status"]], label))
    return ("<div style='box-sizing:border-box;height:100%%;padding:12px 14px;border:%s;border-radius:%s;box-shadow:%s;background:%s;"
            "font-family:Inter,sans-serif;color:%s'>%s<div style='%smargin-top:8px;padding:0;overflow:hidden'>"
            "<img src='%s' style='display:block;width:100%%;height:360px'></div></div>"
            % (c["border"], c["radius"], c["glow"], c["card_bg"], c["text"], top, box, img))


def render_tile(slot, idx, sp):
    c = CONFIG
    W, H = c["panel_w"], c["panel_h"]
    r, col = divmod(idx, c["cols"])
    ox, oy = col * W, r * H
    base_id = 1000 + slot * 10
    tag = "wall:s%02d:%s" % (slot, sp["project"])
    if sp.get("showcase"):                                                   # rotating showcase: one animated card
        return ([{"id": base_id, "type": "text", "title": "", "transparent": True, "description": tag,
                  "gridPos": {"x": ox, "y": oy, "w": W, "h": H}, "options": {"mode": "html", "content": tile_showcase_html(sp)}}],
                {"slot": slot, "template": "showcase", "items": len(sp["showcase"]["items"]), "interval_s": sp["showcase"]["interval"]})
    if sp["charts"] and all(ch.get("points") is not None for ch in sp["charts"]):     # template v2: one card, landscape chart row
        return ([{"id": base_id, "type": "text", "title": "", "transparent": True, "description": tag,
                  "gridPos": {"x": ox, "y": oy, "w": W, "h": H}, "options": {"mode": "html", "content": tile_v2_html(sp)}}],
                {"slot": slot, "template": "v2", "charts": len(sp["charts"]), "info_h": H, "chart_h": 0})
    blocks, info_h = plan(sp)
    has_charts = bool(sp["charts"])
    panels = [{"id": base_id, "type": "text", "title": "", "transparent": not has_charts, "description": tag,
               "gridPos": {"x": ox, "y": oy, "w": W, "h": info_h},
               "options": {"mode": "html", "content": info_html(sp, blocks, roomy=not has_charts, framed=has_charts)}}]
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
        elif sp.get("slot"):
            if sp["slot"] not in free:
                raise Conflict({"error": "slot %d is not vacant" % sp["slot"], "occupied": {s: v.get("project") for s, v in st.items() if v["state"] == "occupied"}})
            slot, reused = sp["slot"], False
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


WALL_QS = "kiosk&refresh=30s&theme=dark&_dash.hideTimePicker&_dash.hideVariables&_dash.hideLinks&hideLogo=true"


def wall_page(uid, width_pct):
    """Kiosk wrapper: the dashboard in a centred frame `width_pct`% wide on the same dark background, so TV overscan can't clip
    the edges (a kiosk Chrome window snaps back to full-monitor size when resized, so the margin has to live in the page).
    The page also polls the dashboard's saved version and reloads only the frame when it changes (no window restart)."""
    # On a version change the new frame loads BEHIND the old one and is swapped in a few seconds after it finishes loading, so a redraw never blinks.
    return ("<!doctype html><meta charset=utf-8><title>wall</title><style>html,body{margin:0;height:100%%;background:#111217;overflow:hidden}"
            "iframe{position:absolute;top:0;bottom:0;left:50%%;width:%d%%;height:100%%;transform:translateX(-50%%);border:0}</style><script>"
            "var U=location.protocol+'//'+location.hostname+':3000/d/%s?%s',cur=null,v=null,z=1;"
            "function load(){var f=document.createElement('iframe');f.style.zIndex=0;f.src=U;document.body.appendChild(f);"
            "f.onload=function(){setTimeout(function(){f.style.zIndex=++z;var old=cur;cur=f;if(old){setTimeout(function(){if(old.parentNode)old.parentNode.removeChild(old)},400)}},cur?3500:0)}}"
            "function tick(){fetch('/wall/%s/version',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){"
            "if(v!==null&&j.version!==v){load()}v=j.version}).catch(function(){}).then(function(){setTimeout(tick,5000)})}"
            "window.addEventListener('DOMContentLoaded',function(){load();tick()});</script>") % (width_pct, uid, WALL_QS, uid)


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
        if n > MAX_BODY:
            raise ValueError("body too large (%dKB max)" % (MAX_BODY // 1024))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            raise ValueError("body is not valid JSON")

    def _route(self, method):
        path, _, query = self.path.partition("?")
        path = path.rstrip("/") or "/"
        try:
            if method == "GET" and path in ("/health", "/api/health"):    # /api/health lets the kiosk supervisor treat this port like Grafana
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/wall/([a-z0-9-]+)(/version)?", path)       # unauthenticated: static page + a version number, nothing sensitive
            if method == "GET" and m:
                uid = m.group(1)
                if uid not in [d[0] for d in CONFIG["dashboards"]]:
                    return self._send(404, {"error": "unknown wall dashboard"})
                if m.group(2):
                    return self._send(200, {"version": grafana("GET", "/api/dashboards/uid/" + uid)["dashboard"].get("version")})
                w = re.search(r"(?:^|&)w=(\d{2,3})(?:&|$)", query)
                pct = min(max(int(w.group(1)), 50), 100) if w else 95
                b = wall_page(uid, pct).encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers()
                return self.wfile.write(b)
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
