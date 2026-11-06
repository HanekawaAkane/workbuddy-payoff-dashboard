#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data.json 注入模板，产出一个完全离线、零外部依赖的单文件 HTML。"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "__DASHBOARD_DATA__"


def safe_json(obj) -> str:
    """放进 <script type=application/json> 之前的必要转义。"""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (s.replace("&", "\\u0026")
             .replace("<", "\\u003c")
             .replace(">", "\\u003e")
             .replace("\u2028", "\\u2028")
             .replace("\u2029", "\\u2029"))


def render_html(data: dict, template_path: Path) -> str:
    """返回完整的单文件 HTML 字符串（不写文件）。"""
    tpl = template_path.read_text(encoding="utf-8")
    if PLACEHOLDER not in tpl:
        raise RuntimeError("模板缺少占位符 " + PLACEHOLDER)
    html = tpl.replace(PLACEHOLDER, safe_json(data))
    if PLACEHOLDER in html:
        raise RuntimeError("占位符替换失败")
    return html


def render(data_path: Path, template_path: Path, out: Path | None = None) -> Path:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    html = render_html(data, template_path)
    if out is None:
        cst = timezone(timedelta(hours=8))
        stamp = datetime.now(cst).strftime("%Y%m%d-%H%M%S")
        out = ROOT / "output" / f"token-dashboard-{stamp}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="渲染 token 看板 HTML")
    ap.add_argument("--data", default=str(ROOT / "output" / "data.json"))
    ap.add_argument("--template", default=str(ROOT / "assets" / "template.html"))
    ap.add_argument("--out", default="", help="输出路径；留空则按时间戳生成到 output/")
    ap.add_argument("--latest", action="store_true", help="额外写一份固定名 token-dashboard-latest.html")
    args = ap.parse_args()
    out = render(Path(args.data), Path(args.template), Path(args.out) if args.out else None)
    print(f"[OK] {out}  ({out.stat().st_size/1024/1024:.2f} MB)")
    if args.latest:
        latest = ROOT / "output" / "token-dashboard-latest.html"
        latest.write_bytes(out.read_bytes())
        print(f"[OK] {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
