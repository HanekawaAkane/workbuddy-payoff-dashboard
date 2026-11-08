#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本仓库同步安装为 WorkBuddy 用户级 Skill。"""
from __future__ import annotations
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"output", ".git", ".workbuddy", "__pycache__", ".pytest_cache", ".venv"}
# 含共享密钥 / 本机私有数据的文件不进 Skill 目录
SKIP_FILES = {
    ".DS_Store", "*.pyc", "peers.json", "peers.demo.json", "library-sync.json",
    "settings.local.json", ".env", "credentials.json",
    "START-NODE-COMMAND.txt", "publish-manifest.json",
}


def main():
    ap = argparse.ArgumentParser(description="安装 workbuddy-token-dashboard Skill")
    ap.add_argument("--home", default=os.environ.get("WORKBUDDY_HOME") or str(Path.home() / ".workbuddy"))
    args = ap.parse_args()
    dest = Path(args.home) / "skills" / "workbuddy-token-dashboard"
    dest.mkdir(parents=True, exist_ok=True)

    # 清理早期版本同步进来的私有残留（copy2 不会自动删目标端多余文件）。
    # 只动本 Skill 目录内这几个明确路径，不碰其它东西。
    for rel in (".workbuddy", "config/peers.json", "config/peers.demo.json",
                "output/START-NODE-COMMAND.txt", "output/publish-manifest.json"):
        stale = dest / rel
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            stale.unlink()

    copied = 0
    for src in ROOT.rglob("*"):
        rel = src.relative_to(ROOT)
        if any(p in SKIP_DIRS for p in rel.parts):
            continue
        if src.is_dir():
            (dest / rel).mkdir(parents=True, exist_ok=True)
            continue
        if any(src.match(p) for p in SKIP_FILES):
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        copied += 1

    (dest / "output").mkdir(exist_ok=True)
    print(f"[OK] 已安装 {copied} 个文件 -> {dest}")
    print("[NEXT] 看板不依赖 Skill：双击 open-snapshot.bat 或 start-live.bat 即可外部打开。")
    print("[NEXT] 在 WorkBuddy 里启用该 Skill 后，也可以用「看看 token 消耗」触发。默认不创建定时任务。")
    print("[NOTE] 仓库源码改动后请重新运行本脚本同步。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
