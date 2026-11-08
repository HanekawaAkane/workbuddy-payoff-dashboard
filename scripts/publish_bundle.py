#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / publish_bundle.py

在【另一台设备】上跑：导出本机便携包 → 原地覆盖到资料库的固定文件节点。

    python scripts/publish_bundle.py --device 笔记本 --folder-id <文件夹ID>

供 WorkBuddy 自动化任务每天调用。关键点：**每台设备一个固定节点**，
按标题找到同名 drive 节点就用 --node-id 覆盖，保持节点 ID 与链接不变，
不会像每天新建 HTML 那样堆一坨快照。

便携包默认不含提示词，只含四段 token / 模型 / 时间 / 官方积分 / 会话标题。
资料库凭据由 WorkBuddy 会话环境提供；若脚本直接调不通，会打印清晰的人工指令。
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
import library_io  # noqa: E402

SUFFIX = ".token-bundle.json"
TITLE_SUFFIX = ".token-bundle"   # 服务端标题会剥掉 .json


def safe_name(dev: str) -> str:
    return "".join(ch for ch in dev if ch.isalnum() or ch in "-_").strip() or "device"


def default_folder_id() -> str:
    """一键上传的关键：目标文件夹 ID 从部署包注入的配置 / 本机配置里读，不用手敲。"""
    v = os.environ.get("WORKBUDDY_BUNDLE_FOLDER", "").strip()
    if v:
        return v
    for name in ("config/library-target.json", "config/library-sync.json"):
        p = ROOT / name
        if not p.exists():
            continue
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            fid = str(c.get("folder_id", "")).strip()
            if fid and not fid.startswith("PASTE_"):
                return fid
        except (OSError, ValueError):
            continue
    return ""


def export_bundle(home: Path, device: str, out: Path) -> dict:
    if not home.exists():
        raise FileNotFoundError(f"WorkBuddy 数据目录不存在：{home}")
    bundle = collect.make_bundle(home, device, with_prompts=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    return bundle


def publish(bundle_path: Path, device: str, folder_id: str) -> dict:
    """上传到固定节点；找不到同名节点时新建。返回 {node_id, url, created}。"""
    file_name = device + SUFFIX
    node_id = library_io.find_child(folder_id, device + TITLE_SUFFIX)
    info = library_io.upload(bundle_path, file_name,
                             parent_id="" if node_id else folder_id,
                             node_id=node_id)
    return {"node_id": info.get("node_block_id", ""),
            "url": info.get("url", ""), "created": not node_id}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="导出本机 token 明细并发布到资料库固定节点")
    ap.add_argument("--device", default=socket.gethostname(), help="设备名，跨设备必须唯一")
    ap.add_argument("--home", default=os.environ.get("WORKBUDDY_HOME")
                    or str(Path.home() / ".workbuddy"))
    ap.add_argument("--out", default="", help="便携包输出路径，默认 output/<设备名>.token-bundle.json")
    ap.add_argument("--folder-id", default="",
                    help="资料库目标文件夹 ID；默认自动读 config/library-target.json "
                         "（打包时注入）/ library-sync.json，也可用环境变量 WORKBUDDY_BUNDLE_FOLDER")
    ap.add_argument("--no-upload", action="store_true", help="只导出，不上传")
    args = ap.parse_args(argv)

    dev = safe_name(args.device)
    bundle_path = Path(args.out) if args.out else ROOT / "output" / (dev + SUFFIX)
    try:
        bundle = export_bundle(Path(args.home), dev, bundle_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 2
    print(f"[OK] 导出 {dev}：{len(bundle['calls']):,} 次调用 / "
          f"{len(bundle['sessions'])} 个会话 / 提示词 {len(bundle['prompts'])} 条 "
          f"-> {bundle_path} ({bundle_path.stat().st_size/1024:.0f} KB)")

    if args.no_upload:
        print("[INFO] --no-upload：只导出，未上传。")
        return 0
    folder_id = args.folder_id or default_folder_id()
    if not folder_id:
        print("[WARN] 找不到资料库文件夹 ID，跳过上传。", file=sys.stderr)
        print("[NEXT] 用 --folder-id <ID> 指定，或在 config/library-target.json 写好 folder_id。")
        return 0
    try:
        res = publish(bundle_path, dev, folder_id)
    except (RuntimeError, OSError, ValueError) as e:
        print(f"[WARN] 自动上传失败：{e}", file=sys.stderr)
        print("[NEXT] 导出文件已生成。请让 WorkBuddy Agent 用资料库能力把 "
              f"{bundle_path} 覆盖上传到文件夹 {folder_id} 的 {dev + SUFFIX} 节点。")
        return 0
    action = "新建" if res["created"] else "原地覆盖"
    print(f"[OK] 资料库{action}：节点 {res['node_id']}")
    print(f"     {res['url']}")
    print("[NEXT] 主设备会在下次轮询自动拉到这个包，无需人工干预。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
