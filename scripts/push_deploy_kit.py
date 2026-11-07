#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / push_deploy_kit.py

一键把「部署包」准备好、供发布到另一台设备（本机侧全自动，无第三方依赖）。

    python scripts/push_deploy_kit.py --peer-url http://192.168.1.23:8765 --peer-name 笔记本

流水线：
  1. 取/生成 32 字节随机共享密钥。它只用于本项目节点间 /api/bundle 鉴权，
     是新生成的随机串，不是任何账号凭据，也不从 WorkBuddy 目录读取任何东西。
     --token 可显式指定（例如对端已经配好了某个值），但公开渠道拿到的值不要复用。
  2. 写 config/peers.json（已被 .gitignore 排除，且不会被打进部署包）。
  3. build_deploy_kit.py      -> output/workbuddy-token-exporter.zip
  4. build_download_page.py   -> output/deploy-kit-download.html（ZIP 内嵌 + SHA-256）
  5. 安全自检：包内不含本机数据 / 密钥 / .workbuddy；下载页不含密钥字节；
     命令文本引用的每个脚本都确实存在于 ZIP 里；页面内嵌 ZIP 与本地逐字节一致。
  6. 写 output/START-NODE-COMMAND.txt（含密钥，仅本地保存）
     写 output/publish-manifest.json（路径 / sha256 / 密钥指纹，不含密钥本身）

上传这一步脚本自己做不了（资料库上传是 Agent 侧通道）。脚本只把待上传的
HTML 准备好并打印绝对路径，由 Agent 用 LibraryUpload 上传，或用户自行上传。

  * 只传 .html，别直接传 .zip：资料库对 .zip 只建空壳网页节点（无文件字节）。
  * output/START-NODE-COMMAND.txt 含密钥，不要上传、不要发链接、不要提交仓库。
  * 密钥走「带外」：本机生成 -> 你在另一台设备手动敲进 START-NODE.bat。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))
SCRIPTS = ROOT / "scripts"
OUT = ROOT / "output"
ZIP_PATH = OUT / "workbuddy-token-exporter.zip"
PAGE_PATH = OUT / "deploy-kit-download.html"
CMD_PATH = OUT / "START-NODE-COMMAND.txt"
MANIFEST_PATH = OUT / "publish-manifest.json"
PEERS_PATH = ROOT / "config" / "peers.json"

# 部署包里绝不允许出现的目录 / 文件
FORBIDDEN_PARTS = {"output", ".workbuddy", ".git", "__pycache__"}
FORBIDDEN_NAMES = {
    "peers.json", "peers.demo.json", "settings.local.json",
    "credentials.json", ".env", "publish-manifest.json",
    "START-NODE-COMMAND.txt",
}
PLACEHOLDER_TOKENS = {"change-me", "change-me-to-a-long-random-string", ""}
# 命令文本里会引用到的文件，必须在 ZIP 里真实存在（否则另一台设备执行必失败）
REQUIRED_IN_ZIP = (
    "deploy/START-NODE.bat",
    "deploy/EXPORT.bat",
    "scripts/serve.py",
    "scripts/peers.py",
    "scripts/keep_online.py",
    "scripts/export.py",
    "config/pricing.json",
)


def load_or_create_token(rotate: bool, explicit: str) -> tuple[str, str]:
    """返回 (token, 来源)。已有可用密钥默认复用，避免对端突然失效。"""
    if explicit:
        return explicit, "由 --token 显式指定（请确认来源可信、未在公开渠道流传）"
    if PEERS_PATH.exists() and not rotate:
        try:
            old = json.loads(PEERS_PATH.read_text(encoding="utf-8")).get("token", "")
        except (OSError, ValueError, AttributeError):
            old = ""
        if old and old not in PLACEHOLDER_TOKENS:
            return old, "复用 config/peers.json 中已有的共享密钥"
    return secrets.token_urlsafe(32), "新生成（secrets.token_urlsafe(32)）"


def write_peers_config(token: str, peer_url: str, peer_name: str, rotate: bool) -> dict:
    """保留用户已有的对端清单，只更新密钥并按名字 upsert 新对端。"""
    cfg: dict = {}
    if PEERS_PATH.exists():
        try:
            cfg = json.loads(PEERS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    cfg["_readme"] = [
        "由 push_deploy_kit.py 生成。polling 只拉取 enabled=true 的对端。",
        "url 指向对端 serve.py；同网填局域网 IP，异地用 Tailscale / ZeroTier 虚拟 IP。",
        "token 必须与对端 serve.py --token 一致。不要把节点服务直接暴露到公网。",
        "本文件含密钥，已在 .gitignore 中，且不会打进部署包。",
    ]
    cfg["poll_seconds"] = int(cfg.get("poll_seconds", 60) or 60)
    cfg["token"] = token
    peers = [p for p in cfg.get("peers", []) if isinstance(p, dict)] if isinstance(cfg.get("peers"), list) else []
    if peer_url:
        peers = [p for p in peers if p.get("name") != peer_name]
        peers.append({"name": peer_name, "url": peer_url.rstrip("/"), "enabled": True})
        if rotate:
            # 轮换密钥后，清掉可能残留的单台覆盖密钥
            for p in peers:
                p.pop("token", None)
    cfg["peers"] = peers
    PEERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PEERS_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cfg


def run_builder(script: str, *extra: str) -> None:
    cmd = [sys.executable, str(SCRIPTS / script), *extra]
    print("[RUN] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(ROOT), check=True, capture_output=False)


def audit_package(token: str, cmd_text: str, zip_bytes: bytes, page_bytes: bytes) -> list[str]:
    """确保跨设备的 ZIP 和下载页不含本机私有数据与密钥，且命令引用的脚本都在包里。"""
    problems: list[str] = []
    with zipfile.ZipFile(ZIP_PATH) as z:
        names = z.namelist()
        for rel in REQUIRED_IN_ZIP:
            if f"workbuddy-token-exporter/{rel}" not in names:
                problems.append(f"部署包缺少命令会用到的文件：{rel}")
        for name in names:
            rel = name.split("/", 1)[1] if "/" in name else name
            parts = [p for p in rel.split("/") if p]
            if not parts:
                continue
            if any(p in FORBIDDEN_PARTS for p in parts):
                problems.append(f"部署包含本机私有目录：{rel}")
            if parts[-1] in FORBIDDEN_NAMES:
                problems.append(f"部署包含含密钥/本机配置的文件：{rel}")
            if name.endswith("/"):
                continue
            if token.encode("utf-8") in z.read(name):
                problems.append(f"部署包文件里出现共享密钥：{rel}")
    if token.encode("utf-8") in page_bytes:
        problems.append("下载页 HTML 里出现共享密钥（页面要上传资料库，不能带密钥）")

    # 命令文本里提到的 bat / py，必须在包里
    referenced = set(re.findall(r"(?:scripts|deploy)\\[A-Za-z0-9_.-]+\.(?:py|bat)", cmd_text))
    packaged = {n.split("/", 1)[1].replace("/", "\\") for n in zipfile.ZipFile(ZIP_PATH).namelist() if "/" in n}
    for ref in referenced:
        if ref not in packaged:
            problems.append(f"命令引用了包里不存在的文件：{ref}")

    # 下载页内嵌的 ZIP 必须与本地 ZIP 逐字节一致
    m = re.search(rb'var B64="([A-Za-z0-9+/=]+)"', page_bytes)
    if not m:
        problems.append("下载页里找不到内嵌的 ZIP base64")
    else:
        embedded = base64.b64decode(m.group(1))
        if embedded != zip_bytes:
            problems.append("下载页内嵌的 ZIP 与本地 ZIP 不一致（重新跑 build_download_page.py）")
    return sorted(set(problems))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="一键生成并准备发布另一台设备用的部署包")
    ap.add_argument("--peer-url", default="",
                    help="对端节点地址，如 http://192.168.1.23:8765；不知道可以留空，之后手填 peers.json")
    ap.add_argument("--peer-name", default="peer-device", help="对端显示名（仅本机看板用）")
    ap.add_argument("--port", type=int, default=8765, help="对端节点监听端口")
    ap.add_argument("--token", default="", help="显式指定共享密钥；默认复用/新生成。公开渠道拿到的值别用")
    ap.add_argument("--rotate-token", action="store_true", help="强制换一个新密钥（对端也要同步换）")
    args = ap.parse_args(argv)

    if args.peer_url and not args.peer_url.startswith(("http://", "https://")):
        print("[FATAL] --peer-url 要以 http:// 或 https:// 开头。", file=sys.stderr)
        return 2
    if args.token and (args.token in PLACEHOLDER_TOKENS or len(args.token) < 16):
        print("[FATAL] --token 太短或仍是占位符。", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    token, origin = load_or_create_token(args.rotate_token, args.token)
    cfg = write_peers_config(token, args.peer_url, args.peer_name, args.rotate_token)

    print(f"[1/6] 共享密钥：{origin}")
    print(f"      TOKEN = {token}")
    if args.token:
        print("      [注意] 这是显式指定的值。若它曾在聊天/网页/邮件里出现过，请改用 --rotate-token 重新生成。")
    run_builder("build_deploy_kit.py")                       # 2
    run_builder("build_download_page.py")                   # 3
    zip_bytes, page_bytes = ZIP_PATH.read_bytes(), PAGE_PATH.read_bytes()
    print(f"[2/6] {ZIP_PATH.name}  {len(zip_bytes)/1024:.0f} KB")
    print(f"[3/6] {PAGE_PATH.name}  {len(page_bytes)/1024:.0f} KB")

    dev_hint = "%COMPUTERNAME%"
    cmd_text = "\n".join([
        "在【另一台设备】上：",
        "  1) 打开资料库里的「WorkBuddy部署包-点此下载ZIP」页面，点按钮下载 ZIP，解压。",
        "  2) 打开命令行，cd 到解压出来的 workbuddy-token-exporter 目录：",
        r"       cd /d D:\path\to\workbuddy-token-exporter",
        "  3) 先一次性试跑，确认能起来（Ctrl+C 结束）：",
        "",
        f"       deploy\\START-NODE.bat {token} {args.port} {dev_hint}",
        "",
        "  4) 确认无误后改常驻版（进程意外退出会自动重启，Ctrl+C 才真正结束）：",
        "",
        f"       python scripts\\keep_online.py --mode node --token {token} --port {args.port} --device {dev_hint}",
        "",
        "【本机】汇总端常驻（只绑 127.0.0.1，按 config/peers.json 定时拉对端）：",
        "",
        r"       cd /d D:\workbuddy\workbuddy-token-dashboard",
        "       python scripts\\keep_online.py --mode main",
        "",
        "       看板：http://127.0.0.1:8765/",
        "",
        "前提：把对端的真实 IP 填进 config/peers.json 的 peers[].url",
        "      （同网填局域网 IP，异地填 Tailscale / ZeroTier 虚拟 IP）。",
        "",
        "-" * 70,
        "本文件含共享密钥：不要上传资料库、不要发链接、不要提交仓库。",
        "密钥只用于两台设备之间 /api/bundle 的鉴权，不是账号凭据。",
        "不要把 8765 端口映射到公网。",
        f"生成时间：{datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S %z')}",
        "",
    ])

    problems = audit_package(token, cmd_text, zip_bytes, page_bytes)   # 4
    if problems:
        for p in problems:
            print(f"[FATAL] {p}", file=sys.stderr)
        print("[ABORT] 产物已生成但自检未通过，请不要上传。", file=sys.stderr)
        return 3
    print("[4/6] 安全自检通过：无本机数据 / 无密钥 / 命令引用文件齐全 / 页面内嵌 ZIP 逐字节一致。")

    CMD_PATH.write_text(cmd_text, encoding="utf-8")          # 5

    manifest = {                                            # 6
        "generated_at": datetime.now(CST).isoformat(),
        "upload_this_file": str(PAGE_PATH),
        "upload_note": "只上传这个 .html；资料库对 .zip 只建空壳节点。",
        "do_not_upload": [str(CMD_PATH), str(PEERS_PATH), str(ZIP_PATH)],
        "zip": {"path": str(ZIP_PATH), "bytes": len(zip_bytes), "sha256": sha256(zip_bytes)},
        "page": {"path": str(PAGE_PATH), "bytes": len(page_bytes), "sha256": sha256(page_bytes)},
        "token_fingerprint": hashlib.sha256(token.encode("utf-8")).hexdigest()[:12],
        "token_origin": origin,
        "token_stored_in": [str(PEERS_PATH), str(CMD_PATH)],
        "peer_count": len(cfg.get("peers", [])),
        "peer_url_configured": bool(args.peer_url),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[5/6] 对端命令：{CMD_PATH}")
    print(f"[6/6] 发布清单：{MANIFEST_PATH}")

    print("\n" + "=" * 70)
    print("下一步（上传这一步脚本做不了，要走资料库通道）：")
    print(f"  上传文件：{PAGE_PATH}")
    print("  在另一台设备打开该页面 -> 点「下载部署包 ZIP」-> 解压 -> 执行 START-NODE-COMMAND.txt 里的命令。")
    if not args.peer_url:
        print("  [提醒] 没给 --peer-url：拿到对端 IP 后填进 config/peers.json 的 peers[].url。")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
