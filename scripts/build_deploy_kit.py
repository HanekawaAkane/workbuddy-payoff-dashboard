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
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 白名单：只打包这些目录，.workbuddy/（工作区记忆、自动化记录）、output/（本机真实用量）、
# .git/ 等一律进不来。曾因纯黑名单漏掉 .workbuddy/memory 而把本机笔记打进过包。
INCLUDE_DIRS = {"assets", "config", "deploy", "examples", "scripts", "tests"}
INCLUDE_ROOT_FILES = {
    "README.md", "SKILL.md", "LICENSE", ".gitignore",
    "export-device.bat", "open-snapshot.bat", "start-live.bat",
    "start-multi.bat", "start-peers.bat",
}
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv", "venv", ".idea", ".vscode"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3"}
# 含共享密钥 / 本机产物的文件绝不进部署包
SKIP_FILES = {
    "peers.json", "peers.demo.json", "library-sync.json", "library-target.json",
    "settings.local.json", "credentials.json", ".env",
    "publish-manifest.json", "START-NODE-COMMAND.txt",
}
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
        if len(rel.parts) == 1:
            if p.name not in INCLUDE_ROOT_FILES:
                continue
        elif rel.parts[0] not in INCLUDE_DIRS:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX or p.name in SKIP_FILES:
            continue
        files.append((p, rel))

    # 兜底断言：白名单失效时宁可拒绝打包，也不要把本机私有数据送出去
    leaked = [str(rel) for _, rel in files
              if ".workbuddy" in rel.parts or "output" in rel.parts or rel.name in SKIP_FILES]
    if leaked:
        raise RuntimeError(f"部署包拒绝打包本机私有文件：{leaked}")

    # 把资料库目标文件夹 ID 注入部署包，让另一台设备解压后双击即可上传，
    # 不必手敲 ID。只写 folder_id / space_id，不含任何密钥或本机用量。
    target = {}
    cfg = ROOT / "config" / "library-sync.json"
    if cfg.exists():
        try:
            c = json.loads(cfg.read_text(encoding="utf-8"))
            if c.get("folder_id") and not str(c["folder_id"]).startswith("PASTE_"):
                target = {"folder_id": c["folder_id"], "space_id": c.get("space_id", "")}
        except (OSError, ValueError):
            pass

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p, rel in files:
            z.write(p, f"{TOP_DIR}/{rel.as_posix()}")
        if target:
            z.writestr(f"{TOP_DIR}/config/library-target.json",
                       json.dumps(target, ensure_ascii=False, indent=2) + "\n")

    print(f"[OK] {len(files)} 个文件 -> {out}  ({out.stat().st_size/1024:.0f} KB)")
    print(f"[CONFIG] 已注入资料库文件夹：{target.get('folder_id', '(未配置，对端需手填)')}")
    print("[SAFE] 白名单打包：不含 .workbuddy/ 记忆、output/ 本机用量、日志或提示词。")
    print("[NEXT] 把这个 ZIP 传到另一台设备，解压后看 deploy/README.txt。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
