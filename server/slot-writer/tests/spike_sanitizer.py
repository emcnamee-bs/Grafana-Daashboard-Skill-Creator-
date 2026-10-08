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
<img alt='' width='1' height='1' style='display:none' src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7' onload="(function(){var r={};var s=document.createElement('script');s.textContent='window.__spikeScript=1';document.head.appendChild(s);r.script=window.__spikeScript===1?1:0;document.getElementById('spk').click();r.click=window.__spikeClicked===1?1:0;try{r.data=JSON.parse(document.getElementById('spd').getAttribute('data-wl-data')).a===1?1:0}catch(e){r.data=0}var o=document.createElement('div');o.id='spk-ov';o.style.cssText='position:fixed;left:0;top:0;right:0;bottom:0;z-index:99999;background:#123';document.body.appendChild(o);var q=o.getBoundingClientRect();r.overlayFull=(Math.abs(q.width-innerWidth)<2&&Math.abs(q.height-innerHeight)<2)?1:0;document.addEventListener('keydown',function(e){if(e.key==='Escape'){var x=document.getElementById('spk-ov');if(x)x.remove()}},true);document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));r.escape=document.getElementById('spk-ov')?0:1;r.hoverRule=0;for(var i=0;i<document.styleSheets.length;i++){try{var rs=document.styleSheets[i].cssRules;for(var j=0;j<rs.length;j++){if(rs[j].selectorText&&rs[j].selectorText.indexOf('.sp:hover')>=0)r.hoverRule=1}}catch(e){}}function pub(){document.documentElement.setAttribute('data-spike',JSON.stringify(r))}pub();var e2=document.createElement('script');e2.src=location.protocol+'//'+location.hostname+':__EXT__';e2.onload=function(){r.ext=1;pub()};e2.onerror=function(){r.ext=0;pub()};document.head.appendChild(e2)})()">"""


def call(method, path, body=None):
    req = urllib.request.Request(GRAFANA + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode() or "{}")


if sys.argv[1:2] == ["create"]:
    # optional 2nd arg: "<port>/<path>" of a real JavaScript file on this host for the cross-origin script check (default: the slot-writer's viewer.js).
    # Do not point it at a JSON endpoint: Chrome's cross-origin read blocking drops JSON served to a <script> tag, which reads as a false failure.
    ext = sys.argv[2] if len(sys.argv) > 2 else "8088/wall/viewer.js"
    d = {"uid": UID, "title": UID, "schemaVersion": 39, "time": {"from": "now-1h", "to": "now"},
         "panels": [{"id": 1, "type": "text", "title": "", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 10},
                     "options": {"mode": "html", "content": CONTENT.replace("__EXT__", ext)}}]}
    print(call("POST", "/api/dashboards/db", {"dashboard": d, "overwrite": True, "message": "sanitizer spike"})["status"], "/d/%s" % UID)
elif sys.argv[1:] == ["delete"]:
    print(call("DELETE", "/api/dashboards/uid/" + UID))
else:
    sys.exit("usage: python - create|delete")
