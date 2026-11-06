# -*- coding: utf-8 -*-
"""纯标准库单元测试：python -m unittest discover -s tests -v"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
from render import safe_json, render  # noqa: E402

PRICING = json.loads((ROOT / "config" / "pricing.json").read_text(encoding="utf-8"))


class TestPricing(unittest.TestCase):
    def test_all_configured_models_have_four_prices(self):
        for name, cfg in PRICING["models"].items():
            p = cfg.get("price") or cfg.get("offpeak")
            self.assertEqual(len(p), 4, name)
            for k in ("input_miss", "output", "cache_hit", "cache_write"):
                self.assertIn(k, p, f"{name}.{k}")
                self.assertGreaterEqual(p[k], 0)

    def test_plans_have_positive_credits(self):
        for p in PRICING["plans"]:
            self.assertGreater(p["credits"], 0)
            self.assertGreater(p["credits_base"], 0)
            self.assertLessEqual(p["credits_base"], p["credits"])

    def test_time_of_use_peak_is_double(self):
        collect.PRICING = PRICING
        for m in ("deepseek-v4.1-flash", "deepseek-v4-pro"):
            off, pk = collect.price_for(m, False), collect.price_for(m, True)
            for a, b in zip(off, pk):
                self.assertAlmostEqual(b / a, 2.0, places=3)


class TestNormalization(unittest.TestCase):
    def test_segments_basic(self):
        ru = {"prompt_tokens": 33000, "completion_tokens": 500,
              "prompt_cache_hit_tokens": 30000, "prompt_cache_miss_tokens": 3000}
        self.assertEqual(collect.segments(ru), (30000, 3000, 500, 0))

    def test_segments_fallback_from_details(self):
        ru = {"prompt_tokens": 10000, "completion_tokens": 200,
              "prompt_tokens_details": {"cached_tokens": 8000},
              "cache_creation_input_tokens": 300}
        self.assertEqual(collect.segments(ru), (8000, 2000, 200, 300))

    def test_is_peak(self):
        import datetime
        cst = collect.CST
        peak = datetime.datetime(2026, 11, 6, 10, 0, tzinfo=cst)   # Friday 10:00
        lunch = datetime.datetime(2026, 11, 6, 13, 0, tzinfo=cst)  # Friday 13:00
        sat = datetime.datetime(2026, 11, 7, 10, 0, tzinfo=cst)    # Saturday
        self.assertTrue(collect.is_peak(int(peak.timestamp() * 1000)))
        self.assertFalse(collect.is_peak(int(lunch.timestamp() * 1000)))
        self.assertFalse(collect.is_peak(int(sat.timestamp() * 1000)))


class TestLeastSquares(unittest.TestCase):
    def test_exact_linear_recovery(self):
        rows = [(0.1, 0.02, 0.003, 2 * 0.1 + 3 * 0.02 + 5 * 0.003),
                (0.5, 0.01, 0.010, 2 * 0.5 + 3 * 0.01 + 5 * 0.010),
                (0.2, 0.08, 0.001, 2 * 0.2 + 3 * 0.08 + 5 * 0.001),
                (1.0, 0.05, 0.020, 2 * 1.0 + 3 * 0.05 + 5 * 0.020)]
        co = collect.least_squares(rows)
        for got, want in zip(co, (2, 3, 5)):
            self.assertAlmostEqual(got, want, places=6)


class TestBuild(unittest.TestCase):
    def setUp(self):
        collect.PRICING = PRICING
        self.sid = "s-1"
        self.req = "a" * 32
        self.calls = [
            {"sid": self.sid, "reqid": self.req, "ts": 1793930000000, "model": "minimax-m3.1-flash",
             "display": "MiniMax-M3.1-Flash", "hit": 10000, "miss": 2000, "out": 500,
             "write": 0, "credit": 1.0, "kind": 0, "is_peak": False},
            {"sid": self.sid, "reqid": self.req, "ts": 1793930060000, "model": "minimax-m3.1-flash",
             "display": "MiniMax-M3.1-Flash", "hit": 20000, "miss": 3000, "out": 700,
             "write": 0, "credit": 2.0, "kind": 0, "is_peak": False},
        ]
        self.db_sessions = {self.sid: {"title": "测试会话", "cwd": "/tmp", "created_at": 0, "model": ""}}

    def test_official_bill_takes_priority_and_is_allocated(self):
        bills = {self.sid: {self.req: 9.0}}
        data = collect.build(PRICING, self.calls, bills, self.db_sessions, False, {})
        self.assertEqual(data["requests"][0][7], 9.0)      # 官方账单
        self.assertEqual(data["requests"][0][10], 1)        # credit_src = bill
        self.assertAlmostEqual(sum(c[11] for c in data["calls"]), 9.0, places=5)
        self.assertAlmostEqual(sum(r[7] for r in data["requests"]), 9.0, places=5)

    def test_fallback_to_log_credit(self):
        data = collect.build(PRICING, self.calls, {}, self.db_sessions, False, {})
        self.assertEqual(data["requests"][0][7], 3.0)
        self.assertEqual(data["requests"][0][10], 0)

    def test_api_cost_uses_four_segments(self):
        data = collect.build(PRICING, self.calls, {}, self.db_sessions, False, {})
        p = PRICING["models"]["minimax-m3.1-flash"]["price"]
        want = ((2000 + 3000) * p["input_miss"] + (500 + 700) * p["output"]
                + (10000 + 20000) * p["cache_hit"]) / 1e6
        self.assertAlmostEqual(data["meta"]["total_api_cost"], round(want, 8), places=5)

    def test_schema_lengths(self):
        data = collect.build(PRICING, self.calls, {}, self.db_sessions, False, {})
        self.assertEqual(len(data["calls"][0]), 12)
        self.assertEqual(len(data["requests"][0]), 12)
        self.assertEqual(len(data["models"][0]), 9)
        self.assertEqual(data["meta"]["n_calls"], 2)


class TestRender(unittest.TestCase):
    def test_safe_json_escapes_script_close(self):
        s = safe_json({"x": "</script><img src=x onerror=alert(1)>"})
        self.assertNotIn("</script>", s)
        self.assertIn("\\u003c/script\\u003e", s)
        self.assertEqual(json.loads(s)["x"], "</script><img src=x onerror=alert(1)>")

    def test_render_produces_single_file(self):
        collect.PRICING = PRICING
        calls = [{"sid": "s", "reqid": "b" * 32, "ts": 1793930000000, "model": "glm-5.3-flash",
                  "display": "GLM-5.3-Flash", "hit": 1000, "miss": 100, "out": 50, "write": 0,
                  "credit": 0.1, "kind": 0, "is_peak": False}]
        data = collect.build(PRICING, calls, {}, {"s": {"title": "t", "cwd": "", "created_at": 0}}, False, {})
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            out = render(d / "data.json", ROOT / "assets" / "template.html", d / "out.html")
            html = out.read_text(encoding="utf-8")
            self.assertNotIn("__DASHBOARD_DATA__", html)
            self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
            self.assertIn('id="__DATA__"', html)


if __name__ == "__main__":
    unittest.main()
