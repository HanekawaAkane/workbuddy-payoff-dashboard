#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / peers.py

从「在线的对端设备」主动拉取 token 明细便携包。

每台设备跑 `serve.py --token <共享密钥>`，把 `/api/bundle` 暴露给可信网络
（局域网 IP 或 Tailscale 虚拟网，别直接裸奔公网）。主设备按 config/peers.json
定时 GET，把结果写进 bundles 目录；serve.py 已在监视该目录，页面会自动重载。

单独跑一次：
    python scripts/peers.py --config config/peers.json --out output/bundles
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402


def fetch_bundle(url: str, token: str = "", timeout: float = 10.0) -> dict:
    base = url.rstrip("/")
    sep = "&" if "?" in base else "?"
    full = base + "/api/bundle" + (sep + "token=" + urllib.parse.quote(token) if token else "")
    req = urllib.request.Request(full, headers={"User-Agent": "workbuddy-token-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        obj = json.loads(r.read().decode("utf-8"))
    if obj.get("schema") != collect.BUNDLE_SCHEMA:
        raise ValueError(f"对端返回的不是便携包（schema={obj.get('schema')!r}）：{base}")
    if not obj.get("device") or not isinstance(obj.get("calls"), list):
        raise ValueError(f"对端便携包字段不完整：{base}")
    return obj


def sync_peers(cfg: dict, out_dir: Path, timeout: float = 10.0, log=print) -> list[Path]:
    """逐个拉取；离线 / 失败的对端跳过，不影响其它设备。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    default_token = cfg.get("token", "")
    written = []
    for p in cfg.get("peers", []):
        if not p.get("enabled", True):
            continue
        name = p.get("name") or p.get("url")
        try:
            obj = fetch_bundle(p["url"], p.get("token", default_token), timeout)
        except Exception as e:  # noqa: BLE001
            log(f"[SKIP] {name} 离线或不可达：{type(e).__name__}: {e}")
            continue
        dev = obj["device"]
        # 设备名做文件名，挡掉路径穿越
        safe = "".join(ch for ch in dev if ch.isalnum() or ch in "-_.").strip() or "peer"
        dest = out_dir / f"{safe}.json"
        dest.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        written.append(dest)
        log(f"[OK] {name} -> {safe}.json：{len(obj['calls']):,} 次调用，{dest.stat().st_size/1024:.0f} KB")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="从在线对端设备拉取 token 明细")
    ap.add_argument("--config", default=str(ROOT / "config" / "peers.json"))
    ap.add_argument("--out", default=str(ROOT / "output" / "bundles"))
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args(argv)
    p = Path(args.config)
    if not p.exists():
        print(f"[FATAL] 找不到 {p}；请从 config/peers.example.json 复制一份填写。", file=sys.stderr)
        return 2
    cfg = json.loads(p.read_text(encoding="utf-8"))
    written = sync_peers(cfg, Path(args.out), args.timeout)
    print(f"[DONE] 拉到 {len(written)} 台设备 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
