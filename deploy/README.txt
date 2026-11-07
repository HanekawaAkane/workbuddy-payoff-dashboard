WorkBuddy Token Dashboard - 另一台设备的部署包
================================================

这个包做什么
------------
把本机的 WorkBuddy token / 积分明细变成一个只读接口，让主设备在两台
都在线时自动把数据拉走，汇总成一张看板。

前置条件
--------
1. 这台机器装了 WorkBuddy 桌面端（数据就在 ~/.workbuddy 里）。
2. 不需要另外装 Python —— WorkBuddy 自带 Python，下面的 bat 会自动找。
3. 两台机器能互相访问：同一局域网用局域网 IP，异地用 Tailscale / ZeroTier
   的虚拟 IP。别把端口直接映射到公网。

三步
----
1. 解压到任意目录（比如 D:\workbuddy-token-dashboard）。
2. 双击 START-NODE.bat，或带参数运行：

       START-NODE.bat  <共享密钥>  <端口>  <设备名>

   例：START-NODE.bat  my-long-secret-123  8765  laptop

   窗口里会打印出访问地址，例如 http://192.168.1.23:8765/api/bundle?token=...
   保持这个窗口开着（锁屏不影响，但电脑不能关机/断网）。

   想让进程意外退出后自动重启，改用常驻版（Ctrl+C 才真正结束）：

       python scripts\keep_online.py --mode node --token <共享密钥> --port 8765 --device %COMPUTERNAME%

   主设备那边对应常驻命令：python scripts\keep_online.py --mode main
   （只绑 127.0.0.1，按 config/peers.json 定时拉对端。）

3. 在主设备编辑 config/peers.json（从 peers.example.json 复制），把上面
   那个地址和密钥填进去，然后启动主设备：

       python scripts/serve.py --peers config/peers.json --open

   主设备会每 60 秒拉一次；对端离线就跳过，上线后自动补上。看板已经
   在监视 bundles 目录，页面会自动重载，不需要手动刷新。

只想导出一次、不想常驻服务？
----------------------------
双击 EXPORT.bat <同步盘目录>，会生成一个 <设备名>.json 放进同步盘。
主设备用 python scripts/serve.py --sources <同步盘> --open 读取。
这条路不需要两台同时在线，但也不是实时拉取。

安全
----
- /api/bundle 只输出四段 token / 模型 / 时间 / 积分，默认不含提示词。
- 非回环监听时程序会强制 --no-prompts，并建议设置 --token。
- 服务只监听，不写入任何 WorkBuddy 数据；不提供任意文件读取。
- 别把 8765 端口映射到公网；用 Tailscale 这类私有网络。

积分口径
--------
便携包里的官方积分来自本机 workbuddy.db 的 session_usage.credit_json。
合并后的总额是各设备本地账单之和，不等于账号云端账单；官网
「个人中心 -> 套餐与用量 -> 积分消耗明细」可用来校总账。

零配置备选（借官方多端协同）
----------------------------
如果两台都装了 WorkBuddy 且不方便配网络，可以在小程序里选中那台电脑，
粘 PASTE-TO-WORKBUDDY.txt 里的那句话，让它自己执行导出并放进资料库。
这依赖官方远程任务能力，本项目不保证所有版本都可用。
