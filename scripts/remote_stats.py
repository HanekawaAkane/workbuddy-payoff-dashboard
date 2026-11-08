#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workbuddy-token-dashboard / remote_stats.py

统计【资料库同步过来的远端设备】token 用量。与看板共用 collect.py 的口径，
不另算一套：四段 token、官方分摊积分、API 直购价、套餐单价全部一致。

    python scripts/remote_stats.py                       # 读 output/bundles/*.json
    python scripts/remote_stats.py --refresh            # 先从资料库拉最新包再统计
    python scripts/remote_stats.py --with-local         # 连本机一起统计
    python scripts/remote_stats.py --json output/remote-stats.json
    python scripts/remote_stats.py --csv  output/remote-stats.csv

默认只统计资料库包（--no-local 语义）。便携包不含提示词；本脚本也不读取提示词。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402

CST = timezone(timedelta(hours=8))
# calls 行：[reqIdx, ts, modelIdx, hit, miss, out, write, logCredit, apiCost, peak, kind, allocCredit]
C_REQ, C_TS, C_MODEL, C_HIT, C_MISS, C_OUT, C_WRITE = 0, 1, 2, 3, 4, 5, 6
C_LOGCR, C_COST, C_PEAK, C_KIND, C_ALLOC = 7, 8, 9, 10, 11
# requests 行：[sessionIdx, ...]；sessions 行：[sid, title, cwd, createdTs, device]
R_SID, S_DEVICE = 0, 4


def stamp(ts: int, fmt: str = "%Y-%m-%d") -> str:
    return datetime.fromtimestamp(ts / 1000, CST).strftime(fmt)


def discover(out_dir: Path) -> list[Path]:
    return sorted(p for p in out_dir.glob("*.json") if p.is_file())


def build_sources(bundles: list[Path], with_local: bool, home: Path) -> list[dict]:
    srcs = [{"device": "", "home": None, "bundle": p} for p in bundles]
    if with_local:
        srcs.append({"device": "本机", "home": home, "bundle": None})
    return srcs


def overlap_warning(bundles: list[Path], home: Path) -> str:
    """去掉设备前缀后比对 uid，防止把同一台机器的重复导出当成两台设备。"""
    if not home.exists() or not bundles:
        return ""
    try:
        _, local, _, _, _ = collect.scan_home(home, "本机", False)
    except Exception:  # noqa: BLE001
        return ""
    norm = lambda s: str(s).split("::", 1)[-1]  # noqa: E731
    luid = {norm(c.get("uid")) for c in local}
    dup = total = 0
    for p in bundles:
        try:
            _, rc, _, _, _ = collect.load_bundle(p)
        except Exception:  # noqa: BLE001
            continue
        ruid = {norm(c.get("uid")) for c in rc}
        total += len(ruid)
        dup += len(ruid & luid)
    if not total:
        return ""
    pct = dup / total
    if pct > 0.5:
        return (f"⚠ 与本机数据重合 {dup:,}/{total:,}（{pct:.1%}）——"
                "这些包很可能就是本机导出的，合并会双计，请勿据此下结论。")
    return f"与本机 uid 重合 {dup:,}/{total:,}（{pct:.1%}），可视为独立设备数据。"


def compute(data: dict) -> dict:
    models, calls, requests, sessions = (data["models"], data["calls"],
                                        data["requests"], data["sessions"])

    def bucket():
        return {"calls": 0, "hit": 0, "miss": 0, "out": 0, "write": 0,
                "credit": 0.0, "api_cost": 0.0, "peak": 0}

    def add(b, row):
        b["calls"] += 1
        b["hit"] += row[C_HIT]; b["miss"] += row[C_MISS]
        b["out"] += row[C_OUT]; b["write"] += row[C_WRITE]
        b["credit"] += row[C_ALLOC]; b["api_cost"] += row[C_COST]
        b["peak"] += 1 if row[C_PEAK] else 0

    per_dev, per_model, per_day = defaultdict(bucket), defaultdict(bucket), defaultdict(bucket)
    for row in calls:
        try:
            dev = sessions[requests[row[C_REQ]][R_SID]][S_DEVICE]
        except (IndexError, TypeError):
            dev = "?"
        mname = models[row[C_MODEL]][1] if row[C_MODEL] < len(models) else "?"
        add(per_dev[dev], row)
        add(per_model[mname], row)
        add(per_day[stamp(row[C_TS])], row)

    plans = {p["id"]: p for p in data["plans"]}
    plan = plans.get(data["default_plan"], {})
    per_credit = (plan.get("monthly_price", 0) / plan.get("credits", 1)) if plan else 0.0

    def finish(b):
        b["tokens"] = b["hit"] + b["miss"] + b["out"] + b["write"]
        b["in_cost"] = b["credit"] * per_credit
        for k in ("credit", "api_cost", "in_cost"):
            b[k] = round(b[k], 4)
        return b

    m = data["meta"]
    return {
        "generated_at": m["generated_at"],
        "source_devices": sorted(per_dev),
        "range": [stamp(m["range"][0], "%Y-%m-%d %H:%M"), stamp(m["range"][1], "%Y-%m-%d %H:%M")],
        "plan": {"id": plan.get("id"), "name": plan.get("name"),
                 "monthly_price": plan.get("monthly_price"), "credits": plan.get("credits"),
                 "per_credit": round(per_credit, 8)},
        "totals": finish({
            "calls": m["n_calls"], "hit": sum(b["hit"] for b in per_dev.values()),
            "miss": sum(b["miss"] for b in per_dev.values()),
            "out": sum(b["out"] for b in per_dev.values()),
            "write": sum(b["write"] for b in per_dev.values()),
            "credit": m["total_credit"], "api_cost": m["total_api_cost"],
            "peak": sum(b["peak"] for b in per_dev.values()), "in_cost": m["total_credit"] * per_credit,
        }),
        "per_device": {k: finish(v) for k, v in sorted(per_dev.items())},
        "per_model": dict(sorted(((k, finish(v)) for k, v in per_model.items()),
                                 key=lambda kv: -kv[1]["tokens"])),
        "per_day": {k: finish(v) for k, v in sorted(per_day.items())},
        "coverage": {"tokens": m["total_tokens"], "covered": m["covered_tokens"],
                     "ratio": round(m["covered_tokens"] / max(m["total_tokens"], 1), 4)},
        "n_sessions": m["n_sessions"], "n_requests": m["n_requests"],
        "n_models": m["n_models"],
    }


def print_report(st: dict, bundles: list[Path], warning: str) -> None:
    n = lambda v: f"{v:,}"  # noqa: E731

    def row(cells, widths, first_left=True):
        out = []
        for i, (c, w) in enumerate(zip(cells, widths)):
            s = str(c)
            out.append(s.ljust(w) if (i == 0 and first_left) else s.rjust(w))
        return " ".join(out)

    t = st["totals"]
    print("=" * 78)
    print("资料库远端 Token 统计  ·  " + st["generated_at"])
    print("=" * 78)
    print(f"数据源：{len(bundles)} 个便携包 | 设备：{', '.join(st['source_devices'])}")
    print(f"时间范围：{st['range'][0]}  ~  {st['range'][1]}（北京时间）")
    print(f"会话 {st['n_sessions']} / 请求 {st['n_requests']} / 模型 {st['n_models']}")
    print(f"套餐：{st['plan']['name']}  ¥{st['plan']['monthly_price']}/"
          f"{n(st['plan']['credits'])} 积分 = ¥{st['plan']['per_credit']:.5f}/积分")
    print(f"牌价覆盖率：{st['coverage']['ratio']:.1%}")
    if warning:
        print(warning)

    W = [14, 8, 15, 14, 13, 10, 16, 11, 10, 11]
    hdr = ("设备", "调用", "缓存命中", "未命中输入", "输出", "缓存写入", "总Token", "积分", "平台内¥", "API直购¥")
    print("\n" + "-" * 118)
    print(row(hdr, W))
    print("-" * 118)
    for dev, b in st["per_device"].items():
        print(row((dev[:13], n(b["calls"]), n(b["hit"]), n(b["miss"]), n(b["out"]),
                   n(b["write"]), n(b["tokens"]), f"{b['credit']:,.2f}",
                   f"{b['in_cost']:,.2f}", f"{b['api_cost']:,.2f}"), W))
    print("-" * 118)
    print(row(("合计", n(t["calls"]), n(t["hit"]), n(t["miss"]), n(t["out"]),
               n(t["write"]), n(t["tokens"]), f"{t['credit']:,.2f}",
               f"{t['in_cost']:,.2f}", f"{t['api_cost']:,.2f}"), W))
    ratio = t["api_cost"] / max(t["in_cost"], 1e-9)
    print(f"\n平台外/平台内 = {ratio:.2f}×（同用量 API 直购价 ÷ 积分折算）")
    print(f"峰时调用 {n(t['peak'])} 次，占 {t['peak']/max(t['calls'],1):.1%}")

    W3 = [28, 8, 16, 11, 12]
    print("\n模型 TOP 8（按 Token）")
    print(row(("模型", "调用", "总Token", "积分", "API直购¥"), W3))
    for k, b in list(st["per_model"].items())[:8]:
        print(row((k[:27], n(b["calls"]), n(b["tokens"]), f"{b['credit']:,.2f}",
                   f"{b['api_cost']:,.2f}"), W3))

    print("\n最近 10 天（按 Token）")
    print(row(("日期", "调用", "总Token", "积分", "API直购¥"), W3))
    for k, b in list(st["per_day"].items())[-10:]:
        print(row((k, n(b["calls"]), n(b["tokens"]), f"{b['credit']:,.2f}",
                   f"{b['api_cost']:,.2f}"), W3))
    print()


def write_csv(st: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["scope", "name", "calls", "cache_hit", "input_miss", "output", "cache_write",
              "total_tokens", "official_credit", "in_platform_cny", "api_direct_cny", "peak_calls"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for scope, mapping in (("device", st["per_device"]), ("model", st["per_model"]),
                              ("day", st["per_day"])):
            for name, b in mapping.items():
                w.writerow([scope, name, b["calls"], b["hit"], b["miss"], b["out"], b["write"],
                            b["tokens"], b["credit"], b["in_cost"], b["api_cost"], b["peak"]])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="统计资料库同步过来的远端设备 token 用量")
    ap.add_argument("--bundles", default=str(ROOT / "output" / "bundles"))
    ap.add_argument("--config", default=str(ROOT / "config" / "library-sync.json"))
    ap.add_argument("--pricing", default=str(ROOT / "config" / "pricing.json"))
    ap.add_argument("--home", default=os.environ.get("WORKBUDDY_HOME")
                    or str(Path.home() / ".workbuddy"))
    ap.add_argument("--refresh", action="store_true", help="先调用 library_sync 从资料库拉最新包")
    ap.add_argument("--with-local", action="store_true", help="把本机数据也统计进来")
    ap.add_argument("--json", default="", help="导出结构化 JSON")
    ap.add_argument("--csv", default="", help="导出逐设备/模型/日期 CSV")
    ap.add_argument("--no-overlap-check", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.bundles)
    if args.refresh:
        import library_sync  # noqa: PLC0415
        try:
            cfg = library_sync.load_config(Path(args.config))
            lib_out = ROOT / cfg.get("out_dir", "output/bundles")
            written = library_sync.sync_once(cfg, lib_out)
            print(f"[REFRESH] 资料库同步完成，写入 {len(written)} 个包 -> {lib_out}")
            out_dir = lib_out
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 资料库刷新失败，改用本地已有包：{type(e).__name__}: {e}",
                  file=sys.stderr)

    bundles = discover(out_dir)
    if not bundles and not args.with_local:
        print(f"[FATAL] {out_dir} 里没有便携包。先跑 python scripts/library_sync.py --once "
              "或加 --refresh。", file=sys.stderr)
        return 2
    home = Path(args.home)
    srcs = build_sources(bundles, args.with_local, home)
    try:
        data = collect.collect_from_sources(srcs, Path(args.pricing), False)
    except (FileNotFoundError, ValueError) as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 2

    st = compute(data)
    st["bundles"] = [str(p) for p in bundles]
    warning = "" if args.no_overlap_check else overlap_warning(bundles, home)
    st["overlap_check"] = warning
    print_report(st, bundles, warning)

    if args.json:
        p = Path(args.json); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] JSON -> {p}")
    if args.csv:
        p = Path(args.csv); write_csv(st, p)
        print(f"[OK] CSV  -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
