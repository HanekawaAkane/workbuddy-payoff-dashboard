#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成一个「部署包下载页」：把 ZIP 以 base64 内嵌进单文件 HTML。

用途：WorkBuddy 资料库的上传通道对 .zip 只建空壳网页节点（kind=web,
node has no drive file），但对 .html 能完整保存内容。于是把 ZIP 塞进
HTML，在另一台设备打开资料库里的这个页面，点一下按钮就还原出真正的
workbuddy-token-exporter.zip。

    python scripts/build_download_page.py
    -> output/deploy-kit-download.html
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WorkBuddy Token 部署包 · 下载</title>
<style>
:root{--bg:#f5f6fa;--card:#fff;--bd:#e5e8f0;--tx:#171a26;--mu:#697187;--ac:#4f46e5;--ac2:#eef0ff;--ok:#0d9488}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.7}
.wrap{max-width:820px;margin:0 auto;padding:38px 22px 70px}
.eyebrow{font-size:11px;font-weight:750;letter-spacing:.14em;color:var(--ac);text-transform:uppercase}
h1{font-size:29px;letter-spacing:-.03em;margin:10px 0 8px}
.sub{color:var(--mu);font-size:13.5px;margin:0 0 26px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:24px;box-shadow:0 10px 30px rgba(16,24,40,.05);margin-bottom:18px}
.hero{text-align:center}
.fname{font-family:Consolas,Menlo,monospace;font-size:17px;font-weight:700;margin:6px 0 2px;word-break:break-all}
.meta{color:var(--mu);font-size:12.5px}
button{margin-top:20px;border:0;border-radius:11px;background:var(--ac);color:#fff;font-size:15px;font-weight:700;padding:14px 30px;cursor:pointer;box-shadow:0 6px 18px rgba(79,70,229,.25)}
button:hover{background:#4338ca}
button:active{transform:translateY(1px)}
#status{margin-top:14px;font-size:12.5px;min-height:20px}
#status.ok{color:var(--ok);font-weight:650}
#status.bad{color:#c0392b;font-weight:650}
.note{background:#fff5e6;border-left:3px solid #d58a16;border-radius:0 9px 9px 0;padding:13px 16px;font-size:12.5px;color:#745018;margin-bottom:18px}
h2{font-size:16px;margin:0 0 10px;letter-spacing:-.01em}
ol{margin:0;padding-left:21px;font-size:13.5px}
ol li{margin:7px 0}
code{font-family:Consolas,Menlo,monospace;background:var(--ac2);border-radius:4px;padding:1px 6px;font-size:12px;color:#3730a3}
.files{font-family:Consolas,Menlo,monospace;font-size:11.5px;color:var(--mu);background:#fafbfe;border:1px solid var(--bd);border-radius:9px;padding:12px 14px;max-height:230px;overflow:auto;white-space:pre-wrap;word-break:break-all}
.hash{font-family:Consolas,Menlo,monospace;font-size:11px;color:var(--mu);word-break:break-all;margin-top:12px}
.foot{color:var(--mu);font-size:11.5px;margin-top:22px;line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">workbuddy-token-dashboard / deploy kit</div>
  <h1>部署包下载</h1>
  <p class="sub">在另一台设备上打开本页，点下面的按钮即可拿到完整的 <b>workbuddy-token-exporter.zip</b>。</p>

  <div class="note"><b>为什么要做成网页：</b>资料库的上传通道不接收 <code>.zip</code>——它只会生成一个没有文件内容的空壳网页节点。但 <code>.html</code> 能完整保存，所以这个页面内嵌了全部 ZIP 字节，点按钮在本地还原成真正的压缩文件。<b>不需要联网、不需要服务端。</b></div>

  <div class="card hero">
    <div class="fname">workbuddy-token-exporter.zip</div>
    <div class="meta">__SIZE__ · __NFILES__ 个文件 · 生成于 __BUILT__</div>
    <button id="dl">下载部署包 ZIP</button>
    <div id="status"></div>
    <div class="hash">SHA-256：<span id="expected">__SHA__</span></div>
  </div>

  <div class="card">
    <h2>拿到之后做什么</h2>
    <ol>
      <li>解压到任意目录（例如 <code>D:\\workbuddy-token-dashboard</code>）。</li>
      <li>双击 <code>deploy\\START-NODE.bat &lt;密钥&gt; &lt;端口&gt; &lt;设备名&gt;</code>，起只读节点服务。它会自动找到 WorkBuddy 自带的 Python，<b>不用另装环境</b>。</li>
      <li>主设备从 <code>config\\peers.example.json</code> 复制成 <code>peers.json</code>，填这台设备的地址和同一个密钥，跑 <code>python scripts/serve.py --peers config/peers.json --open</code>。</li>
    </ol>
    <p style="font-size:12.5px;color:var(--mu);margin:12px 0 0">然后主设备每 60 秒自动拉一次，对端离线跳过、上线自动补，看板自动重载。同网用局域网 IP，异地用 Tailscale / ZeroTier，别把端口映射到公网。</p>
  </div>

  <div class="card">
    <h2>包内文件（__NFILES__）</h2>
    <div class="files">__FILES__</div>
  </div>

  <div class="foot">包内不含任何本机真实用量数据、日志或提示词；<code>config/peers.json</code>（含密钥）不会被打进去。下载后浏览器可能提示"文件可能有害"，那是因为 ZIP 里含 .bat 脚本，属正常现象——请自行核对上面的 SHA-256。</div>
</div>

<script>
var B64="__B64__";
var EXPECT="__SHA__";
var NAME="workbuddy-token-exporter.zip";
function hex(buf){return Array.from(new Uint8Array(buf)).map(function(b){return b.toString(16).padStart(2,'0')}).join('')}
document.getElementById('dl').addEventListener('click',async function(){
  var st=document.getElementById('status');
  st.className='';st.textContent='正在还原文件…';
  try{
    var bin=atob(B64), arr=new Uint8Array(bin.length);
    for(var i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
    var blob=new Blob([arr],{type:'application/zip'});
    var ok=true, h='';
    try{ h=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()); }catch(e){ ok=false; }
    if(ok){
      var got=hex(h);
      st.className=got===EXPECT?'ok':'bad';
      st.textContent=got===EXPECT?'SHA-256 校验通过，文件完整。':'校验失败，文件可能已损坏：'+got;
      if(got!==EXPECT) return;
    }else{
      st.className='ok';st.textContent='已还原（当前环境不支持本地校验，请自行核对 SHA-256）。';
    }
    var a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=NAME;
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(function(){URL.revokeObjectURL(a.href)},60000);
  }catch(e){st.className='bad';st.textContent='还原失败：'+e.message}
});
</script>
</body>
</html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成内嵌 ZIP 的部署包下载页")
    ap.add_argument("--zip", default=str(ROOT / "output" / "workbuddy-token-exporter.zip"))
    ap.add_argument("--out", default=str(ROOT / "output" / "deploy-kit-download.html"))
    args = ap.parse_args(argv)

    zpath = Path(args.zip)
    if not zpath.exists():
        raise SystemExit(f"[FATAL] 找不到部署包 {zpath}，先运行 python scripts/build_deploy_kit.py")
    raw = zpath.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
    html = (PAGE
            .replace("__B64__", base64.b64encode(raw).decode("ascii"))
            .replace("__SHA__", sha)
            .replace("__SIZE__", f"{len(raw)/1024:.0f} KB")
            .replace("__NFILES__", str(len(names)))
            .replace("__BUILT__", datetime.now(CST).strftime("%Y-%m-%d %H:%M"))
            .replace("__FILES__", "\n".join(n.replace("workbuddy-token-exporter/", "", 1) for n in names)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out}  ({out.stat().st_size/1024:.0f} KB)")
    print(f"[OK] ZIP {len(raw):,} bytes / {len(names)} files / sha256 {sha}")
    print("[NEXT] 用 LibraryUpload 上传这个 HTML 到资料库；.html 通道可完整保存内容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
