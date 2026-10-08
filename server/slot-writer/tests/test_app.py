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
