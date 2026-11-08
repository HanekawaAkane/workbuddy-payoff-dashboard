#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / collect.py

从 WorkBuddy 本地数据中提取逐次模型调用的 token 与积分明细，输出紧凑 JSON。

数据源（全部只读）：
  1) <home>/projects/**/*.jsonl                 会话记录，providerData.rawUsage 含四段 token
  2) <home>/workbuddy.db  :: session_usage     credit_json 为官方逐「请求」积分账单
  3) <home>/workbuddy.db  :: sessions         会话标题 / 工作目录 / 创建时间
  4) config/pricing.json                       各厂商 API 牌价

关键口径：
  - 一条带 rawUsage 的记录 = 一次模型 API 调用（用 providerData.messageId 去重）。
  - providerData.conversationRequestId = 一次用户「请求」（一轮 Agent 循环可能含几十次 API 调用）。
  - credit_json 的 key（去掉连字符）就是 conversationRequestId，是官方账单口径，优先采用；
    缺失时回退到该轮所有调用 rawUsage.credit 之和，并标记 credit_src=0。
  - 四段 token：未命中输入 / 输出 / 缓存命中 / 缓存写入。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
SEGMENTS = ("input_miss", "output", "cache_hit", "cache_write")
KIND_MAP = {"function_call": 0, "message": 1, "reasoning": 2, "model-usage": 3}
KIND_LABELS = ["工具调用", "回复消息", "思考", "用量记录"]

SYS_REMINDER_RE = re.compile(r"<system-reminder\b.*?</system-reminder>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_prompt(text: str, limit: int = 140) -> str:
    if not text:
        return ""
    text = SYS_REMINDER_RE.sub("", text)
    text = re.sub(r"<user_query>|</user_query>", " ", text)
    text = TAG_RE.sub(" ", text)
    text = WS_RE.sub(" ", text).strip()
    return text[:limit]


def norm_id(s) -> str:
    return (s or "").replace("-", "").lower()


def is_peak(ts_ms: int) -> bool:
    d = datetime.fromtimestamp(ts_ms / 1000, CST)
    return d.weekday() < 5 and (9 <= d.hour < 12 or 14 <= d.hour < 18)


def segments(ru: dict) -> tuple[int, int, int, int]:
    """把不同版本的 rawUsage 归一到四段 token。"""
    hit = (ru.get("prompt_cache_hit_tokens") or 0) + (ru.get("cache_read_input_tokens") or 0)
    miss = ru.get("prompt_cache_miss_tokens")
    if not hit:
        hit = ((ru.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    prompt = ru.get("prompt_tokens") or 0
    if miss is None:
        miss = max(0, prompt - (hit or 0))
    out = ru.get("completion_tokens") or 0
    write = (ru.get("prompt_cache_write_tokens") or 0) + (ru.get("cache_creation_input_tokens") or 0)
    return int(hit or 0), int(miss or 0), int(out or 0), int(write or 0)


def price_for(model: str, peak: bool) -> list[float] | None:
    """返回 [未命中输入, 输出, 缓存命中, 缓存写入] 单价（元/百万 tokens）。"""
    cfg = PRICING["models"].get(model)
    if not cfg:
        return None
    if cfg.get("time_of_use"):
        p = cfg["peak"] if peak else cfg["offpeak"]
    else:
        p = cfg["price"]
    return [float(p[k]) for k in SEGMENTS]


def load_db(home: Path):
    db = home / "workbuddy.db"
    sessions, bills = {}, {}
    if not db.exists():
        return sessions, bills
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        for r in con.execute("SELECT id, title, custom_title, cwd, created_at, model FROM sessions"):
            sessions[r["id"]] = {
                "title": r["custom_title"] or r["title"] or "(未命名会话)",
                "cwd": r["cwd"] or "",
                "created_at": int(r["created_at"] or 0),
                "model": r["model"] or "",
            }
        for r in con.execute("SELECT session_id, credit_json FROM session_usage"):
            if r["credit_json"]:
                try:
                    bills[r["session_id"]] = {norm_id(k): float(v) for k, v in json.loads(r["credit_json"]).items()}
                except (ValueError, TypeError):
                    pass
    finally:
        con.close()
    return sessions, bills


def scan_jsonl(path: Path, bills: dict, with_prompts: bool):
    """产出 (calls, user_messages)。calls 里 reqid 已归一化。"""
    sid = path.stem
    calls, user_msgs, seen = [], [], set()
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(o, dict):
                continue
            ts = o.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            ts = int(ts)
            typ = o.get("type")
            if with_prompts and typ == "message" and o.get("role") == "user":
                parts = []
                for c in o.get("content") or []:
                    if isinstance(c, dict) and c.get("type") in ("input_text", "text"):
                        parts.append(c.get("text") or "")
                txt = clean_prompt(" ".join(parts))
                if txt:
                    user_msgs.append((ts, txt))
                continue
            pd = o.get("providerData") or {}
            ru = pd.get("rawUsage")
            if not isinstance(ru, dict):
                continue
            key = (sid, pd.get("messageId") or o.get("id"))
            if key in seen:
                continue
            seen.add(key)
            hit, miss, out, write = segments(ru)
            if hit + miss + out + write == 0:
                continue
            model = pd.get("model") or "unknown"
            reqid = norm_id(pd.get("conversationRequestId")) or norm_id(o.get("parentId")) or norm_id(o.get("id"))
            calls.append({
                "uid": f"{sid}:{pd.get('messageId') or o.get('id')}",
                "sid": sid, "reqid": reqid, "ts": ts, "model": model,
                "display": pd.get("requestModelName") or model,
                "hit": hit, "miss": miss, "out": out, "write": write,
                "credit": float(ru.get("credit") or 0),
                "kind": KIND_MAP.get(typ, 4),
                "is_peak": is_peak(ts),
            })
    return sid, calls, user_msgs


def least_squares(rows) -> list[float] | None:
    """rows: [(hit, miss, out, y)]，单位均为百万 tokens / 积分。"""
    n = 3
    A = [[0.0] * (n + 1) for _ in range(n)]
    for h, m, o, y in rows:
        v = (h, m, o)
        for i in range(n):
            for j in range(n):
                A[i][j] += v[i] * v[j]
            A[i][n] += v[i] * y
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(A[r][i]))
        A[i], A[piv] = A[piv], A[i]
        if abs(A[i][i]) < 1e-12:
            return None
        d = A[i][i]
        for j in range(i, n + 1):
            A[i][j] /= d
        for k in range(n):
            if k != i:
                f = A[k][i]
                for j in range(i, n + 1):
                    A[k][j] -= f * A[i][j]
    return [A[i][n] for i in range(n)]


def build(pricing: dict, calls: list, bills: dict, db_sessions: dict, with_prompts: bool, prompt_map: dict):
    global PRICING
    PRICING = pricing

    # 模型表
    model_ids, model_index = [], {}
    for c in calls:
        if c["model"] not in model_index:
            model_index[c["model"]] = len(model_ids)
            model_ids.append(c["model"])
    def mid(m):
        if m not in model_index:
            model_index[m] = len(model_ids)
            model_ids.append(m)
        return model_index[m]

    model_rows = []
    for m in model_ids:
        cfg = pricing["models"].get(m, {})
        off = price_for(m, False)
        pk = price_for(m, True) if cfg.get("time_of_use") else None
        model_rows.append([
            m, cfg.get("display", m), cfg.get("vendor", "未知"),
            bool(cfg.get("verified")), cfg.get("source_label", "未配置牌价"),
            cfg.get("note", ""), off, pk, bool(cfg.get("time_of_use")),
        ])

    # 会话表
    session_ids, session_index = [], {}
    for c in calls:
        if c["sid"] not in session_index:
            session_index[c["sid"]] = len(session_ids)
            session_ids.append(c["sid"])
    session_rows = []
    for s in session_ids:
        d = db_sessions.get(s, {})
        # 没有 workbuddy.db 时（纯日志 / 精简导出包）从 sid 前缀还原设备名
        dev = d.get("device") or (s.split("::", 1)[0] if "::" in s else "本机")
        session_rows.append([s, d.get("title", "(子会话 / 未登记)"), d.get("cwd", ""),
                             d.get("created_at", 0), dev])

    # 请求（turn）分组
    groups: dict[tuple[str, str], list] = {}
    for idx, c in enumerate(calls):
        groups.setdefault((c["sid"], c["reqid"]), []).append(idx)

    req_keys = sorted(groups, key=lambda k: min(calls[i]["ts"] for i in groups[k]))
    request_rows, call_rows = [], []
    req_call_rows: list[list[int]] = []
    total_tokens = covered_tokens = 0
    total_credit = total_cost = 0.0
    total_log_credit = 0.0
    min_ts, max_ts = None, None

    for rk in req_keys:
        idxs = groups[rk]
        sid, reqid = rk
        first_ts = min(calls[i]["ts"] for i in idxs)
        hit = sum(calls[i]["hit"] for i in idxs)
        miss = sum(calls[i]["miss"] for i in idxs)
        out = sum(calls[i]["out"] for i in idxs)
        write = sum(calls[i]["write"] for i in idxs)
        log_credit = sum(calls[i]["credit"] for i in idxs)
        cost = 0.0
        req_rows: list[int] = []
        for i in idxs:
            c = calls[i]
            p = price_for(c["model"], c["is_peak"])
            c_cost = 0.0
            if p:
                c_cost = (c["miss"] * p[0] + c["out"] * p[1] + c["hit"] * p[2] + c["write"] * p[3]) / 1e6
                covered_tokens += c["hit"] + c["miss"] + c["out"] + c["write"]
            total_tokens += c["hit"] + c["miss"] + c["out"] + c["write"]
            cost += c_cost
            total_cost += c_cost
            call_rows.append([
                len(request_rows), c["ts"], mid(c["model"]), c["hit"], c["miss"], c["out"], c["write"],
                round(c["credit"], 6), round(c_cost, 8), 1 if c["is_peak"] else 0, c["kind"], 0.0,
            ])
            req_rows.append(len(call_rows) - 1)
            min_ts = c["ts"] if min_ts is None else min(min_ts, c["ts"])
            max_ts = c["ts"] if max_ts is None else max(max_ts, c["ts"])

        bill = bills.get(sid, {}).get(reqid)
        if bill is None:
            credit, src = log_credit, 0
        else:
            credit, src = bill, 1
        total_log_credit += log_credit
        total_credit += credit
        # 把官方账单积分分摊回逐次调用，保证任意维度聚合的积分加总 == 账单总额
        if credit and req_rows:
            if log_credit > 0:
                for ri in req_rows:
                    call_rows[ri][11] = round(credit * call_rows[ri][7] / log_credit, 8)
            else:
                for ri in req_rows:
                    call_rows[ri][11] = round(credit / len(req_rows), 8)
        req_call_rows.append(req_rows)
        prompt = ""
        if with_prompts:
            for ts, txt in prompt_map.get(sid, []):
                if ts <= first_ts + 2000:
                    prompt = txt
                else:
                    break
        request_rows.append([
            session_index[sid], reqid, first_ts, hit, miss, out, write,
            round(credit, 6), round(cost, 8), len(idxs), src, prompt,
        ])

    meta = {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "range": [min_ts or 0, max_ts or 0],
        "n_calls": len(call_rows), "n_requests": len(request_rows), "n_sessions": len(session_rows),
        "n_models": len(model_rows),
        "total_tokens": total_tokens, "covered_tokens": covered_tokens,
        "total_credit": round(total_credit, 4), "total_log_credit": round(total_log_credit, 4),
        "total_api_cost": round(total_cost, 4),
        "bill_requests": sum(1 for r in request_rows if r[10] == 1),
        "prompt_included": with_prompts,
        "timezone": "Asia/Shanghai (UTC+8 fixed offset)",
    }
    return {
        "meta": meta,
        "schema": {
            "models": "[id, display, vendor, verified, sourceLabel, note, offpeak[4]|null, peak[4]|null, timeOfUse]",
            "sessions": "[sid, title, cwd, createdTs, device]",
            "requests": "[sessionIdx, reqId, ts, cacheHit, inputMiss, output, cacheWrite, officialCredit, apiCost, nCalls, creditSrc(1=bill 0=log), prompt]",
            "calls": "[reqIdx, ts, modelIdx, cacheHit, inputMiss, output, cacheWrite, logCredit, apiCost, peakFlag, kind, allocatedCredit]",
            "price_segments": "input_miss / output / cache_hit / cache_write, 单位 元每百万 tokens",
        },
        "pricing_notes": pricing["notes"],
        "price_unit": pricing["price_unit"],
        "models": model_rows,
        "sessions": session_rows,
        "requests": request_rows,
        "calls": call_rows,
        "kind_labels": KIND_LABELS + ["其他"],
    }


def source_signature(home: Path) -> float:
    """单个 WorkBuddy 目录的最新修改时间。"""
    return path_signature([home])


def path_signature(paths) -> float:
    """任意数据源（home 目录 / 便携包目录 / 单文件）的最新修改时间。"""
    latest = 0.0
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.exists():
                latest = max(latest, p.stat().st_mtime)
            continue
        if not p.is_dir():
            continue
        for name in ("workbuddy.db", "workbuddy.db-wal"):
            q = p / name
            if q.exists():
                latest = max(latest, q.stat().st_mtime)
        proj = p / "projects"
        if proj.exists():
            for q in proj.glob("**/*.jsonl"):
                try:
                    latest = max(latest, q.stat().st_mtime)
                except OSError:
                    pass
        for q in p.glob("*.json"):          # 便携包
            try:
                latest = max(latest, q.stat().st_mtime)
            except OSError:
                pass
    return latest


BUNDLE_SCHEMA = "wbtd-bundle/1"


def scan_home(home: Path, device: str, with_prompts: bool = True, since_ts: int | None = None):
    """扫描一个设备的 WorkBuddy 目录，返回归一化的 (calls, bills, sessions, prompts)。

    sid 统一加 "<device>::" 前缀，避免跨设备 UUID / 账单 key 串味。
    """
    if not home.exists():
        raise FileNotFoundError(f"设备数据目录不存在: {home}")
    raw_sessions, raw_bills = load_db(home)
    sessions = {f"{device}::{k}": {**v, "device": device} for k, v in raw_sessions.items()}
    bills = {f"{device}::{k}": v for k, v in raw_bills.items()}
    files = sorted((home / "projects").glob("**/*.jsonl"))
    if not files:
        raise FileNotFoundError(f"设备 {device} 未找到会话日志: {home / 'projects'}")
    calls, prompts = [], {}
    for p in files:
        sid, cs, ums = scan_jsonl(p, bills, with_prompts)
        psid = f"{device}::{sid}"
        if since_ts:
            cs = [c for c in cs if c["ts"] >= since_ts]
        for c in cs:
            c["sid"] = psid
            c["uid"] = f"{device}::{c.get('uid', psid)}"
        calls.extend(cs)
        if ums:
            prompts[psid] = sorted(ums)
    return device, calls, bills, sessions, prompts


def make_bundle(home: Path, device: str, with_prompts: bool = False) -> dict:
    """给一台设备生成可跨机搬运的便携包（默认不含提示词）。"""
    dev, calls, bills, sessions, prompts = scan_home(home, device, with_prompts)
    return {
        "schema": BUNDLE_SCHEMA, "device": dev,
        "exported_at": datetime.now(CST).isoformat(timespec="seconds"),
        "calls": calls, "bills": bills, "sessions": sessions,
        "prompts": {k: [list(x) for x in v] for k, v in (prompts if with_prompts else {}).items()},
    }


def bundle_from_sources(sources: list, device: str, with_prompts: bool = False) -> dict:
    """把一个节点（可能含多个源）导出成**单一设备名**的便携包，供别的节点拉取。

    所有 sid / uid / 账单 key 统一重写为 "<device>::"，避免对端拿到后设备名混乱。
    """
    out = {"schema": BUNDLE_SCHEMA, "device": device,
           "exported_at": datetime.now(CST).isoformat(timespec="seconds"),
           "calls": [], "bills": {}, "sessions": {}, "prompts": {}}
    seen = set()
    for s in sources:
        if s.get("bundle"):
            _, calls, bills, sessions, prompts = load_bundle(s["bundle"])
        else:
            _, calls, bills, sessions, prompts = scan_home(s["home"], s["device"], with_prompts)
        for raw in calls:
            u = _call_uid(raw)
            if u in seen:
                continue
            seen.add(u)
            c = dict(raw)
            stem = str(c["sid"]).split("::", 1)[-1]
            uid = str(c.get("uid", stem)).split("::", 1)[-1]
            c["sid"] = f"{device}::{stem}"
            c["uid"] = f"{device}::{uid}"
            out["calls"].append(c)
        for k, v in bills.items():
            out["bills"][f"{device}::{str(k).split('::', 1)[-1]}"] = v
        for k, v in sessions.items():
            out["sessions"][f"{device}::{str(k).split('::', 1)[-1]}"] = {**v, "device": device}
        if with_prompts:
            for k, v in prompts.items():
                out["prompts"][f"{device}::{str(k).split('::', 1)[-1]}"] = [list(x) for x in v]
    out["calls"].sort(key=lambda c: c["ts"])
    return out


def load_bundle(path: Path):
    """还原便携包，结构与 scan_home 输出一致。"""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("schema") != BUNDLE_SCHEMA:
        raise ValueError(f"不是受支持的便携包格式: {path}")
    dev = obj["device"]
    calls = obj["calls"]
    bills = obj["bills"]
    sessions = obj["sessions"]
    prompts = {k: [tuple(x) for x in v] for k, v in (obj.get("prompts") or {}).items()}
    # 兼容早期未加前缀的包
    for s in list(sessions):
        if not str(s).startswith(f"{dev}::"):
            sessions[f"{dev}::{s}"] = {**sessions.pop(s), "device": dev}
    for s in list(bills):
        if not str(s).startswith(f"{dev}::"):
            bills[f"{dev}::{s}"] = bills.pop(s)
    for c in calls:
        if not str(c["sid"]).startswith(f"{dev}::"):
            c["sid"] = f"{dev}::{c['sid']}"
        if not str(c.get("uid", "")).startswith(f"{dev}::"):
            c["uid"] = f"{dev}::{c.get('uid') or c['sid']}"
    return dev, calls, bills, sessions, prompts


def _call_uid(c: dict):
    return c.get("uid") or (c["sid"], c["reqid"], c["ts"], c["model"],
                            c["hit"], c["miss"], c["out"], c["write"])


def collect_from_sources(sources: list, config_path: Path,
                         with_prompts: bool = True, since_ts: int | None = None) -> dict:
    """汇总多个设备。

    sources: [{"device": 名称, "home": Path 或 None, "bundle": Path 或 None}, ...]
    便携包的设备名以包内 device 字段为准。跨源按调用唯一键去重，允许同一设备增量导出多次。
    """
    global PRICING
    pricing = json.loads(config_path.read_text(encoding="utf-8"))
    PRICING = pricing
    all_calls, all_bills, all_sessions, all_prompts = [], {}, {}, {}
    devices, seen = [], set()
    for s in sources:
        if s.get("bundle"):
            dev, calls, bills, sessions, prompts = load_bundle(s["bundle"])
        else:
            dev, calls, bills, sessions, prompts = scan_home(
                s["home"], s["device"], with_prompts, since_ts)
        devices.append(dev)
        for c in calls:
            if since_ts and c["ts"] < since_ts:
                continue
            u = _call_uid(c)
            if u in seen:
                continue
            seen.add(u)
            all_calls.append(c)
        all_bills.update(bills)
        all_sessions.update(sessions)
        all_prompts.update(prompts)
    if not all_calls:
        raise FileNotFoundError("所有数据源都没有可用记录")
    all_calls.sort(key=lambda c: c["ts"])
    data = build(pricing, all_calls, all_bills, all_sessions, with_prompts, all_prompts)
    data["meta"]["devices"] = sorted(set(devices))
    data["meta"]["multi_device"] = len(set(devices)) > 1
    return data


def collect_data(home: Path, config_path: Path, with_prompts: bool = True,
                 since_ts: int | None = None, device: str = "本机") -> dict:
    """单设备兼容入口。"""
    return collect_from_sources([{"device": device, "home": Path(home), "bundle": None}],
                               config_path, with_prompts, since_ts)


def resolve_sources(homes, sources_dirs, device: str = "", no_local: bool = False,
                    with_local: bool = False):
    """把 CLI 参数解析成 sources 列表。home 支持 "设备名=路径"。

    给了 --sources 又没显式 --home 时，默认不带本机：否则本机若也往同步盘
    导过包，同一批调用会因设备前缀不同被算两遍。要一起看用 --with-local。
    """
    out = []
    default_home = os.environ.get("WORKBUDDY_HOME") or str(Path.home() / ".workbuddy")
    skip_local = no_local or (bool(sources_dirs) and not homes and not with_local)
    specs = list(homes) if homes else ([] if skip_local else [default_home])
    for spec in specs:
        if "=" in spec and not spec[1:3] == ":\\":
            name, p = spec.split("=", 1)
        else:
            p = spec
            if device:
                name = device
            elif len(specs) == 1:
                name = "本机"           # 单设备沿用旧口径，不暴露用户名
            else:
                name = Path(spec).name
        if name in ("", ".workbuddy", "workbuddy"):
            name = Path(spec).parent.name or "本机"
        out.append({"device": name, "home": Path(p), "bundle": None})
    for d in sources_dirs:
        dp = Path(d)
        if not dp.exists():
            raise FileNotFoundError(f"便携包目录不存在: {dp}")
        for b in sorted(dp.glob("*.json")):
            out.append({"device": None, "home": None, "bundle": b})
    if not out:
        raise ValueError("没有指定任何数据源")
    return out


def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="采集 WorkBuddy 本地 / 多设备 token 与积分用量")
    ap.add_argument("--home", action="append", default=[],
                    help='设备数据目录，可重复；支持 "设备名=路径"。默认当前设备 ~/.workbuddy')
    ap.add_argument("--sources", action="append", default=[],
                    help="便携包目录，可重复；读取其中所有 *.json（由 export.py 生成）")
    ap.add_argument("--device", default="", help="单个 --home 时的设备名")
    ap.add_argument("--no-local", action="store_true", help="不采集本机，只用 --sources / 显式 --home")
    ap.add_argument("--with-local", action="store_true", help="用了 --sources 时也把本机一起算进来")
    ap.add_argument("--config", default=str(root / "config" / "pricing.json"))
    ap.add_argument("--out", default=str(root / "output" / "data.json"))
    ap.add_argument("--no-prompts", action="store_true", help="不写入用户提示词摘要（对外发布时用）")
    ap.add_argument("--since", default="", help="仅保留 YYYY-MM-DD 之后的调用")
    args = ap.parse_args(argv)

    since_ts = None
    if args.since:
        since_ts = int(datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=CST).timestamp() * 1000)
    try:
        sources = resolve_sources(args.home, args.sources, args.device,
                                  args.no_local, args.with_local)
        data = collect_from_sources(sources, Path(args.config), not args.no_prompts, since_ts)
    except (FileNotFoundError, ValueError) as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    m = data["meta"]
    print(f"[OK] 设备 {len(m['devices'])} 台：{', '.join(m['devices'])}")
    print(f"[OK] {m['n_calls']} 次 API 调用 / {m['n_requests']} 个请求 / {m['n_sessions']} 个会话 / {m['n_models']} 个模型")
    print(f"[OK] token {m['total_tokens']:,}（有牌价覆盖 {m['covered_tokens']:,}，{m['covered_tokens']/max(m['total_tokens'],1):.1%}）")
    print(f"[OK] 官方积分 {m['total_credit']:,.2f}（{m['bill_requests']}/{m['n_requests']} 个请求来自 credit_json 账单；逐调用日志累计 {m['total_log_credit']:,.2f}）")
    print(f"[OK] 同用量 API 直购价 ¥{m['total_api_cost']:,.2f}")
    print(f"[OK] -> {out}  ({out.stat().st_size/1024/1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
