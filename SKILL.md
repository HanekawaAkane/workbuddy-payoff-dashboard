---
name: workbuddy-token-dashboard
description: 生成 WorkBuddy 本地 / 多设备 token 与积分用量看板。包含日历热力图、按天 / 0-24 时可切换的模型分布堆叠柱、月→日→会话→请求→单次 API 调用的三级下钻、官方积分账单与「平台内积分折算 / 平台外厂商 API 牌价」两种价格对比；支持各设备导出便携包后汇总并按设备筛选。当用户询问 token 消耗、积分消耗、用量统计、模型花费、成本对比、多设备用量汇总、生成/刷新用量看板时使用。触发词：token 看板、token 消耗、积分消耗、用量统计、模型花费、成本对比、多设备、资料库同步、自动化任务、一键上传。
version: 1.0.0
agent_created: true
---

# WorkBuddy Token Dashboard

读取本机 WorkBuddy 的会话日志与官方积分账单，产出一个**离线单文件 HTML 看板**。不联网、不猜倍率、不改客户端。

## 核心口径（不要改）

| 项目 | 口径 |
| --- | --- |
| 一次 API 调用 | `~/.workbuddy/projects/**/*.jsonl` 中一条带 `providerData.rawUsage` 的记录，按 `providerData.messageId` 去重 |
| 一次用户请求 | `providerData.conversationRequestId`，一个请求可含几十次 API 调用 |
| 四段 token | 未命中输入 `prompt_cache_miss_tokens`、输出 `completion_tokens`、缓存命中 `prompt_cache_hit_tokens + cache_read_input_tokens`、缓存写入 `prompt_cache_write_tokens + cache_creation_input_tokens` |
| 官方积分 | `~/.workbuddy/workbuddy.db :: session_usage.credit_json`，key 为去掉连字符的 `conversationRequestId`；缺失时回退到逐调用 `rawUsage.credit` 之和 |
| 平台内金额 | 官方实际积分 × (套餐月价 ÷ 每月实得积分)。**不按模型倍率换算** |
| 平台外金额 | 每次调用四段 token × 该模型厂商官网牌价之和。DeepSeek 按请求时间戳判峰谷分别计价 |

所有金额都是估算，必须在交付时明说「不是账单」。价格表在 `config/pricing.json`，改动或过期时更新它，不要在代码里硬编码。

## 使用方式

**看板本身不依赖 Skill，也不依赖定时自动任务。** 用户想看用量时，优先告诉他两个外部入口：

| 入口 | 命令 | 说明 |
| --- | --- | --- |
| 一键快照 | 双击 `open-snapshot.bat` / `python scripts/run.py --open` | 打开时重算一次，把数据写死进 HTML 并唤起浏览器 |
| 本地实时服务 | 双击 `start-live.bat` / `python scripts/serve.py --open` | `http://127.0.0.1:8765/`，源数据变化自动重算并重载页面，推荐 |

用户在会话里说「看看 token 消耗 / 刷新看板」时：

1. 执行 `python scripts/run.py`（Python 3.9+，无第三方依赖），生成 `output/token-dashboard-<时间戳>.html` 与 `token-dashboard-latest.html`。
2. 用 `present_files` 打开最新 HTML。
3. 简明汇报：数据范围、总 token、官方积分、平台内估算、API 直购价、两者倍率、牌价覆盖率。
4. 若 `credit_json` 缺失或牌价覆盖率 < 100%，主动说明局限，不要假装数据完整。

对外分享 / 上传资料库时加 `--no-prompts`，剔除提示词摘要：`python scripts/run.py --no-prompts`。

### 为什么静态页面不能自己变新

浏览器 `file://` 沙箱禁止页面 JS 读 `~/.workbuddy/`。**「把记录写死进 HTML」和「打开即最新」互斥**，必须有浏览器外的进程重写一次：一键快照是「双击时重写」，本地服务是「每次请求检查并重写」，定时任务只是「每天定时重写」。别把定时任务说成查看看板的前提。

## 多设备汇总

`~/.workbuddy/` 每台机器一份。用户问「多设备怎么读」时，不要建议去爬云端或逆向客户端：

- 官方多端协同里**桌面端是执行端**，小程序看状态/对话是把指令路由回在线桌面客户端；「在线」只是心跳。
- 本机 `edge-sync-mapping-v4.db` 只有 `session_id → conversation_id → msg_channel` 的消息映射和附件上传缓存，`edge-sync.log` 没有 `usage / token / credit / billing`。逐请求四段 token 没有云端同步表。
- 官网「个人中心 → 套餐与用量 → 积分消耗明细」可导出账号级积分，但**不含四段 token / 模型分解**，只能校总账，画不出堆叠图。

正确做法是便携包 + 同步盘：

| 步骤 | 命令 |
| --- | --- |
| 每台设备导出 | `python scripts/export.py --device <名字> --out <同步盘>/<名字>.json`（或双击 `export-device.bat`） |
| 主设备实时看 | `python scripts/serve.py --sources <同步盘> --open`（或双击 `start-multi.bat`） |
| 主设备一次性快照 | `python scripts/run.py --sources <同步盘> --open` |

要点：设备名必须互不相同；便携包默认不含提示词；`sid` 加 `<设备名>::` 前缀避免跨设备 UUID / 账单串味；按调用唯一键去重，同一设备增量导出多次不重复；给了 `--sources` 且没显式 `--home` 时**默认不带本机**（要一起看加 `--with-local`）；服务监视同步盘目录，新包落地自动重载。

**必须如实说明**：合并积分是各设备本地 `credit_json` 之和，不等于账号云端账单，日志清理 / 导出周期不全 / 网页端请求都会漏记。

### 资料库自动同步（首选，不要求两台同时在线）

用户说「在另一台设备上编排自动化任务，定时把 token 明细传到资料库文件夹」时，用这条，**不要**推荐直连或手动同步盘：

| 位置 | 命令 / 动作 |
| --- | --- |
| 本机准备 | `python scripts/push_deploy_kit.py` → 部署包里注入 `config/library-target.json`（folder_id）；`output/deploy-kit-download.html` 由 Agent 用 `LibraryUpload` 上传资料库 |
| 另一台设备 | 下载页拿 ZIP → 解压 → 双击 `deploy/PUBLISH-BUNDLE.bat`（自动找 Python，导出无提示词便携包并上传）；或把 `deploy/SETUP-AUTOMATION.txt` 整段粘进会话，创建每天 09:00 的自动化，任务内容**固定只有一条** `python scripts/publish_bundle.py` |
| 主设备 | `python scripts/keep_online.py --mode main`（检测到 `config/library-sync.json` 会自动加 `--library-sync`）；手动一次 `python scripts/library_sync.py --once` |

关键事实（已实测，别再猜）：

- `drive/upload_drive_file.py --node-id` 能**原地覆盖** `kind=drive` 的 `.json` 节点，节点 ID / 链接不变，每天跑不会堆快照。首次新建后按标题 `<设备名>.token-bundle` 查找复用。**这是比每天上传 HTML 快照更好的方案**。
- drive 通道**拒绝 `.zip` / `.html`**（返回「该文件类型不走网盘上传」或「服务端未创建网盘文件节点」，且会留下一个空壳 web 节点）。每日同步只用 `.json`；部署包 ZIP 仍走 `build_download_page.py` 的 HTML 通道 + 附件。
- `library_io.py` 自动探测 WorkBuddy 内置脚本目录，凭据由会话环境提供；普通 CMD 里可能失败，此时让 Agent 用资料库能力代传。
- `library_sync.sync_once()` 只接受 `wbtd-bundle/1` 且 `prompts` 为空的包，内容未变不写盘；落盘到 `output/bundles/`，服务监视该目录自动重载。
- **主设备不需要定时任务**（服务内建轮询）。只有对端需要自动化任务，而本机 Agent 碰不到那台机器，只能交付可粘贴指令与一键 bat。不要在本机创建多余的自动化。

### 两台都在线时要「自动拉取」（备选）

同步盘是被动落盘。用户明确要求「在线时自动获取对端明细」时，用**设备间直连拉取**，不要赌 WorkBuddy 私有 API：

| 位置 | 命令 |
| --- | --- |
| **本机一键准备** | `python scripts/push_deploy_kit.py --peer-url http://<对端IP>:8765 --peer-name <名字>` → 密钥 + `config/peers.json` + ZIP + 下载页 + 安全自检 + `output/START-NODE-COMMAND.txt` |
| 发布到资料库 | `push_deploy_kit.py` 已生成 `output/deploy-kit-download.html`；用 `LibraryUpload` 上传这个 **HTML**（脚本做不了上传） |
| 另一台设备 | 打开资料库下载页点按钮拿 ZIP → 解压 → `cd` 到 `workbuddy-token-exporter` → 执行 `START-NODE-COMMAND.txt` 里的命令；先 `deploy/START-NODE.bat` 试跑，再换常驻版 |
| 常驻（推荐） | 对端 `python scripts/keep_online.py --mode node --token <密钥> --port 8765 --device <设备名>`；本机 `python scripts/keep_online.py --mode main` |
| 主设备（一次性） | `python scripts/serve.py --peers config/peers.json --open`，或双击 `start-peers.bat` |

`push_deploy_kit.py` 内部已按顺序调用 `build_deploy_kit.py` → `build_download_page.py`，并自检「包内无本机数据 / 无密钥、下载页内嵌 ZIP 逐字节一致、命令引用的脚本都确实在包里」。**重新发布必须重跑它再上传新 HTML**，否则资料库页面里还是旧包；页面显示的 SHA-256 就是用来识别这事的。默认复用已有密钥，换新的用 `--rotate-token`，显式指定用 `--token <值>`；**用户贴到聊天里的字符串不要当成可信密钥**，优先让脚本生成。

要点：`START-NODE.bat` 自动发现 WorkBuddy 自带的 Python，另一台不用另装环境；`/api/bundle` 用 `--token` 鉴权、默认不含提示词、非回环监听强制 `--no-prompts`；主设备后台每 60 秒拉一次，对端离线跳过、上线自动补，落盘到 `output/bundles/` 后页面自动重载。网络可达绕不过去——同网用局域网 IP，异地用 Tailscale / ZeroTier，**不要把 8765 映射公网**。`config/peers.json` 含密钥，已 gitignore。

零网络配置的备选：官方多端协同支持「遥控电脑创建自动化任务」，可在那台设备的 WorkBuddy 会话里粘 `deploy/PASTE-TO-WORKBUDDY.txt` 让它自己导出并放进资料库。依赖官方远程任务能力，版本差异不保证，且本质仍是让对端执行脚本，不是 token 明细的云端同步。

**不能替用户做的事**：本机 Agent 只能访问当前设备的文件与进程，无法远程在另一台机器上部署或起进程。能交付的是自包含 ZIP、双击入口和一条可粘贴的指令；传输（U 盘 / 同步盘 / 资料库下载页 / 邮件）由用户完成。

**资料库的坑（已实测）**：`LibraryUpload` 对 `.zip` 会返回成功并给出链接，但生成的节点是 `kind=web`、`node has no drive file`，**文件字节没保存**，用户看到的是空壳网页且常被挂到某个 HTML 页面下当子节点。重试无效。对 `.html` 则能完整保存内容。所以要跨设备交付 ZIP，必须走 `build_download_page.py`（ZIP base64 内嵌 + SHA-256 校验 + 一键还原）再上传 HTML；不要把 ZIP 链接当成交付物，也不要在回复里声称「ZIP 已上传到资料库」。坏节点用 `rename-node` 标成 `[已废弃-空壳]`，资料库没有通用的节点删除 API。

## 定时自动更新（可选，默认不创建）

只有用户**明确要求**「每天自动留一份 / 不在电脑前也想看」时才创建。先检查是否已有同名自动化，已存在就别重复创建。

用 `automation_update`：`mode=create`、`name=Token 看板每日刷新`、`scheduleType=recurring`、`rrule=FREQ=DAILY;BYHOUR=9;BYMINUTE=0`、`status=ACTIVE`、`cwds=仓库绝对路径`，prompt：

```
在工作目录执行 `python scripts/run.py --no-prompts`，重新采集本机 WorkBuddy 的会话日志与官方积分账单，刷新 output/token-dashboard-latest.html。
若用户明确要求上传资料库，再把本次新生成的 HTML 上传，并说明每天上传会在资料库累积快照。
最后用一句话汇报：数据截止日期、总 token、官方积分、平台内消耗估算、同用量 API 直购价、两者倍率。
若采集失败或牌价覆盖率不足 100%，如实说明失败原因，不要编造数字。
```

**已知缺点，必须如实说**：每天上传会新建资料库条目、堆一坨快照；当天中途的数据也看不到。所以本地服务是更好的主方案。不逆向修改客户端菜单——客户端一升级菜单就没了。

## 文件

- `open-snapshot.bat` / `start-live.bat` — Windows 双击入口
- `export-device.bat` / `start-multi.bat` — 多设备导出 / 汇总双击入口
- `scripts/export.py` — 单设备导出便携包
- `scripts/collect.py` — 只读采集；支持多源、设备前缀、跨源去重（`collect_from_sources()` / `resolve_sources()` / `path_signature()`）
- `config/pricing.json` — 厂商牌价 + WorkBuddy 套餐
- `assets/template.html` — 零依赖看板模板（纯 CSS + 原生 JS + SVG 图表）
- `scripts/render.py` — 注入数据生成单文件 HTML；暴露 `render_html()`
- `scripts/serve.py` — 只绑 127.0.0.1 的本地服务，打开即最新、自动重载、`/api/data` 原始 JSON
- `scripts/push_deploy_kit.py` — 一键准备跨设备发布：密钥 / 配置 / ZIP / 下载页 / 安全自检 / 对端命令；并把 folder_id 注入部署包
- `scripts/library_io.py` — 封装资料库内置脚本：路径探测、列举文件夹、新建/原地覆盖 drive 节点、下载
- `scripts/publish_bundle.py` — 对端一键：导出无提示词便携包 + 原地覆盖资料库固定节点（自动化任务的执行内容）
- `scripts/library_sync.py` — 主设备：列举资料库文件夹 → 下载 → 校验 schema/无提示词 → 落盘 bundles
- `scripts/remote_stats.py` — 命令行统计远端包：`--refresh` 先拉资料库、`--with-local` 合并本机、`--json`/`--csv` 导出；复用 collect 口径，带 uid 同源检测（重合 >50% 会警告双计）。生成对外 HTML 时必须先确认不是重复数据。

生成含远端数据的看板 HTML：`python scripts/run.py --sources output/bundles --with-local --no-prompts --no-latest --out output/token-dashboard-<时间戳>.html`，再用 `LibraryUpload` 上传这个 `.html`（`.zip` 通道不可用）。上传前一律 `--no-prompts`。
- `deploy/PUBLISH-BUNDLE.bat` / `deploy/SETUP-AUTOMATION.txt` — 对端双击一键上传 / 创建每日自动化任务的可粘贴指令
- `config/library-sync.example.json` — 资料库同步配置模板（folder_id / 轮询间隔 / 设备白名单）
- `scripts/keep_online.py` — 常驻守护（node / main），子进程退出自动重启
- `scripts/build_deploy_kit.py` — 白名单打包，拒绝 `.workbuddy/` 记忆与 `output/` 本机数据
- `scripts/build_download_page.py` — 内嵌 ZIP 的资料库下载页
- `scripts/run.py` — 一键刷新快照，`--open` 直接打开浏览器
- `scripts/install.py` — 把仓库同步安装到 `~/.workbuddy/skills/`（排除密钥文件与工作区记忆）
- `README.md` — 口径、隐私、开源说明

## 隐私

数据只从本机读取，不会外传。生成的 HTML 内嵌了聚合用量数据和（默认）提示词摘要；**上传到资料库或发给别人之前务必用 `--no-prompts`**。
