#!/usr/bin/env python3
"""Bump a wall dashboard's version without changing anything visible. Grafana does not raise the version when identical JSON is
re-saved, so each run flips the dashboard's `description` (metadata the kiosk never shows) between empty and "version-bump test".
Used by live-check.ps1 to prove that an open full-screen view holds the wrapper page's reload. Runs inside the slot-writer
container (it holds the Grafana token, never printed):
  ssh emac@mini-mac.local 'docker exec -i slot-writer python - wall-top' < server/slot-writer/tests/bump_version.py"""
import json, os, sys, urllib.request

GRAFANA = os.environ.get("GRAFANA_URL", "http://grafana:3000")
TOKEN = os.environ["GRAFANA_TOKEN"]


def call(method, path, body=None):
    req = urllib.request.Request(GRAFANA + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode() or "{}")


uid = sys.argv[1] if len(sys.argv) > 1 else "wall-top"
if uid not in ("wall-top", "wall-middle", "wall-bottom"):
    sys.exit("only the wall dashboards can be bumped")
dash = call("GET", "/api/dashboards/uid/" + uid)["dashboard"]
dash["description"] = "" if dash.get("description") else "version-bump test"
res = call("POST", "/api/dashboards/db", {"dashboard": dash, "overwrite": True, "message": "version bump (hold test)"})
print(res["status"], "version", res["version"])
