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
import gzip
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
from render import render_html  # noqa: E402

CST = timezone(timedelta(hours=8))

LIVE_BAR = """
<style>
body{padding-bottom:58px}
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
#livebar.error .dot{background:#f87171;box-shadow:0 0 0 3px rgba(248,113,113,.2)}
#livebar button:disabled{opacity:.55;cursor:wait}
@media(max-width:640px){#livebar{left:12px;right:12px;bottom:12px;justify-content:center;gap:8px}#livebar a{display:none}}
</style>
<div id="livebar" role="status"><span class="dot"></span><span id="liveText">本地实时 · __DEV__ · 数据截止 <b id="liveAt">__GEN__</b></span>
  <button id="liveRefresh">重新读取</button><a href="/api/data" target="_blank">原始 JSON ↗</a></div>
<script>
(function(){
  var sig=__SIG__, busy=false;
  var bar=document.getElementById('livebar'), button=document.getElementById('liveRefresh');
  function state(kind,text){
    bar.classList.toggle('busy',kind==='busy'); bar.classList.toggle('error',kind==='error');
    if(text) document.getElementById('liveText').textContent=text;
  }
  async function poll(){
    if(busy||document.hidden) return;
    busy=true;
    try{
      var r=await fetch('/api/status',{cache:'no-store'}), j=await r.json();
      if(j.refreshing) state('busy','检测到变化，正在增量更新…');
      else if(j.error) state('error','更新失败：'+j.error);
      else if(j.sig&&j.sig!==sig) location.reload();
      else state('ok','本地实时 · 已是最新 · 数据截止 __GEN__');
      bar.title=j.last_duration_ms?('上次重算 '+j.last_duration_ms+' ms'+(j.cache?(' · 缓存命中 '+j.cache.hits+' 次'):'')):'';
    }catch(e){ state('error','本地服务连接失败，请确认服务仍在运行'); }
    finally{ busy=false; }
  }
  button.addEventListener('click',async function(){
    if(busy) return;
    busy=true; button.disabled=true; state('busy','正在重新读取…');
    try{
      var r=await fetch('/api/refresh',{cache:'no-store'}), j=await r.json();
      if(!r.ok||!j.ok) throw new Error(j.error||'刷新失败');
      location.reload();
    }catch(e){ state('error','刷新失败：'+e.message); }
    finally{ busy=false; button.disabled=false; }
  });
  setInterval(poll,20000);
})();
</script>
"""


class State:
    def __init__(self, homes, sources_dirs, device, no_local, with_local,
                 config: Path, template: Path, with_prompts: bool):
        self.homes, self.sources_dirs = list(homes), list(sources_dirs)
        self.device, self.no_local, self.with_local = device, no_local, with_local
        self.config, self.template = config, template
        self.with_prompts = with_prompts
        self.sources = collect.resolve_sources(self.homes, self.sources_dirs,
                                               device, no_local, with_local)
        self.lock = threading.Lock()          # 只保护可发布状态，不在重算期间占用
        self.rebuild_lock = threading.Lock()  # 同一时刻只允许一个采集任务
        self.cache = collect.ScanCache()
        self.html = ""
        self.data = None
        self.sig = ""
        self.generated = ""
        self.error = ""
        self.refreshing = False
        self.last_duration_ms = 0
        self.last_checked_at = ""

    def _watch_paths(self):
        paths = []
        skip_local = self.no_local or (self.sources_dirs and not self.homes and not self.with_local)
        specs = self.homes or ([] if skip_local else
                               [os.environ.get("WORKBUDDY_HOME") or str(Path.home() / ".workbuddy")])
        for spec in specs:
            paths.append(Path(spec.split("=", 1)[1] if "=" in spec else spec))
        for d in self.sources_dirs:
            paths.append(Path(d))
        for s in self.sources:
            if s.get("bundle"):
                paths.append(s["bundle"])
        return paths

    def signature(self) -> str:
        """完整结构指纹，文件删除 / 回滚 / 新便携包都能被发现。"""
        paths = self._watch_paths() + [self.template, self.config, ROOT / "scripts" / "serve.py"]
        return collect.path_fingerprint(paths)

    def rebuild(self, force: bool = False):
        started = time.perf_counter()
        with self.rebuild_lock:
            with self.lock:
                self.refreshing = True
            try:
                # 每次重算都重新发现便携包；未变化的文件由 ScanCache 直接复用。
                self.sources = collect.resolve_sources(self.homes, self.sources_dirs,
                                                       self.device, self.no_local, self.with_local)
                sig = self.signature()
                with self.lock:
                    if self.html and not force and sig == self.sig:
                        return
                data = collect.collect_from_sources(self.sources, self.config, self.with_prompts,
                                                    cache=self.cache)
                dev = data["meta"].get("devices", [])
                devtxt = f"{len(dev)} 台设备" if len(dev) > 1 else (dev[0] if dev else "本机")
                bar = (LIVE_BAR.replace("__GEN__", data["meta"]["generated_at"][:19].replace("T", " "))
                               .replace("__DEV__", devtxt)
                               .replace("__SIG__", json.dumps(sig)))
                html = render_html(data, self.template).replace("</body>", bar + "</body>")
                with self.lock:
                    self.html, self.data, self.sig = html, data, sig
                    self.generated = data["meta"]["generated_at"]
                    self.error = ""
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.error = f"{type(e).__name__}: {e}"
            finally:
                with self.lock:
                    self.refreshing = False
                    self.last_duration_ms = round((time.perf_counter() - started) * 1000)
                    self.last_checked_at = datetime.now(CST).isoformat(timespec="seconds")

    def rebuild_async(self):
        with self.lock:
            if self.refreshing:
                return None
            self.refreshing = True
        worker = threading.Thread(target=self.rebuild, daemon=True, name="dashboard-rebuild")
        worker.start()
        return worker

    def status(self) -> dict:
        with self.lock:
            d = self.data
            return {
                "ok": bool(self.html) and not self.error, "sig": self.sig, "generated": self.generated,
                "error": self.error, "refreshing": self.refreshing,
                "last_duration_ms": self.last_duration_ms, "last_checked_at": self.last_checked_at,
                "cache": self.cache.stats(), "source_count": len(self.sources),
                "n_calls": d["meta"]["n_calls"] if d else 0,
                "total_credit": d["meta"]["total_credit"] if d else 0,
                "total_api_cost": d["meta"]["total_api_cost"] if d else 0,
                "devices": d["meta"].get("devices", []) if d else [],
            }


STATE: State | None = None
CONFIG: dict = {"token": "", "bundle_device": socket.gethostname()}


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkBuddyTokenDashboard/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (datetime.now(CST).strftime("%H:%M:%S"), fmt % args))

    def _send(self, body: bytes, ctype: str, code: int = 200):
        compressed = False
        textual = ctype.startswith(("text/", "application/json", "application/javascript"))
        if len(body) > 2048 and textual and "gzip" in self.headers.get("Accept-Encoding", "").lower():
            body = gzip.compress(body, compresslevel=5)
            compressed = True
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        if code != 204:
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
            # 状态请求永不等待全量重算：变化由后台线程处理，下一轮轮询再取新页面。
            sig = STATE.signature()
            with STATE.lock:
                stale = sig != STATE.sig
            if stale:
                STATE.rebuild_async()
            result = STATE.status()
            result["stale"] = stale
            self._json(result)
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
        if path == "/api/bundle":
            # 给别的设备拉取用：只输出聚合后的逐调用明细，默认不含提示词
            if CONFIG["token"]:
                supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
                if supplied != CONFIG["token"]:
                    self._json({"error": "unauthorized"}, 401)
                    return
            STATE.rebuild()
            try:
                obj = collect.bundle_from_sources(STATE.sources, CONFIG["bundle_device"], False,
                                                  cache=STATE.cache)
                # 同源内容未变化时导出时间也保持稳定，便于对端识别无变化并避免重复落盘。
                obj["exported_at"] = STATE.generated or obj["exported_at"]
                self._json(obj)
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            return
        self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="本地 token 看板服务（打开浏览器即最新数据）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="只允许回环地址，改公网自负其责")
    ap.add_argument("--home", action="append", default=[],
                    help='设备数据目录，可重复；支持 "设备名=路径"')
    ap.add_argument("--sources", action="append", default=[],
                    help="便携包目录，可重复；读取其中所有 *.json（各设备 export.py 的输出）")
    ap.add_argument("--device", default="", help="单 --home 时的设备名")
    ap.add_argument("--no-local", action="store_true", help="不采集本机，只用 --sources")
    ap.add_argument("--with-local", action="store_true", help="用了 --sources 时也把本机一起算进来")
    ap.add_argument("--config", default=str(ROOT / "config" / "pricing.json"))
    ap.add_argument("--template", default=str(ROOT / "assets" / "template.html"))
    ap.add_argument("--no-prompts", action="store_true", help="不在页面中嵌入提示词摘要")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--token", default="", help="保护 /api/bundle 的共享密钥；对端 peers.json 里要填同一个")
    ap.add_argument("--bundle-device", default=socket.gethostname(),
                    help="/api/bundle 声称的设备名，默认主机名")
    ap.add_argument("--peers", default="", help="对端清单 JSON（config/peers.json），启用后定时主动拉取")
    ap.add_argument("--peer-out", default="", help="拉到的便携包存放目录，默认 output/bundles")
    ap.add_argument("--poll-seconds", type=int, default=0, help="覆盖 peers.json 里的 poll_seconds")
    ap.add_argument("--timeout", type=float, default=10.0, help="拉取单台对端的超时秒数")
    ap.add_argument("--library-sync", default="",
                    help="资料库同步配置 JSON；启用后定时从资料库文件夹拉各设备便携包")
    ap.add_argument("--library-poll-seconds", type=int, default=0,
                    help="覆盖资料库同步配置里的 poll_seconds")
    args = ap.parse_args()

    global STATE, CONFIG
    CONFIG = {"token": args.token, "bundle_device": args.bundle_device}

    sources_dirs = list(args.sources)
    peer_cfg, peer_out = None, None
    if args.peers:
        p = Path(args.peers)
        if not p.exists():
            print(f"[FATAL] 找不到对端清单 {p}", file=sys.stderr)
            return 2
        peer_cfg = json.loads(p.read_text(encoding="utf-8"))
        peer_out = Path(args.peer_out) if args.peer_out else ROOT / "output" / "bundles"
        peer_out.mkdir(parents=True, exist_ok=True)
        if str(peer_out) not in sources_dirs:
            sources_dirs.append(str(peer_out))
        # --peer-out 只放远端拉来的包，不会包含本机自己的导出，所以这里应当把本机算进来
        if not args.no_local and not args.with_local:
            args.with_local = True

    library_cfg, library_out = None, None
    if args.library_sync:
        lp = Path(args.library_sync)
        if not lp.exists():
            print(f"[FATAL] 找不到资料库同步配置 {lp}", file=sys.stderr)
            return 2
        library_cfg = json.loads(lp.read_text(encoding="utf-8"))
        library_out = ROOT / library_cfg.get("out_dir", "output/bundles")
        library_out.mkdir(parents=True, exist_ok=True)
        if str(library_out) not in sources_dirs:
            sources_dirs.append(str(library_out))
        # 同理：资料库拉来的都是别的设备的包，本机数据要一起算
        if not args.no_local and not args.with_local:
            args.with_local = True

    # 非回环监听时强制不含提示词：否则整个局域网都能看到你的对话摘要
    loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not args.no_prompts:
        print("[WARN] 非回环监听，已强制 --no-prompts（不向网络暴露提示词摘要）。", flush=True)
    if not loopback and not args.token:
        print("[WARN] 非回环监听但未设置 --token，/api/bundle 任何人可拉取。建议加 --token。", flush=True)

    try:
        STATE = State(args.home, sources_dirs, args.device, args.no_local, args.with_local,
                      Path(args.config), Path(args.template),
                      not (args.no_prompts or not loopback))
    except (FileNotFoundError, ValueError) as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 2

    print("[INIT] 首次采集…", flush=True)
    STATE.rebuild(force=True)
    st = STATE.status()
    if not st["ok"]:
        print(f"[FATAL] {st['error']}", file=sys.stderr)
        return 2
    devices = STATE.data["meta"]["devices"] if STATE.data else []
    print(f"[OK] 设备 {len(devices)} 台：{', '.join(devices)}")
    print(f"[OK] {st['n_calls']} 次调用 / 官方积分 {st['total_credit']:,.2f} / API 直购价 ¥{st['total_api_cost']:,.2f}")

    if peer_cfg:
        import peers  # noqa: E402
        poll = args.poll_seconds or int(peer_cfg.get("poll_seconds", 60))
        def _log(msg):
            sys.stderr.write("[%s] [PEER] %s\n" % (datetime.now(CST).strftime("%H:%M:%S"), msg))
            sys.stderr.flush()
        def _loop():
            # 先立刻拉一次，再按间隔轮询
            while True:
                try:
                    peers.sync_peers(peer_cfg, peer_out, args.timeout, log=_log)
                except Exception as e:  # noqa: BLE001
                    _log(f"轮询异常：{type(e).__name__}: {e}")
                time.sleep(max(10, poll))
        threading.Thread(target=_loop, daemon=True, name="peer-poller").start()
        print(f"[PEER] 每 {max(10, poll)} 秒拉取 {len(peer_cfg.get('peers', []))} 个对端 -> {peer_out}", flush=True)

    if library_cfg:
        import library_sync  # noqa: E402
        lpoll = args.library_poll_seconds or int(library_cfg.get("poll_seconds", 300))

        def _lib_log(msg):
            sys.stderr.write("[%s] [LIBRARY] %s\n" % (datetime.now(CST).strftime("%H:%M:%S"), msg))
            sys.stderr.flush()

        def _lib_loop():
            while True:
                try:
                    library_sync.sync_once(library_cfg, library_out, log=_lib_log)
                except Exception as e:  # noqa: BLE001
                    _lib_log(f"轮询异常：{type(e).__name__}: {e}")
                time.sleep(max(30, lpoll))

        threading.Thread(target=_lib_loop, daemon=True, name="library-poller").start()
        print(f"[LIBRARY] 每 {max(30, lpoll)} 秒从资料库文件夹同步 -> {library_out}", flush=True)

    url = f"http://{args.host}:{args.port}/"
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[READY] {url}")
    print("[INFO] 源数据变化 / 对端上线时页面会自动重载；Ctrl+C 退出。", flush=True)
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
