#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / keep_online.py

把节点服务变成常驻：子进程意外退出后自动重启（1s → 30s 指数退避）。

    # 另一台设备（对端节点，向可信网络暴露 /api/bundle）
    python scripts/keep_online.py --mode node --token <共享密钥> --port 8765 --device %COMPUTERNAME%

    # 本机（汇总端，只绑 127.0.0.1，按 config/peers.json 定时拉对端）
    python scripts/keep_online.py --mode main

Ctrl+C 结束守护。--once 只跑一次，供自测使用。
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))


def node_command(token: str, port: int, device: str) -> list[str]:
    return [
        sys.executable, str(ROOT / "scripts" / "serve.py"),
        "--host", "0.0.0.0", "--port", str(port),
        "--token", token, "--bundle-device", device, "--no-prompts",
    ]


def main_command(port: int = 8765, host: str = "127.0.0.1") -> tuple[list[str], str]:
    """汇总端只绑回环地址。配置存在才启用直连拉取 / 资料库同步。"""
    cmd = [
        sys.executable, str(ROOT / "scripts" / "serve.py"),
        "--host", host, "--port", str(port), "--no-prompts",
    ]
    notes = []
    peers = ROOT / "config" / "peers.json"
    if peers.exists():
        cmd += ["--peers", str(peers)]
        notes.append(f"直连拉取：{peers.name}")
    lib = ROOT / "config" / "library-sync.json"
    if lib.exists():
        cmd += ["--library-sync", str(lib)]
        notes.append(f"资料库同步：{lib.name}")
    return cmd, " / ".join(notes) if notes else "未找到对端配置，退化为单设备本地看板"


def printable(cmd: list[str]) -> str:
    """日志里打码 --token，避免密钥落在控制台/日志里。"""
    out, hide = [], False
    for part in cmd:
        if hide:
            out.append("***")
            hide = False
        else:
            out.append(part)
            hide = part == "--token"
    return " ".join(out)


def supervise(cmd: list[str], label: str, once: bool = False) -> int:
    delay = 1
    while True:
        stamp = datetime.now(CST).strftime("%H:%M:%S")
        print(f"[{stamp}] 启动 {label}: {printable(cmd)}", flush=True)
        started = time.time()
        try:
            rc = subprocess.call(cmd, cwd=str(ROOT))
        except KeyboardInterrupt:
            print("\n[STOP] 收到 Ctrl+C，结束守护。", flush=True)
            return 0
        except OSError as e:
            print(f"[ERROR] 无法启动子进程：{e}", flush=True)
            rc = 1
        if once:
            return rc
        if time.time() - started > 60:
            delay = 1  # 稳定运行过一段时间，重置退避
        print(f"[WARN] {label} 退出（code={rc}），{delay}s 后自动重启；Ctrl+C 结束。", flush=True)
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            print("\n[STOP] 收到 Ctrl+C，结束守护。", flush=True)
            return 0
        delay = min(delay * 2, 30)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="常驻守护：对端节点 / 本机汇总端")
    ap.add_argument("--mode", choices=("node", "main"), required=True)
    ap.add_argument("--token", default="", help="node 模式必填，须与汇总端 peers.json 一致")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--device", default=socket.gethostname())
    ap.add_argument("--host", default="127.0.0.1", help="main 模式监听地址，默认只绑回环")
    ap.add_argument("--once", action="store_true", help="只跑一次，不自动重启")
    args = ap.parse_args(argv)

    if args.mode == "node":
        bad = {"", "change-me", "change-me-to-a-long-random-string"}
        if args.token in bad or len(args.token) < 16:
            print("[FATAL] node 模式需要 --token 一个足够长的共享密钥（>=16 字符）。", file=sys.stderr)
            return 2
        cmd = node_command(args.token, args.port, args.device)
        label = f"对端节点 {args.device} @ 0.0.0.0:{args.port}"
    else:
        cmd, note = main_command(args.port, args.host)
        label = f"本机汇总端 @ {args.host}:{args.port}"
        print(f"[INFO] {note}", flush=True)

    print(f"[INFO] 看板地址：http://{args.host if args.mode == 'main' else '127.0.0.1'}:{args.port}/", flush=True)
    return supervise(cmd, label, args.once)


if __name__ == "__main__":
    raise SystemExit(main())
