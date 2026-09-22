# 数据流水线：从数据到页面的完整闭环

## 概述

本项目的运转是一条**端到端闭环**：人工维护的政策数据 → CI 自动检测政策页变化 → 构建校验 → 部署到 GitHub Pages → 页面展示并提示"待核实" → 本地核实后回写数据 → 重新进入下一轮。

```
   ①数据层(人工真源)        ②检测层(CI 每周一)        ③构建/校验(CI)
  site/data/*.json     ──▶  check_updates.py    ──▶  gen_data_bundle.py
   products.json            抓取+去噪+比对+落快照       gen_docs.py
   policies/{id}.json       生成 update_status        生成 bundle.json
        ▲                   生成 pending 队列               │
        │                         │                         ▼
        │                         │                  ④部署(GitHub Pages)
        │                         │                  deploy.yml 发布 site/
        │                         ▼                         │
        │                ⑤展示层(site/index.html)  ◀────────┘
        │                  app.js 读 bundle + update_status
        │                  渲染表格 / 监控 banner
        │                         │
        │                         ▼ (人看到"待核实"告警)
        │                ⑥核实层(本地 agent + 人工)
        │                  policy_verify.py 出 diff
        │                  判断实质变更 vs 噪声
        │                         │
        └───实质变更:改 policies/{id}.json(人工确认后)──┘
             噪声:修 extract_text 去噪 + 重新基线
             收尾:--resolve 清队列 + 清 banner
```

各阶段使用的脚本、产物与衔接关系如下。

## ① 数据层：唯一真源（人工维护）

| 文件 | 作用 |
| --- | --- |
| `site/data/products.json` | 产品 ID 索引（决定展示顺序）与 `meta` 信息 |
| `site/data/policies/{id}.json` | 单产品政策分析：`versions.toc` / `versions.tob` 的训练、留存、退出、风险字段，`key_clauses` 原文引文，`last_verified`，`timeline`，以及监控配置（目标 URL、`fetch_method`） |

这一层**只由人工或经人工确认后修改**，是后续所有展示与比对的源头。

## ② 检测层：`scripts/check_updates.py`（CI 每周一 09:00 北京时间）

- **触发**：`.github/workflows/monitor.yml`，`cron: "0 1 * * 1"`，也支持 Actions 页面手动触发。
- **范围**：每个产品的每个监控目标 `main`（主页面）/ `toc`（个人版条款）/ `tob`（企业版条款）。
- **流程**：抓取页面 → `extract_text` 去噪 → 空白归一化 → 计算 SHA256 → 与基线快照 `snapshots/{id}/{key}/latest.txt` 比对。

去噪是避免误报的关键，脚本按序剔除：UI 控件短语、阿里云推荐挂件、页脚站壳、帮助中心文末 UI 尾巴（含推荐阅读区块）、正文之前的站点导航（带位置护栏，避免误删条款）、以及 16 位以上的旋转型数字令牌（会话/反伪造标识）。

| 判定 | 含义 | 副作用 |
| --- | --- | --- |
| `ok` | 文本与基线一致（或服务端返回 304） | 无 |
| `changed` | 文本发生变化 | 写入 `latest.txt`，旧内容转存 `prev.txt`，另存 `{YYYY-MM-DD}.txt` 存档 |
| `suspicious` | 正文过短，疑似 JS 渲染或反爬空壳 | **不建立基线**，避免污染后续比对 |
| `failed` | 请求失败/超时 | 不误报为"已变更" |
| `skipped` | 该产品未启用监控 | — |

被 Cloudflare 等拦截的产品走无头浏览器抓取（`fetch_method: "browser"`，CI 会安装 Playwright）。

**产出三件套**（由 bot 自动 commit 回 main）：

| 产物 | 用途 |
| --- | --- |
| `site/generated/update_status.json` | **网页告警的唯一数据源**：每产品聚合状态 + 各目标明细 + `meta` 计数 |
| `site/generated/snapshots/**` | 正文快照，跨环境共享的持久基线与历史，核实阶段用来做 diff |
| `site/generated/pending_verification.json` | 待核实队列：检测 → 核实的跨轮交接物（合并式，只增不减，直到显式 `--resolve`） |

## ③ 构建与校验：`.github/workflows/ci.yml`

每次 PR 或 push 到 main 触发，依次执行：

1. `python -m unittest discover -s tests`（回归测试）
2. `scripts/validate_data.py`（数据结构完整性校验）
3. `scripts/gen_readme_table.py --check`（README 汇总表与数据一致）
4. `scripts/gen_docs.py --check`（文档页为最新）

校验通过后，`publish` job 生成并提交产物：

- `scripts/gen_data_bundle.py` → `site/generated/bundle.json`：把索引与全部政策合并为单个请求（首页优先加载，白名单裁剪后约 20KB）
- `scripts/gen_docs.py` → `site/docs/*.md` 渲染为 `.html`（`.md` 为唯一源，避免两份手工副本漂移）

## ④ 部署：`.github/workflows/deploy.yml` → GitHub Pages

- 采用 `workflow_run` 监听「数据校验」「政策更新监控」完成，而**不是**监听 push —— 因为 bot 使用 `GITHUB_TOKEN` 提交不会触发 push 事件，改用 `workflow_run` 才能覆盖 bot 提交的产物。
- 部署时现场生成社交分享卡片（`gen_og_image.py`，并显式安装 Noto CJK 字体以免中文变豆腐块），然后只上传 `site/` 作为站点根。

## ⑤ 展示层：前端读取什么

| 读取文件 | 用途 |
| --- | --- |
| `generated/bundle.json`（优先，缺失时回退 `products.json` + `policies/*.json`） | 对比表格、筛选、顶部指标 |
| `generated/update_status.json` | 监控 banner「⚠️ 政策监控于 X 检测到 N 个…待人工核实」，以及顶部「数据最后更新日期」（取 `meta.last_run`，缺失时回退 `products.json` 的静态字段） |
| `data/policies/{id}.json`（详情页 `detail.js`） | 单产品详情与长条款原文 |

注意：前端**不读取** `pending_verification.json`，该文件只服务于本地核实流程。

## ⑥ 核实层：`skills/policy-change-verify`（本地 agent + 人工）

- **触发**：维护者看到页面 banner，或主动要求核实某个产品的变更。
- **脚本**：`skills/policy-change-verify/scripts/policy_verify.py`（从仓库根目录运行）

```bash
# 列出待核实队列与被标记的产品/目标
python3 skills/policy-change-verify/scripts/policy_verify.py --list
# 查看单个产品的某个目标（输出旧→新 diff 与当前政策 JSON）
python3 skills/policy-change-verify/scripts/policy_verify.py <product_id> [target]
# 核实收尾：清除队列项 + 清除页面告警
python3 skills/policy-change-verify/scripts/policy_verify.py --resolve <product_id> [target]
```

旧快照按 `prev.txt` → 日期存档 → git 历史依次回溯，并自动跳过"内容相同的重基线提交"，避免全库重建基线造成的假差异。

**判断变更性质**：

- **实质性变更**（训练政策、留存期限、版权归属、责任限制等条款实质变化）→ 起草对 `site/data/policies/{id}.json` 的修改：更新对应字段、`last_verified` 置为当天，必要时向 `timeline` 追加条目。**必须先作为提议交给人工确认再落盘。**
- **噪声**（页脚版权年、cookie 横幅、"最后更新"时间戳、旋转令牌，以及 `failed` / `suspicious`）→ 不修改数据。若属于抓取类噪声（例如页面每次加载都变化的令牌），需修复 `extract_text` 的去噪规则并**重新基线** `latest.txt`，否则下一轮仍会误报。

`--resolve` 会同时清除待核实队列项与 `update_status.json` 中的 `changed` 状态（重算产品级状态与全局计数），使页面告警立即消失——因为页面只读 `update_status.json`，只清队列并不会让告警消失。

核实并回写数据后 push，CI 会重新生成 bundle 并部署，告警消失，**闭环回到 ①**。

## 脚本职责速查

| 脚本 | 阶段 | 职责 |
| --- | --- | --- |
| `scripts/check_updates.py` | ② | 抓取、去噪、哈希比对，写状态/快照/队列 |
| `scripts/validate_data.py` | ③ | 校验数据结构完整性 |
| `scripts/gen_data_bundle.py` | ③ | 生成首页用的 `bundle.json` |
| `scripts/gen_docs.py` | ③ | `docs/*.md` → `.html` |
| `scripts/gen_readme_table.py` | ③ | README 汇总表与数据同步 |
| `scripts/gen_og_image.py` | ④ | 部署时生成社交分享卡片 |
| `scripts/extract_clauses.py` | 人工辅助 | 从协议 HTML 按同义词组提取条款上下文（避免漏掉"优化模型"这类表述） |
| `skills/.../policy_verify.py` | ⑥ | 提取新旧快照 diff + 核实收尾 |

## 两个交接物的区别

`update_status.json` 与 `pending_verification.json` 都记录"待核实"，但服务对象不同：

- `update_status.json`：**每次 monitor 运行整体重算**，是网页告警的数据源。产品状态由目标聚合得出（优先级 `changed` > `failed` > `suspicious` > `ok`）。
- `pending_verification.json`：**跨轮合并式累积**，只入队 `changed`，历史项保留不删，直到本地 `--resolve` 显式清除。它让每周只跑一次的 CI 与本地核实之间可以可靠交接。

二者可能失同步（例如只清了队列而没改状态，页面告警就会一直挂着），因此 `--resolve` 设计为同时处理两者。

## 当前已知问题

1. **skill 文档路径过期**：`skills/policy-change-verify/SKILL.md` 中的命令示例仍指向迁移前的 `.codebuddy/skills/...` 路径，实际目录已迁至仓库根 `skills/`。
2. **队列与告警可能失同步**：历史上曾出现队列被清空但 `update_status.json` 仍标记 `changed` 的情况（页面告警持续显示）。`--resolve` 已覆盖两者，但存量状态需手动对齐。
