#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把整个项目（不含本机真实数据）打成一个 ZIP，拷到另一台设备解压即用。

    python scripts/build_deploy_kit.py
    -> output/workbuddy-token-exporter.zip

另一台设备解压后双击 deploy/START-NODE.bat 或 deploy/EXPORT.bat。
"""
from __future__ import annotations
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"output", ".git", "__pycache__", ".pytest_cache", ".venv", "venv", ".idea", ".vscode"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log"}
# 含共享密钥 / 内网地址的文件绝不进部署包
SKIP_FILES = {"peers.json", "peers.demo.json", "settings.local.json"}
TOP_DIR = "workbuddy-token-exporter"


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成另一台设备用的部署 ZIP")
    ap.add_argument("--out", default=str(ROOT / "output" / "workbuddy-token-exporter.zip"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    files = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX or p.name in SKIP_FILES:
            continue
        files.append((p, rel))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, rel in files:
            z.write(p, f"{TOP_DIR}/{rel.as_posix()}")

    print(f"[OK] {len(files)} 个文件 -> {out}  ({out.stat().st_size/1024:.0f} KB)")
    print("[SAFE] 不含 output/ 下的任何本机真实数据、日志或提示词。")
    print("[NEXT] 把这个 ZIP 传到另一台设备，解压后看 deploy/README.txt。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
