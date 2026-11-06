#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键刷新：采集本地数据 -> 渲染带时间戳的 HTML -> 写 latest 副本。"""
from __future__ import annotations
import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description="刷新 WorkBuddy Token Dashboard")
    ap.add_argument("--home", default="")
    ap.add_argument("--no-prompts", action="store_true", help="不写入提示词摘要，便于对外分享")
    ap.add_argument("--no-latest", action="store_true")
    ap.add_argument("--out", default="", help="指定 HTML 输出路径")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开（双击即看最新快照）")
    args = ap.parse_args()

    py = sys.executable
    common = []
    if args.home:
        common += ["--home", args.home]
    if args.no_prompts:
        common += ["--no-prompts"]

    data = ROOT / "output" / "data.json"
    steps = [
        [py, str(ROOT / "scripts" / "collect.py"), "--out", str(data)] + common,
        [py, str(ROOT / "scripts" / "render.py"), "--data", str(data)]
        + (["--out", args.out] if args.out else [])
        + ([] if args.no_latest else ["--latest"]),
    ]
    for cmd in steps:
        print("$", " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0:
            print(f"[FATAL] 步骤失败（exit {r.returncode}）", file=sys.stderr)
            return r.returncode

    outdir = ROOT / "output"
    target = Path(args.out) if args.out else (outdir / "token-dashboard-latest.html")
    if target.exists():
        print(f"\n[DONE] 最新看板：{target}")
    if args.open and target.exists():
        webbrowser.open(target.resolve().as_uri())
        print("[OPEN] 已在默认浏览器打开。")
    else:
        print("[TIP] 想常驻实时刷新请用 python scripts/serve.py --open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
