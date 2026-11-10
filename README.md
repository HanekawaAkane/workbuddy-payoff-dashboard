# WorkBuddy Payoff Dashboard

> **「得吃面板」— see the value your WorkBuddy sessions generated.**<br>
> 一个本地优先、零依赖的单文件 HTML 看板，把 WorkBuddy 的逐次调用换算成「同用量 API 直购价」。<br>
> **金额是按厂商公开 API 牌价计算的估算，不是账单，也不是实际收入。**

[公开仓库](https://github.com/HanekawaAkane/workbuddy-payoff-dashboard) · [合成数据示例](examples/sample-dashboard.html) · [MIT License](LICENSE)

`Python 3.9+ / 无第三方依赖 / 离线可用 / 本地只读 / 不创建定时任务`

---

## 为什么叫 Payoff

没有直译成 `Earnings Dashboard`。那会让人误以为拿到了真金白银的收入，蠢而且不准确。

`Payoff` 表达的是「这波用量到底换回了多少价值」，更贴近「得吃」的情绪：你付出的是 WorkBuddy 里的请求，看到的是这些请求若按厂商公开牌价直购 API，大致值多少钱。官方积分只作为账单用量指标展示，**不折人民币、不乘套餐单价、不计算平台内外倍率**。

---

## 它解决什么问题

WorkBuddy 客户端不提供逐请求的用量明细，但本机留了两类数据：

| 数据 | 位置 | 内容 |
| --- | --- | --- |
| 会话日志 | `~/.workbuddy/projects/**/*.jsonl` | 每次模型 API 调用的 `providerData.rawUsage`，含四段 token |
| 官方积分账单 | `~/.workbuddy/workbuddy.db :: session_usage.credit_json` | 每个用户请求实际扣了多少积分 |

两者通过 `conversationRequestId` 关联。看板用官方账单校准积分，用逐调用日志算厂商牌价，两条路径互不干扰。

**唯一金额口径：**

```text
API 直购价 = Σ 每次调用 (
    未命中输入 × P_miss +
    输出       × P_out  +
    缓存命中   × P_hit  +
    缓存写入   × P_write
) / 1,000,000
```

牌价与来源写在 [`config/pricing.json`](config/pricing.json)。DeepSeek 按调用时间戳区分工作日峰时/谷时。牌价过期就改这个文件，不要在代码里硬编码。

---

## 先看效果

直接打开 [`examples/sample-dashboard.html`](examples/sample-dashboard.html)。这是 `scripts/make_sample.py` 用合成数据生成的脱敏示例，不含任何真实用量或提示词。

看板包含：

- **历史总花销**：顶部固定展示全部时间、全部设备的累计 API 直购价估算（不随筛选变化），并给出当前视图占历史总额的比例；**00 节**按模型 / 按月份拆解这笔累计金额。金额不是账单，也不是实际收入。
- **01 日历热力图**：月视图 / 全部时间近 13 周，点某天下钻；Token / 积分 / API 金额三种色阶。
- **02 模型分布**：按天或 0–24 时的模型堆叠柱，点柱体下钻，点图例筛选模型。
- **03 逐级下钻**：月 → 日 → 会话 → 请求 → 单次 API 调用；支持搜索、排序、分页、CSV 导出和四段单价明细。
- **04 API 直购价**：主金额卡、模型 TOP 8、四段 token 花费构成、厂商牌价表、覆盖率与口径说明。
- **05 打开方式**：快照、本地服务、多设备汇总的命令速查。

大表默认每页 50 行，可切 100 / 200 行；筛选结果与聚合结果按轮复用，搜索带防抖，视图偏好保存在浏览器本地。

---

## 快速开始

```bash
git clone https://github.com/HanekawaAkane/workbuddy-payoff-dashboard.git
cd workbuddy-payoff-dashboard
```

需要 Python 3.9+，不需要 `pip install`。

### 方式 A：一键快照

Windows 双击 `open-snapshot.bat`，或：

```bash
python scripts/run.py --open
```

它会重算一次，把数据写死进 `output/token-dashboard-latest.html`，然后打开浏览器。之后就是快照；想看新数据再运行一次。

### 方式 B：本地实时服务（推荐）

Windows 双击 `start-live.bat`，或：

```bash
python scripts/serve.py --open
```

打开 <http://127.0.0.1:8765/>。

- 只监听 `127.0.0.1`，只读本机文件，不联网、不写回数据源。
- 用完整结构指纹识别日志新增、追加、删除和同步盘回滚。
- 进程内按文件缓存解析结果，只重读变化的 JSONL、数据库/WAL 和便携包。
- 数据变化在后台重算，状态请求不会被采集阻塞；更新完成后页面自动重载。
- `/api/status` 返回刷新状态、耗时和缓存统计；`/api/data` 返回原始 JSON。
- HTML / JSON / 便携包在客户端支持时自动 gzip。
- 缓存只在当前进程内；重启服务会重新扫描一次。

`Ctrl+C` 停止。把地址存成浏览器书签就是固定入口。

### 对外分享前

```bash
python scripts/run.py --no-prompts
```

默认 HTML 会内嵌每条用户请求前 140 字的提示词摘要。**上传资料库、发给别人、提交到公开仓库之前一律加 `--no-prompts`**。

---

## 静态页面为什么不能自己变新

`file://` 打开的 HTML 不能读 `~/.workbuddy/projects/**` 或 `workbuddy.db`。「数据写死进 HTML」和「打开即最新」互斥。

要让页面变新，必须有浏览器外的进程重写一次：

| 方案 | 谁触发 | 代价 |
| --- | --- | --- |
| 一键快照 `open-snapshot.bat` | 你双击时 | 不双击就是旧数据 |
| 本地服务 `serve.py` | 每次打开页面自动检查 | 需要一个常驻进程 |
| 定时任务 | 每天固定时间 | 当天中途的数据看不到，且容易堆积快照 |

本项目主推前两个。定时任务只是可选项，不是查看看板的前提。

---

## 多设备汇总

`~/.workbuddy/` 每台机器一份。WorkBuddy 小程序显示的「在线」只是心跳；官方多端协同把指令路由回在线桌面端，并没有逐请求四段 token 的云端同步表。官网积分明细可校总账，但不含模型和四段 token，画不出堆叠图。

所以别幻想云端自动同步，用本地汇集：

### 1. 同步盘便携包

每台设备导出：

```bash
python scripts/export.py --device laptop --out "D:/Sync/wb-devices/laptop.json"
```

主设备汇总：

```bash
python scripts/serve.py --sources "D:/Sync/wb-devices" --open
python scripts/run.py   --sources "D:/Sync/wb-devices" --open
```

便携包默认不含提示词；`sid` 加 `<设备名>::` 前缀，按调用唯一键去重。给了 `--sources` 且没显式 `--home` 时默认不带本机，要一起算加 `--with-local`。

**同一台机器被导出成不同设备名时会双计。** 例如本机同时以 `本机` 读取本地日志、又留着一份 `LAPTOP-P2H87FP2.json` 便携包，两批 UID 只差设备前缀，默认去重认不出来。把 `config/device-aliases.example.json` 复制成本机私有的 `config/device-aliases.json`，填：

```json
{"aliases": {"LAPTOP-P2H87FP2": "本机"}}
```

采集时会先把别名源规范成 `本机::`，再按 UID 去重；本地最新日志会保留，旧包里的重复调用被跳过。该配置含本机名，不入库、不进部署包。

### 2. 资料库固定节点（推荐）

适合两台设备不总同时在线：

- 本机：`python scripts/push_deploy_kit.py`
- 另一台：解压部署包后双击 `deploy/PUBLISH-BUNDLE.bat`，或把 `deploy/SETUP-AUTOMATION.txt` 粘进那台设备的 WorkBuddy 会话，创建每天 09:00 的自动化。
- 主设备：`python scripts/keep_online.py --mode main`，或 `python scripts/serve.py --library-sync config/library-sync.json`。

每台设备固定一个 `.token-bundle.json` 节点，按标题找到同名 drive 节点后原地覆盖，节点 ID 不变，不会每天堆快照。主设备服务内建轮询，**不需要定时任务**。

注意：资料库 drive 通道只收 `.json`，`.zip` / `.html` 会变成空壳 web 节点。部署包 ZIP 必须通过 `scripts/build_download_page.py` 内嵌到 HTML 下载页再上传。

### 3. 设备间直连（备选）

两台同时在线且网络互通时使用：

```bash
python scripts/push_deploy_kit.py --peer-url http://192.168.1.23:8765 --peer-name laptop
python scripts/serve.py --peers config/peers.json --open
```

主设备每 60 秒拉取 `/api/bundle`，对端离线跳过、上线自动补；内容未变不写盘，变化落地时原子替换。`/api/bundle` 用 `--token` 鉴权，非回环监听强制不含提示词。**不要把 8765 映射到公网。**

资料库同步、直连部署、同源检测的完整说明见 [`SKILL.md`](SKILL.md)。

---

## 计费口径，别误读

1. 一次 API 调用 = JSONL 中一条带 `rawUsage` 的记录，按 `providerData.messageId` 去重。
2. 一次用户请求 = `conversationRequestId`，一轮 Agent 循环可能含几十次 API 调用。
3. 官方积分优先取 `credit_json`；缺失时回退到该轮 `rawUsage.credit` 之和，并在表格里标「日志回退」。
4. 账单积分按调用权重分摊回逐次记录，保证任意下钻层级的积分加总一致。
5. 四段 token 归一化见 [`scripts/collect.py`](scripts/collect.py) 的 `segments()`。
6. 缓存写入多数厂商不单列收费，按未命中输入同价保守计入。
7. 牌价覆盖率不足 100% 时会明确警告，未覆盖 token 不假装是 0 元。

官方积分只是用量指标。所有金额都是按公开牌价的估算，**不是账单、不是收入、不代表 WorkBuddy 官方计费**。模型 ID 是 WorkBuddy 内部标识，与厂商对外名称可能不完全一致；厂商调价、限免活动、赠送额度均未逐条建模。

---

## 隐私

- 采集脚本只读本机文件，不发起网络请求。
- 默认快照内嵌提示词摘要；对外发布一律 `--no-prompts`。
- `output/`、`config/peers.json`、`config/library-sync.json`、`config/library-target.json` 和 `.workbuddy/` 都在 `.gitignore` 中，不进公开仓库。
- `examples/sample-dashboard.html` 是合成数据。
- 本地服务只绑回环地址；直连模式需要共享密钥时，密钥由脚本生成并留在本地配置文件，不要贴到聊天或公开页面。

这是非官方的个人工具，不隶属于 WorkBuddy 或腾讯，也不修改客户端。

---

## 目录

```text
├── assets/template.html          零依赖单文件看板模板
├── config/pricing.json           厂商 API 牌价、来源与核验状态
├── examples/sample-dashboard.html 合成数据示例
├── scripts/
│   ├── collect.py                只读采集、四段 token、官方积分、API 金额
│   ├── export.py                 单设备便携包导出
│   ├── serve.py                  本地实时服务与增量缓存
│   ├── run.py                    一键生成快照
│   ├── render.py                 注入数据生成 HTML
│   ├── install.py                安装为用户级 WorkBuddy Skill
│   ├── make_sample.py            生成脱敏合成示例
│   ├── peers.py / library_sync.py / publish_bundle.py   多设备同步
│   ├── push_deploy_kit.py / build_deploy_kit.py        跨设备部署包
│   ├── remote_stats.py           命令行统计与同源检测
│   └── keep_online.py            常驻守护
├── tests/test_collect.py         标准库单元测试
├── open-snapshot.bat             一键快照
├── start-live.bat                一键实时服务
├── export-device.bat             一键导出便携包
├── start-multi.bat / start-peers.bat  多设备入口
└── deploy/                       另一台设备用的双击入口与自动化说明
```

Skill 内部名仍为 `workbuddy-token-dashboard`，避免破坏已有安装；对外项目名和 GitHub 仓库名是 `WorkBuddy Payoff Dashboard`。

---

## 开发

```bash
python -m unittest discover -s tests -v
python scripts/make_sample.py
python scripts/run.py --no-prompts
```

改牌价时同步更新 `config/pricing.json` 的 `source` 与 `verified` 字段，不要只改数字。对外 HTML 一律 `--no-prompts`。

## 已知局限

- 只覆盖本机仍残留的会话日志；被清理、未落盘的数据不在内。
- 多设备合并积分是各设备本地账单之和，不等于账号云端账单；网页端请求可能漏记。
- 客户端数据结构是内部实现，版本升级后可能变化；脚本做了字段兼容与去重，但不保证永远有效。
- 金额是近似值，不能用于报销、对账或财务决策。

## License

MIT — 见 [LICENSE](LICENSE)。
