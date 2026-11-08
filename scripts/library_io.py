#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / library_io.py

薄封装 WorkBuddy 资料库内置 Skill 脚本，供 publish_bundle.py / library_sync.py 共用。
不复制资料库实现，只按官方输出协议调用：

    KS_DRIVE_UPLOAD_OK <json>      drive/upload_drive_file.py
    KS_DRIVE_DOWNLOAD  <json>      drive/get_download_link.py
    space_api.py <api>              -> 纯 JSON

凭据由 WorkBuddy 注入的环境变量提供；在普通 CMD 里可能缺失，此时会给出明确提示。
可用 WORKBUDDY_LIBRARY_DIR / WORKBUDDY_PYTHON / WORKBUDDY_BUNDLE_FOLDER 覆盖探测结果。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SKILL_REL = "resources/plugins/workbuddy-builtin/skills/library"
_SPACE_API = "space_api.py"
_UPLOAD = "drive/upload_drive_file.py"
_DOWNLOAD = "drive/get_download_link.py"


def library_dir() -> Path | None:
    """找到内置 library Skill 目录。"""
    cands: list[Path] = []
    for key in ("WORKBUDDY_LIBRARY_DIR", "CODEBUDDY_SKILL_DIR"):
        v = os.environ.get(key, "").strip()
        if v:
            p = Path(v)
            cands += [p, p / "library"]

    res = os.environ.get("WORKBUDDY_RESOURCES_PATH", "").strip()
    if res:
        cands += [Path(res) / "app.asar.unpacked" / SKILL_REL, Path(res) / SKILL_REL]

    roots: list[Path] = []
    for drive in ("C:", "D:", "E:", "F:"):
        roots += [Path(f"{drive}/ProgramData/workbuddy/resources"),
                  Path(f"{drive}/Program Files/WorkBuddy/resources"),
                  Path(f"{drive}/Program Files (x86)/WorkBuddy/resources")]
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        roots.append(Path(local) / "Programs" / "WorkBuddy" / "resources")
    roots += [Path("/Applications/WorkBuddy.app/Contents/Resources"),
              Path("/opt/workbuddy/resources")]
    for r in roots:
        cands += [r / "app.asar.unpacked" / SKILL_REL, r / SKILL_REL]

    for p in cands:
        try:
            if (p / _SPACE_API).is_file():
                return p
        except OSError:
            continue
    return None


def python_exe() -> str:
    return os.environ.get("WORKBUDDY_PYTHON", "").strip() or sys.executable


def credential_hint() -> str:
    if os.environ.get("WORKBUDDY_CONFIG_DIR") or os.environ.get("X_IDE_IS_CLOUDSTUDIO"):
        return ""
    return ("未检测到 WorkBuddy 会话环境变量（WORKBUDDY_CONFIG_DIR）。"
            "请在 WorkBuddy 的自动化任务 / 会话里运行，或由 Agent 代为上传。")


def run(rel: str, *args: str) -> str:
    lib = library_dir()
    if lib is None:
        raise RuntimeError("找不到资料库内置脚本目录；请设置 WORKBUDDY_LIBRARY_DIR 指向 "
                           ".../workbuddy-builtin/skills/library")
    script = lib / rel
    if not script.is_file():
        raise RuntimeError(f"资料库脚本不存在：{script}")
    cmd = [python_exe(), str(script), *args]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and not out.strip():
        raise RuntimeError(f"调用失败（code={r.returncode}）：{' '.join(cmd)}")
    return out.strip()


def marker(out: str, key: str) -> dict:
    for line in out.splitlines():
        if line.startswith(key + "\t") or line.startswith(key + " "):
            return json.loads(line[len(key) + 1:].strip())
    raise RuntimeError(f"输出里缺少 {key}：{out[:300]}")


def api(command: str, **kwargs) -> dict:
    args = [command]
    for k, v in kwargs.items():
        if v is None or v == "":
            continue
        args += ["--" + k.replace("_", "-"), str(v)]
    out = run(_SPACE_API, *args)
    try:
        obj = json.loads(out)
    except ValueError as e:
        raise RuntimeError(f"资料库 API 返回的不是 JSON：{out[:300]}") from e
    if isinstance(obj, dict) and obj.get("error"):
        raise RuntimeError(f"资料库 API 错误：{obj['error']}")
    return obj.get("data", obj)


def list_folder(folder_id: str, space_id: str = "", limit: int = 100) -> list[dict]:
    data = api("space.workspace.list-nodes", space_id=space_id,
               parent_node_id=folder_id, limit=limit)
    return list(data.get("nodes", []) if isinstance(data, dict) else data)


def find_child(folder_id: str, title: str, space_id: str = "") -> str:
    """返回同名 drive 节点 ID；找不到返回空串。服务端标题会剥掉扩展名。"""
    for n in list_folder(folder_id, space_id):
        if n.get("kind") == "drive" and n.get("title") == title:
            return n.get("id", "")
    return ""


def upload(path: Path, file_name: str, parent_id: str = "", node_id: str = "") -> dict:
    """新建或原地覆盖；传 node_id 时保持节点 ID 与链接不变。"""
    args = [str(path), "--file-name", file_name]
    if node_id:
        args += ["--node-id", node_id]
    elif parent_id:
        args += ["--parent-id", parent_id]
    else:
        raise ValueError("新建时必须给 parent_id，覆盖时必须给 node_id")
    return marker(run(_UPLOAD, *args), "KS_DRIVE_UPLOAD_OK")


def download(node_id: str, timeout: float = 60.0) -> tuple[bytes, dict]:
    info = marker(run(_DOWNLOAD, "--node-id", node_id), "KS_DRIVE_DOWNLOAD")
    url = info.get("download_url")
    if not url:
        raise RuntimeError(f"没有下载链接：{info}")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read(), info
