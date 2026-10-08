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
