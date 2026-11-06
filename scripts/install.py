#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本仓库同步安装为 WorkBuddy 用户级 Skill。"""
from __future__ import annotations
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"output", ".git", "__pycache__", ".pytest_cache", ".venv"}
SKIP_FILES = {".DS_Store", "*.pyc"}


def main():
    ap = argparse.ArgumentParser(description="安装 workbuddy-token-dashboard Skill")
    ap.add_argument("--home", default=os.environ.get("WORKBUDDY_HOME") or str(Path.home() / ".workbuddy"))
    args = ap.parse_args()
    dest = Path(args.home) / "skills" / "workbuddy-token-dashboard"
    dest.mkdir(parents=True, exist_ok=True)

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
    print("[NEXT] 在 WorkBuddy 里启用该 Skill；首次启用时会创建每天 09:00 的自动刷新任务。")
    print("[NOTE] 仓库源码改动后请重新运行本脚本同步。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
