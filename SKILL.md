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

用户说「看看 token 消耗 / 刷新看板 / 生成用量看板」时：

1. 在本 Skill 目录执行 `python scripts/run.py`（Python 3.9+，无第三方依赖）。
   脚本会跑 `collect.py` → `render.py`，在 `output/` 生成 `token-dashboard-<时间戳>.html` 和 `token-dashboard-latest.html`。
2. 用 `present_files` 打开最新 HTML。
3. 简明汇报：数据范围、总 token、官方积分、平台内估算、API 直购价、两者倍率、牌价覆盖率。
4. 若 `credit_json` 缺失或牌价覆盖率 < 100%，主动说明局限，不要假装数据完整。

对外分享 / 上传资料库时加 `--no-prompts`，剔除提示词摘要：
`python scripts/run.py --no-prompts`

## 首次安装：创建定时自动更新

**只在 Skill 第一次被安装/启用时执行一次。** 先检查是否已存在同名自动化；已存在就不要重复创建。

用 `automation_update` 创建：

- `mode`: `create`
- `name`: `Token 看板每日刷新`
- `scheduleType`: `recurring`
- `rrule`: `FREQ=DAILY;BYHOUR=9;BYMINUTE=0`
- `status`: `ACTIVE`
- `cwds`: 本 Skill 目录的绝对路径
- `prompt`（原样使用，路径替换为实际绝对路径）：

```
在工作目录执行 `python scripts/run.py --no-prompts`，重新采集本机 WorkBuddy 的会话日志与官方积分账单，生成带时间戳的单文件 HTML 看板。
然后用资料库上传工具把 output/ 目录下本次新生成的 token-dashboard-<时间戳>.html 上传到 WorkBuddy 资料库，文件名保留时间戳。
最后用一句话汇报：数据截止日期、总 token、官方积分、平台内消耗估算、同用量 API 直购价、两者倍率。
若采集失败或牌价覆盖率不足 100%，如实说明失败原因，不要编造数字。
```

**为什么这么做**：放弃往 WorkBuddy 客户端菜单里塞入口（客户端一升级就没了），改用「定时任务 + 资料库」——软件界面里点资料库就能看到当天最新看板，不用在会话里喊一句「帮我看看 token」。

## 定时任务执行时

1. 运行 `python scripts/run.py --no-prompts`。
2. 找到本次生成的 `output/token-dashboard-<时间戳>.html`（用文件修改时间判定，别拿旧的）。
3. 用 `LibraryUpload` 工具上传到资料库；若工具不可用，把 HTML 留在 `output/` 并在汇报里说明未完成上传。
4. 汇报关键数字，不要贴大段日志。

## 文件

- `scripts/collect.py` — 只读采集，输出 `output/data.json`
- `config/pricing.json` — 厂商牌价 + WorkBuddy 套餐
- `assets/template.html` — 零依赖看板模板（纯 CSS + 原生 JS + SVG 图表）
- `scripts/render.py` — 注入数据生成单文件 HTML
- `scripts/run.py` — 一键刷新
- `scripts/install.py` — 把仓库同步安装到 `~/.workbuddy/skills/`
- `README.md` — 口径、隐私、开源说明

## 隐私

数据只从本机读取，不会外传。生成的 HTML 内嵌了聚合用量数据和（默认）提示词摘要；**上传到资料库或发给别人之前务必用 `--no-prompts`**。
