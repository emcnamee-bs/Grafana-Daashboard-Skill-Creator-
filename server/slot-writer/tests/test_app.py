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


class ServerCase(unittest.TestCase):
    """Real HTTP server on an ephemeral port; Grafana is pointed at a closed port so anything past request parsing fails fast."""
    @classmethod
    def setUpClass(cls):
        app.CONFIG["grafana_url"] = "http://127.0.0.1:9"
        app.H.log_message = lambda self, fmt, *a: None        # keep test output free of access-log lines
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
            try:
                return e.code, dict(e.headers), e.read()
            finally:
                e.close()


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
        self.assertIsNone(sp["stats"][0]["explain"])
        self.assertIsNone(sp["stats"][0]["detail"])
        ch = sp["charts"][0]
        self.assertIsNone(ch["explain"])
        self.assertIsNone(ch["history"])
        self.assertIsNone(ch["breakdown"])
        self.assertEqual(ch["history_label"], "")

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


class MaximalTile(unittest.TestCase):
    """Review Focus 5: a tile at the validated maximum must stay inside the body and payload limits (not just a monkeypatched cap)."""
    def maximal_spec(self):
        items = [{"name": ("n%02d" % i) + "y" * 20, "state": "up", "what": "w" * 120} for i in range(12)]
        detail = {"why": "w" * 240, "items": items}
        pts = [[1790000000 + i * 60, 123456.789 + i] for i in range(200)]
        hist = [[1790000000 + i * 60, 123456.789 + i] for i in range(400)]
        kpis = [{"label": "L" * 12, "value": "V" * 10, "state": "ok", "explain": "e" * 200}] * 2
        worst = [{"label": "l" * 24, "value": "v" * 12}] * 5
        chart = lambda i: {"title": "Chart %d" % i, "subtitle": "s" * 26, "span_label": "12h", "points": pts, "history": hist, "history_label": "7d",
                           "explain": "e" * 200, "kpis": kpis, "breakdown": {"ok_pct": 50, "err_pct": 50, "total": 123456789, "worst": worst}}
        return {"project": "max", "summary": "s" * 240, "task": "t" * 90,
                "stats": [{"label": "L" * 16, "value": "V" * 12, "trend": "up", "explain": "e" * 200, "detail": detail}] * 6,
                "health": [{"name": "H" * 18, "state": "up", "explain": "e" * 200, "detail": detail}] * 8,
                "charts": [chart(i) for i in range(4)]}

    def test_validated_maximum_fits_the_request_and_payload_limits(self):
        spec = self.maximal_spec()
        self.assertLess(len(json.dumps(spec)), app.MAX_BODY, "a maximal spec must be accepted by the request limit")
        page = app.tile_v2_html(app.validate(spec))              # raises "tile detail too large" past MAX_PAYLOAD
        size = len(html.unescape(re.search(r"data-wl-data='([^']*)'", page).group(1)))
        self.assertLess(size, app.MAX_PAYLOAD, "embedded payload is %d bytes" % size)


class ExplorableOtherTemplates(unittest.TestCase):
    """Every tile the skill can publish is explorable, not only the chart-row template."""
    def spec(self, **kw):
        d = {"project": "demo", "name": "Demo", "summary": "A demo tile",
             "stats": [{"label": "Open PRs", "value": "3", "explain": "Pull requests open now."}],
             "health": [{"name": "API", "state": "up", "explain": "health endpoint answers"}]}
        d.update(kw)
        return app.validate(d)

    def test_top_bar_only_tile_is_explorable(self):
        panels, _ = app.render_tile(1, 0, self.spec())          # no charts: the top bar fills the square
        content = panels[0]["options"]["content"]
        for t in ("square", "stat:0", "health:0"):
            self.assertIn("data-wl='%s'" % t, content)
            self.assertIn("wallOpen(this,'%s')" % t, content)
        self.assertIn(".wl-t:hover", content)
        self.assertIn(":8088/wall/viewer.js", content)
        p = payload_of(content)
        self.assertEqual(p["name"], "Demo")
        self.assertEqual(p["charts"], [])

    def test_legacy_series_chart_tile_keeps_a_valid_payload(self):
        panels, _ = app.render_tile(1, 0, self.spec(charts=[{"title": "Earnings", "series": "earnings", "kind": "line"}]))
        content = panels[0]["options"]["content"]
        self.assertEqual(payload_of(content)["charts"], [])     # live Grafana panels carry no inline points: nothing for the viewer to draw
        self.assertIn("data-wl='square'", content)


class WrapperHold(unittest.TestCase):
    def test_reload_is_deferred_while_an_overlay_is_open(self):
        page = app.wall_page("wall-top", 95)
        self.assertIn("wallHold", page)                        # listens for the viewer's hold message
        self.assertIn("e.source!==cur.contentWindow", page)    # ...but only from its own iframe
        self.assertIn("pend=true", page)                       # a version change is remembered, not applied
        self.assertIn("if(pend&&!hold)", page)                 # ...and applied once the hold is gone
        self.assertIn("600000", page)                          # a crashed viewer can never freeze updates for more than 10 minutes
        self.assertIn("/wall/wall-top/version", page)          # existing behaviour kept


class ViewerRoute(ServerCase):
    def test_viewer_js_is_served_without_a_key(self):
        code, headers, body = self.request("GET", "/wall/viewer.js")
        self.assertEqual(code, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/javascript"))
        self.assertTrue(body.startswith(b"/* Wall full-screen viewer"))
