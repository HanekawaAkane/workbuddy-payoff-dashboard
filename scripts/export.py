#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / export.py

在**每一台设备**上运行，把本机 WorkBuddy 用量导出成一个便携 JSON 包，
放进同步盘（OneDrive / 坚果云 / 微云 / 私有 git 仓库都行）。主设备再用
  python scripts/run.py --sources <同步盘目录>
汇总重算，得到跨设备看板。

默认不含提示词摘要，只含四段 token、模型、时间、官方积分与会话标题。
"""
from __future__ import annotations
import argparse
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="导出本设备用量为可同步的便携包")
    ap.add_argument("--device", default=socket.gethostname(), help="设备名，默认主机名；多设备必须各自不同")
    ap.add_argument("--home", default=os.environ.get("WORKBUDDY_HOME") or str(Path.home() / ".workbuddy"))
    ap.add_argument("--out", default="", help="输出路径，默认 output/bundles/<设备名>.json")
    ap.add_argument("--with-prompts", action="store_true", help="包含提示词摘要（会导致包内含对话内容，慎用于同步盘）")
    ap.add_argument("--since", default="", help="仅导出 YYYY-MM-DD 之后的记录")
    args = ap.parse_args()

    device = args.device.strip() or "unknown"
    since_ts = None
    if args.since:
        from datetime import datetime
        since_ts = int(datetime.strptime(args.since, "%Y-%m-%d")
                       .replace(tzinfo=collect.CST).timestamp() * 1000)

    try:
        bundle = collect.make_bundle(Path(args.home), device, args.with_prompts)
        if since_ts:
            bundle["calls"] = [c for c in bundle["calls"] if c["ts"] >= since_ts]
    except (FileNotFoundError, ValueError) as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else ROOT / "output" / "bundles" / f"{device}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"[OK] 设备 {device}：{len(bundle['calls']):,} 次调用 / "
          f"{len(bundle['bills'])} 个会话有官方账单 / {len(bundle['sessions'])} 个会话")
    print(f"[OK] -> {out}  ({out.stat().st_size/1024:.0f} KB)")
    print("[NEXT] 把这个文件放进同步盘目录；主设备运行：")
    print(f"       python scripts/run.py --sources <同步盘目录> --open")
    if args.with_prompts:
        print("[WARN] 本次包含提示词摘要，同步盘上会有你的对话内容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
