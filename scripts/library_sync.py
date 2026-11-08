#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / library_sync.py

在【主设备】上跑：从资料库专用文件夹拉取各设备的便携包 → 落盘到 bundles 目录。
serve.py 本来就在监视这个目录，新包落地后看板自动重算并重载。

    python scripts/library_sync.py --config config/library-sync.json --once
    python scripts/library_sync.py --config config/library-sync.json --loop

也可由 serve.py --library-sync 直接在轮询线程里调用 sync_once()。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
import library_io  # noqa: E402

TITLE_SUFFIX = ".token-bundle"


def safe_name(dev: str) -> str:
    return "".join(ch for ch in str(dev) if ch.isalnum() or ch in "-_").strip() or "device"


def validate(raw: bytes) -> dict:
    """只接受本项目导出的、不含提示词的便携包。"""
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"不是合法 JSON：{e}") from e
    if obj.get("schema") != collect.BUNDLE_SCHEMA:
        raise ValueError(f"便携包 schema 不匹配：{obj.get('schema')!r}")
    if not isinstance(obj.get("device"), str) or not obj["device"].strip():
        raise ValueError("便携包缺少 device")
    if not isinstance(obj.get("calls"), list):
        raise ValueError("便携包缺少 calls 列表")
    if obj.get("prompts"):
        raise ValueError("便携包含提示词摘要，拒绝落盘（本项目跨设备传输一律不带提示词）")
    return obj


def sync_once(cfg: dict, out_dir: Path, io=None, log=print) -> list[Path]:
    """列举文件夹 → 逐个下载 → 校验 → 内容变化才写盘。返回本次写入的路径。"""
    io = io or library_io
    folder = cfg.get("folder_id", "")
    if not folder:
        raise ValueError("配置缺少 folder_id")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = cfg.get("title_suffix", TITLE_SUFFIX)
    allow = set(cfg.get("devices") or [])

    nodes = io.list_folder(folder, cfg.get("space_id", ""), int(cfg.get("limit", 100)))
    written = []
    for n in nodes:
        if n.get("kind") != "drive":
            continue
        title = str(n.get("title", ""))
        if suffix and not title.endswith(suffix):
            continue
        if allow and title.removesuffix(suffix) not in allow:
            continue
        nid = n.get("id", "")
        try:
            raw, _info = io.download(nid)
            obj = validate(raw)
            dev = safe_name(obj["device"])
            dest = out_dir / f"{dev}.json"
            if dest.exists() and dest.read_bytes() == raw:
                log(f"[SAME] {title} 无变化")
                continue
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            tmp.write_bytes(raw)
            tmp.replace(dest)
            written.append(dest)
            log(f"[OK] {title} -> {dest.name}：{len(obj['calls']):,} 次调用，{len(raw)/1024:.0f} KB")
        except Exception as e:  # noqa: BLE001
            log(f"[SKIP] {title or nid}：{type(e).__name__}: {e}")
    return written


def load_config(path: Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到配置 {p}；从 config/library-sync.example.json 复制一份填写")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("配置必须是 JSON 对象")
    return cfg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从资料库拉取各设备 token 便携包")
    ap.add_argument("--config", default=str(ROOT / "config" / "library-sync.json"))
    ap.add_argument("--out", default="", help="覆盖配置里的 out_dir")
    ap.add_argument("--once", action="store_true", help="只同步一次")
    ap.add_argument("--loop", action="store_true", help="按 poll_seconds 常驻轮询")
    ap.add_argument("--poll-seconds", type=int, default=0, help="覆盖配置里的轮询间隔")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(Path(args.config))
    except (FileNotFoundError, ValueError) as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else ROOT / cfg.get("out_dir", "output/bundles")
    poll = args.poll_seconds or int(cfg.get("poll_seconds", 300))

    while True:
        try:
            written = sync_once(cfg, out)
            print(f"[DONE] 写入 {len(written)} 个便携包 -> {out}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] 同步失败：{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if args.once or not args.loop:
            return 0
        time.sleep(max(30, poll))


if __name__ == "__main__":
    raise SystemExit(main())
