# workbuddy-token-dashboard

WorkBuddy 的本地 token / 积分用量看板。一个离线单文件 HTML，日历热力图、0–24 时模型分布、月→日→会话→请求→单次 API 调用的逐级下钻，以及「平台内积分折算」与「平台外厂商 API 牌价」两种价格对比。

同时是一个 WorkBuddy Skill：首次安装可创建每天 09:00 的定时任务，自动刷新并把带时间戳的看板上传到资料库。

> 直接看效果：打开 [`examples/sample-dashboard.html`](examples/sample-dashboard.html)（合成数据，无真实用量）。

---

## 为什么做这个

WorkBuddy 客户端本身不提供逐请求的用量明细。但它在本机留了两类数据：

| 数据 | 位置 | 内容 |
| --- | --- | --- |
| 会话日志 | `~/.workbuddy/projects/**/*.jsonl` | 每次模型 API 调用的 `providerData.rawUsage`，含未命中输入 / 输出 / 缓存命中 / 缓存写入四段 token |
| 官方积分账单 | `~/.workbuddy/workbuddy.db :: session_usage.credit_json` | 每个用户请求实际扣了多少积分 |

两者用 `conversationRequestId` 关联。于是可以做到：积分用官方账单（准确），token 用逐调用日志（可算厂商牌价），两条路径互不干扰。

**和「按模型倍率换算」的做法不同**：官方只公开了客户端面板上的 x0.06 / x0.79 之类倍率，且会随活动和峰谷时段变动，不是计费依据。本项目金额估算走「官方积分 × 套餐单价」，另外用账单做最小二乘反推各模型的实测积分单价作为参考。

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

## 看板里有什么

**01 · 日历热力图** — 月视图 / 全部时间（近 13 周），可切月，点某天直接下钻。色阶可切 Token / 积分 / API 金额。

**02 · 0–24 时模型分布** — 24 根堆叠柱按模型着色，显示峰谷时段占比；点柱体按小时下钻，点图例按模型筛选。

**03 · 三级下钻** — 面包屑逐层返回：

```
月整体 → 某天 → 某会话 → 某次请求 → 单次 API 调用（四段 token × 四段单价 → 小计）
```

支持搜索、列排序、CSV 导出。单次调用详情会展开该模型的四段牌价与逐段金额。

**04 · 积分口径与两种价格**

- `消耗金额估算 = 官方实际积分 × (套餐月价 ÷ 每月实得积分)`
- `同用量 API 直购价 = Σ 每次调用 (未命中输入×P_miss + 输出×P_out + 缓存命中×P_hit + 缓存写入×P_write) ÷ 1e6`

套餐可在页面里实时切换，金额随之重算；也可切「仅基础积分口径」排除限时加赠积分。另外展示：

- WorkBuddy 官方套餐表与 ¥/积分
- 从账单反推的各模型实测积分单价（含 R²）
- 16 个模型的厂商牌价、来源链接与核验状态
- 牌价覆盖率（不足 100% 会明确警告，未覆盖 token 不假装是 0 元）

**05 · 自动更新** — 定时任务说明与命令。

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

套餐价格来自 [WorkBuddy 官方定价页](https://www.codebuddy.cn/docs/workbuddy/Pricing)，积分规则见[官方积分文档](https://www.codebuddy.cn/docs/workbuddy/Credits)。腾讯云公开的「Credits/Million tokens」表属于企业 / 国际 Token Plan 口径，与国内个人版积分反算差 3–15 倍，**本项目不采用**。

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
│   └── pricing.json             厂商牌价 + WorkBuddy 套餐 + 来源
├── open-snapshot.bat            一键：重算快照 + 浏览器打开
├── start-live.bat               一键：启动本地实时服务 + 打开浏览器
├── scripts/
│   ├── collect.py               只读采集 → output/data.json（同时暴露 collect_data / source_signature）
│   ├── render.py                注入数据 → 单文件 HTML（同时暴露 render_html）
│   ├── serve.py                 本地 HTTP 服务，打开即最新、源数据变化自动重载
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

- 只覆盖本机残留的会话日志；被清理、未落盘、其他设备的数据不在内。
- 模型 ID 是 WorkBuddy 内部标识，与厂商对外模型名可能不完全一致；匿名 / 别名模型按推定映射。
- 赠送积分有效期、峰谷规则历史变更、限时免费活动等未逐条建模，金额是近似值。
- 客户端数据结构是内部实现，版本升级后可能变化；采集脚本对字段做了兼容与去重，但不保证永远有效。

## License

MIT — 见 [LICENSE](LICENSE)。
