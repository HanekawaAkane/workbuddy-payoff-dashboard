#!/usr/bin/env python3
"""把 CodeBuddy 本地插件日志里的用量，转成看板可直接读取的便携包。

CodeBuddy 不写 WorkBuddy 那种 JSONL 会话，用量散在 IDE 扩展日志里：
    [2026/10/28 15:49:17.287] [Info] [BaseAgent:craft] [reqid] notifyStepEnd,
        step: 1, requestId: ..., messageId: ..., usage: {"inputTokens":..,
        "outputTokens":..,"cacheTokens":..,"cachedMissTokens":..,
        "cachedWriteTokens":..,"credit":..}

本脚本只提取数字（四段 token + credit），不读取提示词、代码或文件内容。
产出结构对齐 WorkBuddy 便携包，因此可以直接:
    python scripts/collect_codebuddy.py
    python scripts/run.py --sources output/bundles --with-local
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
BUNDLE_SCHEMA = "wbtd-bundle/1"

TS_BRACKET = re.compile(r"^\[(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3})\]")
TS_PLAIN = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3})")
STEP_END = re.compile(
    r"notifyStepEnd, step: (\d+), requestId: (\w+), messageId: (\w+), usage: (\{.*?\})")
MODEL_ANY = re.compile(r"modelId[=:]\s*([\w.\-]+)")
CWD_LINE = re.compile(r"cwd[=:]\s*([a-zA-Z]:[/\\][^\s,)\]]+)")


def default_roots() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    roaming = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    return [Path(local) / "CodeBuddyExtension" / "Logs",
            Path(roaming) / "CodeBuddy CN" / "logs"]


def parse_ts(line: str):
    m = TS_BRACKET.match(line) or TS_PLAIN.match(line)
    if not m:
        return None
    y, mo, d, h, mi, s, ms = (int(x) for x in m.groups())
    try:
        return int(datetime(y, mo, d, h, mi, s, ms * 1000, tzinfo=CST).timestamp() * 1000)
    except ValueError:
        return None


def scan_log(path: Path, seen: set, calls: list, model_map: dict, cwds: dict):
    """扫单个日志：产出调用，并按「最近一次 modelId 初始化」绑定模型。"""
    stem = path.stem
    session = stem.split("__", 1)[0] or stem
    try:
        fh = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    current_model = ""
    with fh:
        for line in fh:
            ts = parse_ts(line)
            if ts is None:
                continue
            if session not in cwds:
                m = CWD_LINE.search(line)
                if m:
                    cwds[session] = m.group(1)
            if "modelId" in line:
                m = MODEL_ANY.search(line)
                if m:
                    current_model = m.group(1).strip().lower()
                continue
            if "notifyStepEnd" not in line:
                continue
            m = STEP_END.search(line)
            if not m:
                continue
            step, reqid, msgid, raw = m.group(1), m.group(2), m.group(3), m.group(4)
            key = (reqid, msgid)
            if key in seen:
                continue
            try:
                u = json.loads(raw)
            except ValueError:
                continue
            seen.add(key)
            if current_model:
                model_map[(reqid, int(step))] = current_model
            calls.append({
                "uid": f"{session}:{msgid}",
                "sid": session,
                "reqid": reqid,
                "ts": ts,
                "step": int(step),
                "model": "",            # 稍后回填
                "display": "",
                "hit": int(u.get("cacheTokens") or 0),
                "miss": int(u.get("cachedMissTokens") or 0),
                "out": int(u.get("outputTokens") or 0),
                "write": int(u.get("cachedWriteTokens") or 0),
                "credit": float(u.get("credit") or 0),
                "kind": 0,
                "is_peak": False,
            })


DISPLAY_NAMES = {
    "hy3": "Hy3",
    "hy3-x": "Hy3-X",
    "hy4-preview": "Hy4 preview",
    "deepseek-v4.1-flash": "DeepSeek-V4.1-Flash",
    "deepseek-v4-pro": "DeepSeek-V4-Pro",
    "glm-5.3": "GLM-5.3",
    "glm-5.3-flash": "GLM-5.3-Flash",
    "glm-5.3-flashx": "GLM-5.3-FlashX",
    "kimi-k3.1-pro": "Kimi-K3.1-Pro",
    "kimi-k3-1": "Kimi-K3",
    "auto": "Auto（未记录具体模型）",
}


def fill_models(calls: list, model_map: dict):
    """优先用同 (requestId, step) 的记录，其次同请求其它 step，最后标 auto。"""
    by_req: dict[str, list] = {}
    for c in calls:
        by_req.setdefault(c["reqid"], []).append(c)
    for c in calls:
        name = model_map.get((c["reqid"], c["step"]), "")
        if not name:
            for peer in by_req.get(c["reqid"], []):
                if peer.get("model"):
                    name = peer["model"]
                    break
        c["model"] = name or "auto"
        c["display"] = DISPLAY_NAMES.get(c["model"], c["model"])


def build_bundle(roots: list[Path], device: str = "CodeBuddy") -> dict:
    seen: set = set()
    calls: list = []
    model_map: dict = {}
    cwds: dict = {}
    files = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.log"):
            try:
                if path.stat().st_size == 0:
                    continue
            except OSError:
                continue
            files += 1
            scan_log(path, seen, calls, model_map, cwds)
    if not calls:
        raise FileNotFoundError("没有在 CodeBuddy 日志里找到 usage 记录")
    fill_models(calls, model_map)
    calls.sort(key=lambda c: c["ts"])

    sessions: dict = {}
    bills: dict = {}
    for c in calls:
        sid = c["sid"]
        if sid not in sessions:
            sessions[sid] = {
                "title": f"CodeBuddy · {sid}",
                "cwd": cwds.get(sid, ""),
                "created_at": c["ts"],
                "device": device,
            }
        bills.setdefault(sid, {})
        bills[sid][c["reqid"]] = round(bills[sid].get(c["reqid"], 0.0) + c["credit"], 6)

    for c in calls:
        c.pop("step", None)
    return {
        "schema": BUNDLE_SCHEMA,
        "device": device,
        "exported_at": datetime.now(CST).isoformat(timespec="seconds"),
        "calls": calls,
        "bills": bills,
        "sessions": sessions,
        "prompts": {},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="把 CodeBuddy 日志用量转成看板便携包")
    ap.add_argument("--log-root", action="append", default=[],
                    help="CodeBuddy 日志根目录，可重复；默认两处标准位置")
    ap.add_argument("--out", default="", help="输出路径，默认 output/codebuddy/CodeBuddy.json")
    ap.add_argument("--device", default="CodeBuddy", help="看板里显示的设备名")
    args = ap.parse_args(argv)

    roots = [Path(p) for p in args.log_root] if args.log_root else default_roots()
    root_dir = Path(__file__).resolve().parent.parent
    out = Path(args.out) if args.out else root_dir / "output" / "codebuddy" / "CodeBuddy.json"
    try:
        bundle = build_bundle(roots, args.device)
    except FileNotFoundError as e:
        print(f"[SKIP] {e}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    calls = bundle["calls"]
    credit = sum(c["credit"] for c in calls)
    tokens = sum(c["hit"] + c["miss"] + c["out"] + c["write"] for c in calls)
    first = datetime.fromtimestamp(calls[0]["ts"] / 1000, CST).strftime("%Y-%m-%d")
    last = datetime.fromtimestamp(calls[-1]["ts"] / 1000, CST).strftime("%Y-%m-%d")
    print(f"[OK] {len(calls)} 次调用 · {tokens:,} token · 积分 {credit:,.2f} · {first} ~ {last}")
    print(f"[OK] -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
