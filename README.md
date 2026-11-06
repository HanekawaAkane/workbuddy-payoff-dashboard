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

```bash
git clone https://github.com/<your-name>/workbuddy-token-dashboard.git
cd workbuddy-token-dashboard

python scripts/run.py          # 采集 + 渲染，输出到 output/
```

打开 `output/token-dashboard-<时间戳>.html` 即可。HTML 内嵌全部数据与样式，断网、拷到别的机器、发邮件都能看。

```bash
python scripts/install.py      # 安装为 ~/.workbuddy/skills/ 下的 Skill
python scripts/run.py --no-prompts   # 剔除提示词摘要，适合对外分享 / 上传资料库
python scripts/make_sample.py       # 用合成数据重新生成示例看板
```

非默认数据目录：`python scripts/run.py --home "D:/somewhere/.workbuddy"` 或设环境变量 `WORKBUDDY_HOME`。

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

## 安装为 Skill 与定时自动更新

`python scripts/install.py` 会把仓库同步到 `~/.workbuddy/skills/workbuddy-token-dashboard/`。在 WorkBuddy 里启用后，可用「帮我看看 token 消耗」之类的话触发生成看板。

首次安装时 Skill 会引导创建每天 09:00 的自动化任务，流程：

1. `python scripts/run.py --no-prompts`
2. 生成 `output/token-dashboard-<时间戳>.html`
3. 上传到 WorkBuddy 资料库，软件界面直接点开，不用翻会话记录

**不逆向修改客户端菜单**——客户端一升级菜单就没了。定时任务 + 资料库是稳定方案。细节见 [`SKILL.md`](SKILL.md)。

---

## 目录

```
├── SKILL.md                     WorkBuddy Skill 定义与安装/定时指令
├── README.md
├── LICENSE                      MIT
├── config/
│   └── pricing.json             厂商牌价 + WorkBuddy 套餐 + 来源
├── scripts/
│   ├── collect.py               只读采集 → output/data.json
│   ├── render.py                注入数据 → 单文件 HTML
│   ├── run.py                   一键刷新
│   ├── install.py               同步到用户级 Skill 目录
│   └── make_sample.py           生成脱敏合成示例
├── assets/
│   └── template.html            零依赖看板（CSS + 原生 JS + SVG 图表）
├── examples/
│   └── sample-dashboard.html    合成数据示例看板
├── tests/
│   └── test_collect.py
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
