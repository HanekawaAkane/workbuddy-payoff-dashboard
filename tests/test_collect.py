# -*- coding: utf-8 -*-
"""纯标准库单元测试：python -m unittest discover -s tests -v"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
import serve  # noqa: E402
from render import safe_json, render, render_html  # noqa: E402

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
            # 零外部依赖：不能有 CDN 脚本 / 样式表（文档里的 localhost 示例链接不算）
            self.assertFalse('<script src=' in html, "模板引入了外部脚本")
            self.assertFalse('<link rel="stylesheet"' in html, "模板引入了外部样式")
            self.assertIn('id="__DATA__"', html)
            self.assertIn('id="granSeg"', html)          # 按天 / 0-24 时粒度切换
            self.assertIn('renderDistribution()', html)   # 泛化后的堆叠柱渲染
            # 内存渲染与文件渲染结果一致
            self.assertEqual(html, render_html(data, ROOT / "assets" / "template.html"))


class TestLiveServer(unittest.TestCase):
    def test_source_signature_tracks_changes(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "projects").mkdir()
            (home / "workbuddy.db").write_bytes(b"x")
            f = home / "projects" / "a.jsonl"
            f.write_text("{}\n", encoding="utf-8")
            s1 = collect.source_signature(home)
            self.assertGreater(s1, 0)
            os.utime(f, (time.time() + 5, time.time() + 5))
            self.assertGreater(collect.source_signature(home), s1)

    def test_state_rebuild_and_live_bar(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "projects").mkdir()
            # 故意不建 workbuddy.db：验证「无账单」时也能正常回退
            (home / "projects" / "a.jsonl").write_text(
                json.dumps({"type": "message", "timestamp": 1793930000000,
                            "providerData": {"messageId": "m1", "model": "glm-5.3-flash",
                                             "conversationRequestId": "r1",
                                             "rawUsage": {"prompt_tokens": 1110, "completion_tokens": 50,
                                                          "prompt_cache_hit_tokens": 1000,
                                                          "prompt_cache_miss_tokens": 110,
                                                          "credit": 0.1}}}) + "\n",
                encoding="utf-8")
            st = serve.State([f"testdev={home}"], [], "", False, False,
                             ROOT / "config" / "pricing.json",
                             ROOT / "assets" / "template.html", False)
            st.rebuild(force=True)
            self.assertTrue(st.status()["ok"], st.status()["error"])
            self.assertIn('id="livebar"', st.html)
            self.assertIn("/api/refresh", st.html)
            self.assertNotIn("__DASHBOARD_DATA__", st.html)
            self.assertEqual(st.status()["n_calls"], 1)
            self.assertEqual(st.status()["devices"], ["testdev"])


def _fake_home(td: str, name: str, n: int = 2, sid: str = "same-session"):
    """造一个最小可用的假 WorkBuddy 目录，session_id 故意复用，检验设备前缀隔离。"""
    home = Path(td) / name
    (home / "projects").mkdir(parents=True)
    lines = [json.dumps({"type": "message", "role": "user",
                         "timestamp": 1793929999000,
                         "content": [{"type": "input_text", "text": "帮我查一下用量"}]})]
    for k in range(n):
        lines.append(json.dumps({
            "type": "message", "timestamp": 1793930000000 + k * 1000,
            "providerData": {
                "messageId": f"{name}-m{k}", "model": "glm-5.3-flash",
                "requestModelName": "GLM-5.3-Flash", "conversationRequestId": f"{name}-req",
                "rawUsage": {"prompt_tokens": 1110, "completion_tokens": 50,
                             "prompt_cache_hit_tokens": 1000, "prompt_cache_miss_tokens": 110,
                             "credit": 0.1}}}))
    (home / "projects" / f"{sid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return home


class TestMultiDevice(unittest.TestCase):
    def test_merge_two_devices_keeps_sessions_separate(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = _fake_home(td, "laptop", 2), _fake_home(td, "desktop", 3)
            sources = [{"device": "laptop", "home": a, "bundle": None},
                       {"device": "desktop", "home": b, "bundle": None}]
            data = collect.collect_from_sources(sources, ROOT / "config" / "pricing.json", False)
            self.assertEqual(data["meta"]["devices"], ["desktop", "laptop"])
            self.assertEqual(data["meta"]["n_calls"], 5)
            self.assertEqual(data["meta"]["n_sessions"], 2)   # session UUID 相同但设备前缀不同
            devs = sorted(s[4] for s in data["sessions"])
            self.assertEqual(devs, ["desktop", "laptop"])
            self.assertEqual(len(data["calls"][0]), 12)         # call 行 schema 不变

    def test_bundle_roundtrip_and_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            home = _fake_home(td, "laptop", 2)
            bundle = collect.make_bundle(home, "laptop", False)
            self.assertEqual(bundle["schema"], collect.BUNDLE_SCHEMA)
            self.assertEqual(bundle["prompts"], {})
            p = Path(td) / "laptop.json"
            p.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
            # 同一个包塞两次，去重后不能翻倍
            sources = [{"device": None, "home": None, "bundle": p}] * 2
            data = collect.collect_from_sources(sources, ROOT / "config" / "pricing.json", False)
            self.assertEqual(data["meta"]["n_calls"], 2)
            self.assertEqual(data["meta"]["devices"], ["laptop"])

    def test_export_default_strips_prompts(self):
        with tempfile.TemporaryDirectory() as td:
            home = _fake_home(td, "laptop", 1)
            plain = collect.make_bundle(home, "laptop", False)
            self.assertNotIn("帮我查一下用量", json.dumps(plain, ensure_ascii=False))
            self.assertEqual(plain["prompts"], {})
            full = collect.make_bundle(home, "laptop", True)
            self.assertIn("帮我查一下用量", json.dumps(full, ensure_ascii=False))

    def test_resolve_sources_and_signature(self):
        with tempfile.TemporaryDirectory() as td:
            home = _fake_home(td, "laptop", 1)
            sdir = Path(td) / "bundles"
            sdir.mkdir()
            p = sdir / "laptop.json"
            p.write_text(json.dumps(collect.make_bundle(home, "laptop", False),
                                   ensure_ascii=False), encoding="utf-8")
            s = collect.resolve_sources([f"mydev={home}"], [str(sdir)], "", False)
            self.assertEqual(len(s), 2)
            self.assertEqual(s[0]["device"], "mydev")
            self.assertEqual(s[1]["bundle"], p)
            sig1 = collect.path_signature([sdir])
            os.utime(p, (time.time() + 5, time.time() + 5))
            self.assertGreater(collect.path_signature([sdir]), sig1)
            # 只给 --sources 且没有显式 --home 时，默认不带本机，避免本机重复计数
            only = collect.resolve_sources([], [str(sdir)], "", False, False)
            self.assertEqual(len(only), 1)
            self.assertTrue(all(x["bundle"] for x in only))
            both = collect.resolve_sources([], [str(sdir)], "", False, True)
            self.assertEqual(len(both), 2)


class TestPeerPull(unittest.TestCase):
    """用临时 HTTP 服务模拟「另一台在线设备」。"""

    @staticmethod
    def _serve(bundle, token):
        import http.server
        import threading
        payload = json.dumps(bundle, ensure_ascii=False).encode("utf-8")

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                from urllib.parse import parse_qs, urlparse
                u = urlparse(self.path)
                if u.path != "/api/bundle" or parse_qs(u.query).get("token", [""])[0] != token:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"unauthorized"}')
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, f"http://127.0.0.1:{srv.server_address[1]}"

    def test_fetch_and_skip_offline_peer(self):
        import peers  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            home = _fake_home(td, "laptop", 2)
            bundle = collect.make_bundle(home, "远端A", False)
            srv, base = self._serve(bundle, "sekret")
            try:
                got = peers.fetch_bundle(base, "sekret", timeout=5)
                self.assertEqual(got["device"], "远端A")
                self.assertEqual(len(got["calls"]), 2)
                with self.assertRaises(Exception):
                    peers.fetch_bundle(base, "wrong", timeout=5)   # 401

                cfg = {"peers": [
                    {"name": "在线", "url": base, "token": "sekret", "enabled": True},
                    {"name": "离线", "url": "http://127.0.0.1:1", "enabled": True},
                    {"name": "停用", "url": base, "enabled": False},
                ]}
                logs = []
                out = Path(td) / "incoming"
                written = peers.sync_peers(cfg, out, timeout=5, log=logs.append)
                self.assertEqual(len(written), 1)
                self.assertEqual(written[0].name, "远端A.json")
                self.assertTrue(any("SKIP" in x and "离线" in x for x in logs))
            finally:
                srv.shutdown()
                srv.server_close()

    def test_bundle_from_sources_reprefixes_device(self):
        with tempfile.TemporaryDirectory() as td:
            a = _fake_home(td, "a", 2)
            b = _fake_home(td, "b", 3)
            srcs = [{"device": "a", "home": a, "bundle": None},
                    {"device": "b", "home": b, "bundle": None}]
            out = collect.bundle_from_sources(srcs, "统一节点", False)
            self.assertEqual(out["device"], "统一节点")
            self.assertEqual(len(out["calls"]), 5)
            self.assertTrue(all(c["sid"].startswith("统一节点::") for c in out["calls"]))
            self.assertTrue(all(c["uid"].startswith("统一节点::") for c in out["calls"]))
            self.assertEqual(out["prompts"], {})
            # 拉回来的包能直接进汇总
            p = Path(td) / "node.json"
            p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            dev, calls, bills, sessions, prompts = collect.load_bundle(p)
            self.assertEqual((dev, len(calls)), ("统一节点", 5))


if __name__ == "__main__":
    unittest.main()
