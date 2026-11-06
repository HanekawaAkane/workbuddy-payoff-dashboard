#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键刷新：采集本地数据 -> 渲染带时间戳的 HTML -> 写 latest 副本。"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description="刷新 WorkBuddy Token Dashboard")
    ap.add_argument("--home", default="")
    ap.add_argument("--no-prompts", action="store_true", help="不写入提示词摘要，便于对外分享")
    ap.add_argument("--no-latest", action="store_true")
    ap.add_argument("--out", default="", help="指定 HTML 输出路径")
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
    htmls = sorted(outdir.glob("token-dashboard-*.html"))
    if htmls:
        print(f"\n[DONE] 最新看板：{htmls[-1]}")
        print("[NEXT] 若为定时任务，请把该文件上传到 WorkBuddy 资料库。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
