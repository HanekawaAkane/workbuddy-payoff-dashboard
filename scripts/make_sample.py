#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用确定性合成数据生成公开示例看板，不含任何真实用量或提示词。"""
from __future__ import annotations
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
from render import render  # noqa: E402

CST = timezone(timedelta(hours=8))
# 各模型的实测积分单价（积分 / 百万 tokens）：缓存命中、未命中输入、输出
CREDIT_RATE = {
    "deepseek-v4.1-flash": (0.38, 18.3, 75.2),
    "mimo-v2.6-pro": (0.72, 85.7, 171.4),
    "minimax-m3.1-flash": (2.86, 28.6, 114.3),
    "space-bunny": (1.67, 6.3, 21.9),
    "glm-5.3": (40.0, 160.4, 563.8),
    "glm-5.3-flash": (3.5, 11.6, 35.2),
    "kimi-k3.1-pro": (31.7, 315.7, 1651.5),
    "step-5-preview": (10.0, 200.0, 571.6),
    "hy4-free": (5.7, 142.9, 285.5),
}
WEIGHTS = {
    "deepseek-v4.1-flash": 30, "mimo-v2.6-pro": 20, "minimax-m3.1-flash": 14,
    "space-bunny": 12, "glm-5.3": 6, "glm-5.3-flash": 8,
    "kimi-k3.1-pro": 4, "step-5-preview": 4, "hy4-free": 2,
}
TITLES = ["整理季度数据并生成图表", "重构数据清洗脚本", "论文相关工作调研",
          "排查接口超时问题", "批量转换文档格式", "写一份项目周报",
          "复现实验并对比结果", "梳理需求并拆任务", "校对长文档", "搭一个本地小工具"]
PROMPTS = ["帮我把这份表格按月份汇总，并画一张趋势图。",
           "检查这个脚本为什么在大数据集上会超时，给出修改建议。",
           "检索近三个月的相关工作，按方法分类整理成表格。",
           "把这几份文档统一成同一套标题和引用格式。",
           "解释一下这段实现的缓存策略，并指出潜在问题。",
           "根据当前进度写一版周报，突出阻塞项。",
           "对比两组实验指标，算出提升幅度。",
           "把这个函数拆成几个可测试的模块。",
           "找出文档里前后矛盾的术语并统一。",
           "给这个工具补一份使用说明。"]


def main():
    pricing = json.loads((ROOT / "config" / "pricing.json").read_text(encoding="utf-8"))
    rnd = random.Random(20261106)
    end = datetime(2026, 11, 6, 21, 0, tzinfo=CST)
    calls, bills, db_sessions, prompt_map = [], {}, {}, {}
    models = list(WEIGHTS)
    weights = [WEIGHTS[m] for m in models]

    for d in range(60):
        day = end - timedelta(days=59 - d)
        if day.weekday() == 6 and rnd.random() < .55:
            continue
        for s in range(rnd.randint(1, 3)):
            sid = f"sample-{d:02d}-{s:02d}-0000-0000-000000000000"
            db_sessions[sid] = {"title": rnd.choice(TITLES), "cwd": f"/work/demo-{d % 5}",
                                "created_at": int(day.timestamp() * 1000), "model": ""}
            bills[sid] = {}
            prompt_map[sid] = []
            for q in range(rnd.randint(1, 4)):
                base = day.replace(hour=rnd.choice([9, 10, 11, 14, 15, 16, 17, 19, 20, 21, 22, 23]),
                                   minute=rnd.randint(0, 59))
                ts0 = int(base.timestamp() * 1000)
                reqid = f"{d:02d}{s:02d}{q:02d}".ljust(32, "0")[:32]
                prompt_map[sid].append((ts0 - 1500, rnd.choice(PROMPTS)))
                model = rnd.choices(models, weights=weights, k=1)[0]
                rate = CREDIT_RATE[model]
                log_sum = 0.0
                for k in range(rnd.randint(3, 22)):
                    ts = ts0 + k * rnd.randint(9000, 42000)
                    hit = rnd.randint(6000, 98000)
                    miss = rnd.randint(300, 9000)
                    out = rnd.randint(60, 2600)
                    credit = (hit * rate[0] + miss * rate[1] + out * rate[2]) / 1e6
                    if model == "hy4-free":
                        credit = 0.0
                    log_sum += credit
                    calls.append({
                        "sid": sid, "reqid": reqid, "ts": ts, "model": model,
                        "display": pricing["models"][model]["display"],
                        "hit": hit, "miss": miss, "out": out, "write": 0,
                        "credit": round(credit, 6), "kind": 0 if k % 5 else 1,
                        "is_peak": collect.is_peak(ts),
                    })
                if rnd.random() < .65:
                    bills[sid][reqid] = round(log_sum * rnd.uniform(1.0, 1.09), 4)
            prompt_map[sid].sort()

    calls.sort(key=lambda c: c["ts"])
    data = collect.build(pricing, calls, bills, db_sessions, True, prompt_map)
    data["meta"]["note"] = "SYNTHETIC DEMO DATA — 全部为随机生成的示例，非真实用量"

    tmp = ROOT / "output" / "sample-data.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    out = render(tmp, ROOT / "assets" / "template.html", ROOT / "examples" / "sample-dashboard.html")
    print(f"[OK] 合成示例：{data['meta']['n_calls']} 次调用 / {data['meta']['n_requests']} 个请求 / {data['meta']['n_models']} 个模型")
    print(f"[OK] -> {out}  ({out.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
