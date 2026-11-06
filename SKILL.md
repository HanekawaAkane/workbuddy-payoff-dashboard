---
name: workbuddy-token-dashboard
description: 生成 WorkBuddy 本地 token / 积分用量看板。包含日历热力图、0-24 时模型分布、月→日→会话→请求→单次 API 调用的三级下钻、官方积分账单与「平台内积分折算 / 平台外厂商 API 牌价」两种价格对比。当用户询问 token 消耗、积分消耗、用量统计、模型花费、成本对比、生成/刷新用量看板时使用。触发词：token 看板、token 消耗、积分消耗、用量统计、模型花费、成本对比。
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
- `scripts/collect.py` — 只读采集；暴露 `collect_data()` / `source_signature()` 供服务复用
- `config/pricing.json` — 厂商牌价 + WorkBuddy 套餐
- `assets/template.html` — 零依赖看板模板（纯 CSS + 原生 JS + SVG 图表）
- `scripts/render.py` — 注入数据生成单文件 HTML；暴露 `render_html()`
- `scripts/serve.py` — 只绑 127.0.0.1 的本地服务，打开即最新、自动重载、`/api/data` 原始 JSON
- `scripts/run.py` — 一键刷新快照，`--open` 直接打开浏览器
- `scripts/install.py` — 把仓库同步安装到 `~/.workbuddy/skills/`
- `README.md` — 口径、隐私、开源说明

## 隐私

数据只从本机读取，不会外传。生成的 HTML 内嵌了聚合用量数据和（默认）提示词摘要；**上传到资料库或发给别人之前务必用 `--no-prompts`**。
