#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / serve.py

本地看板服务。浏览器打开 http://127.0.0.1:8765 就能看到最新用量：
  - 每次请求都检查 WorkBuddy 日志/数据库的修改时间，变了就现场重新采集 + 渲染；
  - 页面每 20 秒探一次，源数据变了自动重载，不用手动刷新；
  - 也可以点右下角「重新读取」强制重算；
  - /api/data 直接吐原始 JSON，方便别的工具接。

只绑定回环地址，不监听公网；只读本机文件；不写任何数据。
不需要定时任务、不需要上传资料库、不需要事先生成 HTML 快照。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
from render import render_html  # noqa: E402

CST = timezone(timedelta(hours=8))

LIVE_BAR = """
<style>
#livebar{position:fixed;right:18px;bottom:18px;z-index:80;display:flex;align-items:center;gap:11px;
  background:#171a26;color:#fff;border-radius:30px;padding:9px 15px;font-size:11.5px;
  box-shadow:0 10px 30px rgba(0,0,0,.24);font-family:Inter,"Segoe UI","PingFang SC",sans-serif}
#livebar .dot{width:7px;height:7px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 3px rgba(74,222,128,.2)}
#livebar b{font-weight:700}
#livebar button{border:1px solid #4b5163;background:#2b3040;color:#fff;border-radius:16px;
  padding:4px 11px;font-size:11.5px;cursor:pointer;font-weight:600}
#livebar button:hover{background:#3b4156}
#livebar a{color:#a8b0c8;text-decoration:none;font-size:11px}
#livebar a:hover{color:#fff}
#livebar.busy .dot{background:#fbbf24;box-shadow:0 0 0 3px rgba(251,191,36,.2)}
</style>
<div id="livebar"><span class="dot"></span><span>本地实时 · 数据截止 <b id="liveAt">__GEN__</b></span>
  <button id="liveRefresh">重新读取</button><a href="/api/data" target="_blank">原始 JSON ↗</a></div>
<script>
(function(){
  var sig=__SIG__;
  var bar=document.getElementById('livebar');
  document.getElementById('liveRefresh').addEventListener('click',async function(){
    bar.classList.add('busy');
    try{ await fetch('/api/refresh',{cache:'no-store'}); }catch(e){}
    location.reload();
  });
  setInterval(async function(){
    try{
      var r=await fetch('/api/status',{cache:'no-store'});
      var j=await r.json();
      if(j.sig && j.sig!==sig) location.reload();
    }catch(e){}
  },20000);
})();
</script>
"""


class State:
    def __init__(self, home: Path, config: Path, template: Path, with_prompts: bool):
        self.home, self.config, self.template = home, config, template
        self.with_prompts = with_prompts
        self.lock = threading.Lock()
        self.html = ""
        self.data = None
        self.sig = 0.0
        self.generated = ""
        self.error = ""

    def rebuild(self, force: bool = False):
        sig = collect.source_signature(self.home)
        with self.lock:
            if self.html and not force and sig <= self.sig:
                return
            try:
                data = collect.collect_data(self.home, self.config, self.with_prompts)
                bar = (LIVE_BAR.replace("__GEN__", data["meta"]["generated_at"][:19].replace("T", " "))
                               .replace("__SIG__", json.dumps(sig)))
                self.html = render_html(data, self.template).replace("</body>", bar + "</body>")
                self.data = data
                self.sig = sig
                self.generated = data["meta"]["generated_at"]
                self.error = ""
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"

    def status(self) -> dict:
        with self.lock:
            d = self.data
            return {
                "ok": bool(self.html), "sig": self.sig, "generated": self.generated,
                "error": self.error,
                "n_calls": d["meta"]["n_calls"] if d else 0,
                "total_credit": d["meta"]["total_credit"] if d else 0,
                "total_api_cost": d["meta"]["total_api_cost"] if d else 0,
            }


STATE: State | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkBuddyTokenDashboard/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (datetime.now(CST).strftime("%H:%M:%S"), fmt % args))

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", code)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/favicon.ico":
            self._send(b"", "image/x-icon", 204)
            return
        if path in ("/", "/index.html"):
            STATE.rebuild()
            with STATE.lock:
                html, err = STATE.html, STATE.error
            if html:
                self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send(f"<h2>采集失败</h2><pre>{err}</pre>".encode("utf-8"),
                           "text/html; charset=utf-8", 500)
            return
        if path == "/api/refresh":
            STATE.rebuild(force=True)
            self._json(STATE.status())
            return
        if path == "/api/status":
            # 探测也顺带检查源数据是否变化，变了就后台重算，页面下一次刷新会拿到新数据
            sig = collect.source_signature(STATE.home)
            with STATE.lock:
                stale = sig > STATE.sig
            if stale:
                STATE.rebuild()
            self._json(STATE.status())
            return
        if path == "/api/data":
            STATE.rebuild()
            with STATE.lock:
                d = STATE.data
            if d is None:
                self._json({"error": STATE.error}, 500)
            else:
                self._json(d)
            return
        self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="本地 token 看板服务（打开浏览器即最新数据）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="只允许回环地址，改公网自负其责")
    ap.add_argument("--home", default=os.environ.get("WORKBUDDY_HOME") or str(Path.home() / ".workbuddy"))
    ap.add_argument("--config", default=str(ROOT / "config" / "pricing.json"))
    ap.add_argument("--template", default=str(ROOT / "assets" / "template.html"))
    ap.add_argument("--no-prompts", action="store_true", help="不在页面中嵌入提示词摘要")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    global STATE
    STATE = State(Path(args.home), Path(args.config), Path(args.template), not args.no_prompts)

    print("[INIT] 首次采集…", flush=True)
    STATE.rebuild(force=True)
    st = STATE.status()
    if not st["ok"]:
        print(f"[FATAL] {st['error']}", file=sys.stderr)
        return 2
    print(f"[OK] {st['n_calls']} 次调用 / 官方积分 {st['total_credit']:,.2f} / API 直购价 ¥{st['total_api_cost']:,.2f}")

    url = f"http://{args.host}:{args.port}/"
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[READY] {url}")
    print("[INFO] 源数据变化时页面会自动重载；Ctrl+C 退出。", flush=True)
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n[BYE]")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
