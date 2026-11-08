# workbuddy-token-dashboard

WorkBuddy 的本地 token / 积分用量看板。一个离线单文件 HTML，日历热力图、按天 / 0–24 时模型分布、月→日→会话→请求→单次 API 调用的逐级下钻，以及按各模型厂商牌价计算的 **API 直购价**（含按模型花费、四段 token 花费构成）。

**金额只走厂商 API 牌价这一条口径**；官方积分仅作为账单用量指标展示，不乘任何套餐单价、不折算人民币。同时是一个 WorkBuddy Skill，默认不创建定时任务。

> 直接看效果：打开 [`examples/sample-dashboard.html`](examples/sample-dashboard.html)（合成数据，无真实用量）。

---

## 为什么做这个

WorkBuddy 客户端本身不提供逐请求的用量明细。但它在本机留了两类数据：

| 数据 | 位置 | 内容 |
| --- | --- | --- |
| 会话日志 | `~/.workbuddy/projects/**/*.jsonl` | 每次模型 API 调用的 `providerData.rawUsage`，含未命中输入 / 输出 / 缓存命中 / 缓存写入四段 token |
| 官方积分账单 | `~/.workbuddy/workbuddy.db :: session_usage.credit_json` | 每个用户请求实际扣了多少积分 |

两者用 `conversationRequestId` 关联。于是可以做到：积分用官方账单（准确），token 用逐调用日志（可算厂商牌价），两条路径互不干扰。

**只算一种金额**：每条调用的四段 token 分别乘以该模型的厂商牌价再累加，得到「同用量 API 直购价」。官方只公开了客户端面板上的倍率（会随活动与峰谷变动），且未公开逐模型四段积分单价，所以本看板**不按模型倍率换算、不做积分折人民币**；积分只用来反映官方账单的用量。

---

## 快速开始

需要 Python 3.9+，**无任何第三方依赖**。

### 方式 A · 双击打开就是最新数据（最简单）

Windows 双击 **`open-snapshot.bat`**：重新采集 → 重写 `output/token-dashboard-latest.html` → 用默认浏览器打开。
数据在这一刻被"写死"进 HTML，之后是快照；想看更新的再双击一次。

```bash
python scripts/run.py --open        # 等价命令，跨平台
```

把 `output/token-dashboard-latest.html` 拖进浏览器书签也行，但记住那是上次生成的快照。

### 方式 B · 本地服务，打开即实时（推荐）

Windows 双击 **`start-live.bat`**，或：

```bash
python scripts/serve.py --open      # 打开 http://127.0.0.1:8765/
```

- 服务只监听 `127.0.0.1`，只读本机文件，不联网、不写数据。
- 每次请求都检查 WorkBuddy 日志/数据库的修改时间，**源数据变了就现场重新采集并渲染**。
- 页面每 20 秒探一次，发现变化自动重载；也可点右下角「重新读取」强制重算。
- `/api/data` 直接返回原始 JSON，方便别的工具接。
- Ctrl+C 停止。把地址存成浏览器书签，就是你要的"一个固定入口"。

`/api/status`、`/api/refresh`、`/api/data` 三个接口都可用。

### 其他命令

```bash
python scripts/install.py            # 安装为 ~/.workbuddy/skills/ 下的 Skill
python scripts/run.py --no-prompts   # 剔除提示词摘要，适合对外分享
python scripts/make_sample.py        # 用合成数据重新生成示例看板
python -m unittest discover -s tests -v
```

非默认数据目录：加 `--home "D:/somewhere/.workbuddy"`，或设环境变量 `WORKBUDDY_HOME`。

---

## 为什么静态页面不能自己读数据

这是浏览器沙箱的硬约束，不是设计偷懒：

`file://` 打开的 HTML 里的 JS **不能**读 `~/.workbuddy/projects/**` 或 `workbuddy.db`。所以「把 token 记录写死进 HTML」和「打开就能看到最新记录」是互斥的——写死就是快照。

想让它变新，必须有浏览器外的进程重新写一次。只有三条路：

| 方案 | 谁触发重算 | 代价 |
| --- | --- | --- |
| A 一键快照 `open-snapshot.bat` | 你双击时 | 不双击就是旧数据 |
| B 本地服务 `serve.py` | 每次打开页面自动检查 | 要有个常驻进程（或开机自启） |
| C 定时任务 | 每天 09:00 | 不需要进程常驻，但当天中途的数据看不到、且每天往资料库塞新文件会堆积 |

**本项目主推 A / B。** 定时任务只是 C，是给"不在电脑前、想在 WorkBuddy 资料库里留一份"的人用的可选项，不是查看看板的前提。Skill 不再默认要求创建它。

> 顺带说清楚：WorkBuddy 的「Skill」不是浏览器插件，它只是让 Agent 能调用脚本；真正在外部打开的是生成的 HTML 或本地服务。资料库里那个页面链接是软件内点开的入口，但那也是快照。

---

## 多设备怎么汇总

`~/.workbuddy/` 每台机器一份，网页没法隔空读另一台机器的磁盘。所以必须**把各设备的记录汇到一个点**。

### 先说「在线手段」为什么不够

WorkBuddy 小程序确实能看各客户端在线状态、也能访问各个对话，但这不等于有跨设备的用量明细通道：

- 官方多端协同文档写得很明白：**桌面端是执行端**，小程序看的是桌面任务/对话，指令**路由回在线的桌面客户端**；「在线」是心跳状态，电脑关机断网就打不开。
- 本机 `edge-sync-mapping-v4.db` 里只有 `session_id → conversation_id → msg_channel`（`convmsg:` 消息通道）和图片/附件的 COS、SMH 上传缓存；`edge-sync.log` 里全是 `conversation / session / artifact / message`，**没有 `usage / token / credit / billing`**。
- 逐请求四段 token 只存在于本地 `projects/**/*.jsonl` 的 `providerData.rawUsage`，没有对应的云端同步表。

真正账号级、天然跨设备的是官网「个人中心 → 套餐与用量 → 积分消耗明细」（可按今天 / 7 天 / 30 天筛选并导出）。但它**只有积分，没有四段 token 和模型分解**——能校总账，画不出堆叠图。所以别指望在线通道，用下面的本地汇集。

### 做法：便携包 + 同步盘

```
每台设备                          同步盘                     主设备
┌──────────────┐   export.py   ┌──────────────────┐  --sources  ┌──────────────┐
│ ~/.workbuddy │ ────────────▶ │ laptop.json      │ ───────────▶│ 汇总看板     │
│ (本机日志)   │               │ desktop.json     │             │ 可按设备筛选 │
└──────────────┘               └──────────────────┘             └──────────────┘
```

**每台设备**（设备名必须互不相同）：

```bash
python scripts/export.py --device laptop --out "D:/Sync/wb-devices/laptop.json"
```

Windows 可直接双击 `export-device.bat`（用主机名当设备名，第一个参数是同步盘目录）。

**主设备**：

```bash
python scripts/serve.py --sources "D:/Sync/wb-devices" --open   # 实时服务，推荐
python scripts/run.py   --sources "D:/Sync/wb-devices" --open   # 一次性快照
```

Windows 双击 `start-multi.bat "D:\Sync\wb-devices"` 亦可。

细节：

- 便携包默认**不含提示词**，只含四段 token、模型、时间、官方积分和会话标题，几百 KB，适合丢同步盘。要含提示词加 `--with-prompts`，自己承担泄露风险。
- `sid` 统一加 `<设备名>::` 前缀，跨设备 UUID 和 `credit_json` 账单 key 不会串；按调用唯一键去重，同一台设备增量导出多次也不会算重。
- 给了 `--sources` 且没显式 `--home` 时**默认不带本机**，避免本机也导过包时重复计数。要把本机一起算进来加 `--with-local`。
- 服务会监视同步盘目录，新落一个包、或某个包被更新，页面 20 秒内自动重载，不用手动操作。
- 看板会多出：设备下拉筛选、01 节设备分布条、下钻表「设备」列、CSV 里的设备列、04 节的多设备口径说明。

### 资料库自动同步（推荐，不要求两台同时在线）

比直连更适合「两台设备不总同时在线」：对端用 WorkBuddy 自动化任务定时把明细推到资料库固定文件夹，主设备定时去取。资料库是账号级的，天然跨设备；不需要局域网 IP、Tailscale、防火墙放行，也不依赖小程序或私有远程通道。

```
另一台设备                          资料库                          主设备
publish_bundle.py（每天 9:00） ──▶ WorkBuddy Token 便携包/  ──▶ serve.py --library-sync
导出 + 一键上传（原地覆盖）         <设备名>.token-bundle.json      定时拉取 → 看板自动重载
```

**一次性准备**：本机跑 `python scripts/push_deploy_kit.py`，它会把资料库文件夹 ID 注入部署包的 `config/library-target.json`。另一台设备从资料库里的部署包下载页拿 ZIP、解压。

**另一台设备（一键）**：

- 双击 `deploy/PUBLISH-BUNDLE.bat`：自动找到 Python、导出不含提示词的便携包、上传到资料库固定节点。**不用手敲文件夹 ID，也不用 Agent 临场操作**。
- 每天自动跑：把 `deploy/SETUP-AUTOMATION.txt` 整段粘进那台设备的 WorkBuddy 会话，让它创建每天 09:00 的自动化任务。任务内容只有一条固定命令 `python scripts/publish_bundle.py`。
- 每台设备固定一个 `<主机名>.token-bundle.json` 节点；脚本按标题找到同名 drive 节点就原地覆盖，**节点 ID 与链接不变，每天跑不会堆快照**。主机名必须互不相同。

**主设备**：`python scripts/keep_online.py --mode main`（检测到 `config/library-sync.json` 会自动加 `--library-sync`），或直接 `python scripts/serve.py --library-sync config/library-sync.json`。服务每 300 秒列举文件夹、把变化的包下载到 `output/bundles/`，看板本来就在监视这个目录，自动重算重载。手动拉一次：`python scripts/library_sync.py --once`。

**实测**：5.7 MB / 16,921 次调用的包上传成功；第二次原地覆盖、节点 ID 不变；主设备二次拉取识别「无变化」不写盘；服务内建轮询合并出两台设备 33,844 次调用。

**限制**：资料库 drive 通道只认部分文件类型——`.json` 可以，`.zip` / `.html` 会被拒（「该文件类型不走网盘上传」）。所以每日同步走 `.json`，部署包 ZIP 仍走一次性下载页 / 附件。资料库凭据由 WorkBuddy 会话环境提供，在普通 CMD 里跑可能因缺环境变量失败，此时让 Agent 代为上传。

### 命令行统计远端数据

`scripts/remote_stats.py` 从资料库同步下来的便携包做统计，**口径与看板完全一致**（复用 `collect.py` 的四段 token / 官方积分 / API 直购价计算，不另算一套）：

```bash
python scripts/remote_stats.py --refresh --json output/remote-stats.json --csv output/remote-stats.csv
python scripts/remote_stats.py --refresh --with-local   # 连本机一起统计
```

输出每台设备的调用数、缓存命中 / 未命中输入 / 输出 / 缓存写入、官方积分、API 直购价、模型 TOP 8、最近 10 天、峰时占比；`--json` / `--csv` 可导出给别的工具。默认只统计资料库远端包，`--refresh` 会先拉最新。积分只是用量指标，金额列只有 API 直购价。

脚本带**同源检测**：把 uid 去掉设备前缀后与本机比对，重合超过 50% 会明确警告「这是本机重复导出，合并会双计」，避免把一份数据当成两台设备。

### 两台都在线：设备间直连（备选）

同步盘是「被动落盘」。想要**只要两台在线就自动把对端明细拿过来**，也可以直接用设备间直连拉取——不依赖 WorkBuddy 私有 API，也不依赖任何云盘；代价是两台必须同时在线且网络互通。

```
另一台设备（节点）                          主设备
serve.py --host 0.0.0.0 --token X   ◀── GET /api/bundle?token=X ───  serve.py --peers config/peers.json
每 60 秒拉一次 → output/bundles/<设备>.json → 看板自动重载
```

**本机一键准备（推荐）**：

```bash
python scripts/push_deploy_kit.py --peer-url http://192.168.1.23:8765 --peer-name 笔记本
```

一条命令跑完：取/生成共享密钥 → 写 `config/peers.json` → 打包 ZIP → 生成内嵌 ZIP 的下载页 → 安全自检 → 写 `output/START-NODE-COMMAND.txt`（对端要敲的命令，含密钥）和 `output/publish-manifest.json`（路径、SHA、密钥指纹，不含密钥）。不知道对端 IP 就先留空 `--peer-url`，之后填 `config/peers.json` 的 `peers[].url`。

脚本默认复用已有密钥；想换新的加 `--rotate-token`；确需指定某个值用 `--token <值>`。**密钥不要在聊天、邮件、资料库里传**——它是给 `START-NODE-COMMAND.txt` 和 `config/peers.json` 用的，由你在另一台设备上手动敲进去。

**另一台设备**：从资料库里的**部署包下载页**拿到 ZIP（或 U 盘 / 同步盘拷过去），解压，`cd` 到解压出来的 `workbuddy-token-exporter` 目录，执行 `START-NODE-COMMAND.txt` 里的命令。先跑一次性版 `deploy/START-NODE.bat` 确认能起来，再换常驻版。

> **资料库不能收 `.zip`，别直接传 ZIP。** 上传工具会把它变成一个 `kind=web` 的空壳网页节点（`node has no drive file`），文件字节根本没存进去，在另一台设备也下不来。实测重试两次都一样。
>
> 绕开的办法：`python scripts/build_download_page.py` 生成一个**内嵌完整 ZIP 的下载页**（`output/deploy-kit-download.html`），把这个 `.html` 上传到资料库（HTML 通道可完整保存内容），在另一台设备打开页面点「下载部署包 ZIP」就在本地还原出真正的 `.zip`。页面带 SHA-256 校验，下载后自动比对。发布前重新跑这两条命令即可保证页面里的包是最新的。

它会：

- 自动找到 Python——WorkBuddy 桌面端自带一份，不用额外装环境；
- 起一个只读服务，暴露 `/api/bundle`，只输出四段 token / 模型 / 时间 / 积分，**默认不含提示词**；
- 用 `--token` 挡住未授权拉取；非回环监听时程序还会强制 `--no-prompts`。

**常驻版**（推荐，黑窗口意外关掉/进程崩了会自动重启，1s→30s 退避）：

```bash
# 另一台设备
python scripts/keep_online.py --mode node --token <密钥> --port 8765 --device <设备名>
# 本机汇总端（只绑 127.0.0.1）
python scripts/keep_online.py --mode main
```

`--mode main` 会在 `config/peers.json` 存在时自动带上 `--peers`；文件不存在就退化成单设备本地看板。`Ctrl+C` 才真正结束守护。

**主设备**：`push_deploy_kit.py` 已经写好 `config/peers.json`（含密钥），只差对端真实 IP。也可以从 `config/peers.example.json` 复制手动填，然后：

```bash
python scripts/serve.py --peers config/peers.json --open
```

Windows 双击 `start-peers.bat` 亦可。主设备后台线程每 60 秒拉一次：对端离线就跳过、上线后自动补上；拉到的包写进 `output/bundles/`，而服务本来就在监视这个目录，页面 20 秒内自动重载。整个过程不需要人工触发。

网络可达这一步绕不过去，三选一：同一局域网填局域网 IP；异地用 Tailscale / ZeroTier 虚拟 IP；**别把 8765 直接映射到公网**。`config/peers.json` 含密钥，已在 `.gitignore` 里。

独立跑一次、不起服务：`python scripts/peers.py --config config/peers.json --out output/bundles`。

### 零网络配置的备选：借官方多端协同

官方多端协同文档写了「可以遥控电脑创建自动化任务」，小程序选中目标电脑就能让那台桌面端执行任务、操作本地文件。所以也可以在那台设备的 WorkBuddy 里粘 `deploy/PASTE-TO-WORKBUDDY.txt` 里的那句话，让它自己跑导出脚本并把结果放进同步盘或资料库。

这条不用配网络，但依赖官方远程任务能力，版本差异不保证；而且它同步的是消息/产物通道，**不是**逐请求 token 明细的自动同步——本质还是让对端执行脚本。能直连就直连。

### 多设备积分的精度，别自欺

合并后的积分是**各设备本地 `credit_json` 之和，不等于账号云端账单**。某台设备日志被清理、导出周期不全、或请求发生在网页/移动端时都会漏记。想校总账，拿官网导出的积分明细对照；那个数是账号级的，但换不来四段 token。

---

## 看板里有什么

**01 · 日历热力图** — 月视图 / 全部时间（近 13 周），可切月，点某天直接下钻。色阶可切 Token / 积分 / API 金额。

**02 · 模型分布** — 默认**按天**：每天一根堆叠柱，按模型着色，一眼看出哪天用了哪个模型；一键可切回 **0–24 时**视图。两种粒度都支持 Token / 积分 / API ¥ 三种度量切换，点柱体下钻到当天（或该小时），点图例按模型筛选。日期多时图表横向滚动，X 轴标签自动抽稀。

**03 · 三级下钻** — 面包屑逐层返回：

```
月整体 → 某天 → 某会话 → 某次请求 → 单次 API 调用（四段 token × 四段单价 → 小计）
```

支持搜索、列排序、CSV 导出。单次调用详情会展开该模型的四段牌价与逐段金额。**多设备合并时**顶部出现设备下拉筛选，下钻表多一列「设备」（多台时显示数量），CSV 也带设备列。

**04 · API 直购价**

- 主金额卡：`同用量 API 直购价 = Σ 每次调用 (未命中输入×P_miss + 输出×P_out + 缓存命中×P_hit + 缓存写入×P_write) ÷ 1e6`
- **按模型的 API 花费** TOP 8 横条
- **四段 token 花费构成**：用同一份牌价把金额拆回未命中输入 / 输出 / 缓存命中 / 缓存写入，合计与主金额一致
- 16 个模型的厂商牌价、来源链接与核验状态
- 牌价覆盖率（不足 100% 会明确警告，未覆盖 token 不假装是 0 元）
- 积分口径说明：只作官方账单用量指标，不参与金额计算；账单积分按调用权重分摊，保证任何下钻层级加总一致

**05 · 打开方式** — 一键快照 / 本地实时服务 / 多设备自动拉取 / 可选定时任务的命令速查。

---

## 计费口径（重要，别误读）

1. **一次 API 调用** = JSONL 里一条带 `rawUsage` 的记录，按 `providerData.messageId` 去重。
2. **一次用户请求** = `conversationRequestId`，一轮 Agent 循环可能含几十次 API 调用。
3. **官方积分**优先取 `credit_json`；没有账单记录时回退到该轮 `rawUsage.credit` 之和，并在表格里标「日志回退」。
4. 账单积分与逐调用日志累计通常有差额（本机样本约 8.7%）。看板把账单积分**按调用权重分摊**回每条记录，保证任何下钻层级的积分加总都等于官方总额。
5. **四段 token** 归一化规则见 [`scripts/collect.py`](scripts/collect.py) 的 `segments()`。
6. **DeepSeek 峰谷**：按单条调用时间戳，工作日北京时间 09:00–12:00 / 14:00–18:00 为峰时，其余谷时，周末全天谷时；分别计价。
7. **缓存写入**：除 Kimi K3 系列外多数厂商不单列，按未命中输入同价保守计入；本机样本该段恒为 0。

### 价格来源

`config/pricing.json` 是 2026-11-06 的快照，每条都带 `source` 与 `verified`：

- **官方核验**：DeepSeek、智谱 AI、MiniMax、Kimi、阶跃星辰、腾讯混元（Hy4 发布价）
- **推定 / 第三方**：`space-bunny`（官方已认领为 MiniMax-M3.1-Flash 早期匿名版）、`mimo-v2.6-pro`（USD→CNY 折算）、`hy3`（第三方汇总）、`minimax-m3-pay`（内部别名）

积分规则见[官方积分文档](https://www.codebuddy.cn/docs/workbuddy/Credits)，但本看板**不用它算钱**：官方未公布逐模型四段积分单价，`config/pricing.json` 里也不含任何套餐价格。腾讯云公开的「Credits/Million tokens」表属于企业 / 国际 Token Plan 口径，与国内个人版积分反算差 3–15 倍，同样不采用。

**所有金额都是估算，不是账单。** 厂商牌价会变，改 `config/pricing.json` 后重新跑 `run.py` 即可。

---

## 隐私

- 采集脚本**只读**本机文件，不发起任何网络请求。
- 默认会在 HTML 里内嵌每条用户请求的前 140 字提示词摘要，方便下钻时认出是哪次任务。
- **上传资料库、发链接、提交到公开仓库之前，务必用 `--no-prompts`，并确认 `output/` 已被 `.gitignore` 排除。**
- 仓库里的 `examples/sample-dashboard.html` 由 `scripts/make_sample.py` 用合成数据生成，不含任何真实用量。

---

## 安装为 Skill（可选）

`python scripts/install.py` 会把仓库同步到 `~/.workbuddy/skills/workbuddy-token-dashboard/`。在 WorkBuddy 里启用后，可以用「帮我看看 token 消耗」之类的话触发生成看板。

**但看板本身不依赖 Skill，也不依赖自动任务**：双击 `open-snapshot.bat` 或 `start-live.bat` 就行。

如果你确实想要「每天自动留一份到资料库」，可以手动创建一个每天 09:00 的自动化，执行：

```
python scripts/run.py --no-prompts
```

然后把新生成的 HTML 上传到资料库。注意资料库上传每次会新建条目，天天传会堆一坨快照文件，所以本项目默认**不创建**这个任务。

不逆向修改客户端菜单——客户端一升级菜单就没了。细节见 [`SKILL.md`](SKILL.md)。

---

## 目录

```
├── SKILL.md                     WorkBuddy Skill 定义与安装/定时指令
├── README.md
├── LICENSE                      MIT
├── config/
│   └── pricing.json             各厂商 API 牌价 + 来源（不含套餐 / 积分折算）
├── open-snapshot.bat            一键：重算快照 + 浏览器打开
├── start-live.bat               一键：启动本地实时服务 + 打开浏览器
├── export-device.bat            每台设备双击：导出便携包到同步盘
├── start-multi.bat              主设备双击：汇总同步盘中的多设备数据
├── start-peers.bat              主设备双击：自动拉取在线对端（推荐）
├── deploy/                      另一台设备用的部署说明与双击入口
│   ├── PUBLISH-BUNDLE.bat       一键：导出 + 上传资料库固定节点（自动化任务也跑这条）
│   ├── SETUP-AUTOMATION.txt     粘到另一台设备 WorkBuddy 会话，创建每天 09:00 的任务
│   ├── START-NODE.bat           启动只读节点服务（自动找 WorkBuddy 自带 Python）
│   ├── EXPORT.bat               一次性导出（不需要常驻服务）
│   ├── README.txt / PASTE-TO-WORKBUDDY.txt
├── config/peers.example.json    直连对端清单模板（另存 peers.json，含密钥不入库）
├── config/library-sync.example.json  资料库同步模板（另存 library-sync.json，不入库）
├── scripts/
│   ├── collect.py               只读采集，支持多源 / 设备前缀 / 去重（暴露 collect_from_sources 等）
│   ├── export.py                单设备导出便携包（默认剔除提示词）
│   ├── peers.py                 从在线对端 GET /api/bundle 并落盘（含离线跳过）
│   ├── library_io.py            封装资料库内置脚本（路径探测 / 列举 / 上传 / 下载）
│   ├── publish_bundle.py        对端一键：导出便携包 + 原地覆盖资料库固定节点
│   ├── library_sync.py          主设备：列举资料库文件夹 → 下载 → 校验 → 落盘
│   ├── remote_stats.py          命令行统计远端包（文本 / JSON / CSV，含同源检测）
│   ├── build_deploy_kit.py      打包另一台设备用的 ZIP（注入 folder_id，不含本机数据）
│   ├── build_download_page.py   生成内嵌 ZIP 的资料库下载页（绕开 .zip 上传缺陷）
│   ├── push_deploy_kit.py       一键：密钥→配置→打包→下载页→安全自检→对端命令
│   ├── keep_online.py           常驻守护，node/main 两种模式，退出自动重启
│   ├── render.py                注入数据 → 单文件 HTML（同时暴露 render_html）
│   ├── serve.py                 本地 HTTP 服务，打开即最新、源数据/同步盘变化自动重载
│   ├── run.py                   一键刷新快照（--open 直接打开）
│   ├── install.py               同步到用户级 Skill 目录
│   └── make_sample.py           生成脱敏合成示例
├── assets/
│   └── template.html            零依赖看板（CSS + 原生 JS + SVG 图表）
├── config/pricing.json
├── examples/sample-dashboard.html
├── tests/test_collect.py
└── output/                     （被忽略）本机真实数据
```

## 测试

```bash
python -m unittest discover -s tests -v
```

## 已知局限

- 单设备模式只覆盖本机残留的会话日志；被清理、未落盘的数据不在内。多设备模式靠各设备主动导出便携包，没导出的设备不会凭空出现。
- 多设备合并的积分是各设备本地账单之和，不是账号云端账单；官网导出的积分明细可校总账但不含四段 token。
- 模型 ID 是 WorkBuddy 内部标识，与厂商对外模型名可能不完全一致；匿名 / 别名模型按推定映射。
- 赠送积分有效期、峰谷规则历史变更、限时免费活动等未逐条建模，金额是近似值。
- 客户端数据结构是内部实现，版本升级后可能变化；采集脚本对字段做了兼容与去重，但不保证永远有效。

## License

MIT — 见 [LICENSE](LICENSE)。
