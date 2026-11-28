# 数据流水线：从数据到页面的完整闭环

## 概述

本项目的运转是一条**端到端闭环**：人工维护的政策数据 → 两条共用写入并发组的 GitHub Actions 工作流（每周监控检测变化、每次 push 校验构建）→ 部署到 GitHub Pages → 页面展示并提示"待核实" → 本地核实后回写数据 → 重新进入下一轮。

```
 ① 数据层（人工唯一真源，一切展示与比对的源头）
     site/data/policies/{id}.json · products.json
       │
       ├── gen_*.py 派生产物（本地脚本，或 ③ 校验线的 publish 自动重生成）──▶ ③
       └── 提供监控配置与目标 URL ──▶ ②

 ② 监控线 monitor.yml（每周一 09:00 北京时间 / 手动触发）
     输入：各 AI 产品线上政策页（默认 requests + ETag/304；仅配置 browser 的目标用 Playwright）
     check_updates.py --scope ci：抓取 → 提取去噪 → 空白归一化
       → 与基线快照 snapshots/{id}/{key}/latest.txt 全等比对（有效基线才接受 304）
       │  统一判定：status 回答"正文变没变"，health 回答"抓到的能不能信"（正交）
       ├─ changed + health=ok ─▶ 待核实队列 pending_verification.json
       │                     + 快照存档（首次变更前基线固定为 prev.txt，日期档保留每次新版本）→ ⑥
       ├─ health 异常 ─────▶ 健康队列 monitor_health.json → 修抓取配置，不算政策变更
       ├─ 抓取失败/空壳 ───▶ 绝不覆盖基线（保住历史正文，也不误报为变更）
       └─ monitor_scope=local ▶ CI 不检查，沿用旧状态且仅标 skipped_this_run
                              → 本地 local_monitor.sh 跑（commit 不 push，手动 push）
    生成 feed.xml → 可选 webhook（未配置静默跳过，失败不阻断）
    → rebase 后 bot 提交状态 / 快照 / 两个队列 / feed

 ③ 校验线 ci.yml（push / PR / 手动触发，与 ② 共用写入并发组，避免同时提交）
     全量回归测试 → validate_data → README / 文档 / 产品页 / feed / API 五项 --check
     全绿且为 main push → publish：先同步最新 main → 生成五类产物 → 复验 → 按最终差异 bot 提交
     （bot 的 GITHUB_TOKEN 提交不再触发 push 事件，不会死循环）

 ②③ 完成后 ──▶ ④ 部署 deploy.yml（workflow_run 触发，限 main）
     校验失败不部署（数据可能不合法）；
     监控失败仍部署（结果与快照已提交，跳过会让线上停更一周）；
     现场生成 OG 社交卡片 → 发布 site/ 到 GitHub Pages
       │
       ▼
 ⑤ 展示层
     首页读 bundle.json + update_status.json + monitor_health.json；详情页额外读 data/policies/{id}.json + pending_verification.json + monitor_health.json
     首页渲染对比表 / 监控 banner / 抓取降级明细；详情页另渲染待核实 diff 与抓取异常卡片
       │
       ▼ 人看到"待核实"告警
 ⑥ 核实层 skills/policy-change-verify（本地 agent + 人工）
     policy_verify.py 出新旧快照 diff → 判断实质变更 vs 抓取噪声
       ├─ 实质变更：人工确认后修改 policies/{id}.json（字段 + timeline）
       ├─ 抓取噪声：修 extract_text 去噪规则 + 重新基线
       └─ 收尾：--resolve 清队列 + 清页面告警
       │
       ▼ 改动 push 回 main → 重新触发 ③ 校验与 ④ 部署，闭环回到 ①
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
- **范围**：每个产品的每个监控目标 `main`（主页面）/ `toc`（个人版条款）/ `tob`（企业版条款）/ `source_*`（补充来源）。
- **流程**：抓取页面 → 按 HTML/PDF/文本类型提取正文 → 去噪 → 空白归一化 → 与基线快照 `snapshots/{id}/{key}/latest.txt` 的归一化文本做全等比对（SHA256 仅作记录）；若仅中英文边界或中文之间的空白排版不同，则更新基线但不进待核实队列。

去噪是避免误报的关键，脚本按序剔除：UI 控件短语、导航和页脚 DOM、帮助中心文末 UI 尾巴、正文之前的站点导航，以及明确标记为 token/session/nonce 的动态节点；不再全局删除正文中的长数字。

| 判定 | 含义 | 副作用 |
| --- | --- | --- |
| `ok` | 文本与基线一致，或在本地基线有效时服务端返回 304 | 无 |
| `changed` | 可信正文与基线不同，且 `health=ok` | 写入 `latest.txt`；首次变更前基线固定为 `prev.txt`，每次新版本追加日期档（同日追加时间后缀） |
| `suspicious` | 正文过短、疑似 JS 渲染/反爬空壳；或缺基线后完整抓取重建（`health=rebaselined`） | 不把异常当作正常结果；重建基线需人工确认 |
| `failed` | 请求失败/超时 | 不误报为"已变更"；按 `health` 进入健康队列 |
| `skipped` | 未启用监控、URL 为空/待核实、未匹配筛选，或 `--no-browser` 下整产品均需 browser 且无旧状态 | 不等于 local；local 与范围跳过沿用旧状态，仅标 `skipped_this_run` |

`status` 只回答"政策正文变没变"。抓取本身是否可信由正交的 `health` 字段表达：

| health | 含义 | 是否进健康队列 |
| --- | --- | --- |
| `ok` | 正常 | 否 |
| `initialized` | 首次建立基线（不是异常） | 否 |
| `rebaselined` | 缺基线后完整抓取重建（`suspicious`），或哈希方案升级重建（`ok`）；不与 `changed` 组合 | 否 |
| `degraded` | 本轮抓取异常，但保留了上次有效快照 | 是 |
| `no_baseline` | 本轮抓取异常且无可信基线 | 是 |
| `blocked` | 被反爬/限流/拒绝访问（401/403/405/429/451） | 是 |

两者正交的意义：同一产品的不同目标可以同时出现 `changed` 与健康异常；单个目标的 `changed` 只与 `health=ok` 同现。一次 Cloudflare 挑战只会进健康队列，不会污染"政策是否变化"的判断，也不会被当成待核实的政策变更。`rebaselined` 只与 `ok` / `suspicious` 同现，**不存在 `changed + rebaselined` 组合**。

抓取方式可按产品配置，也可只配在单个目标上（`targets.main` / `versions.*` / `sources[]` 条目支持 `fetch_method`、`content_selector`、`wait_for_selector`、`min_body_chars`、`monitor_scope`）。默认使用 `requests`，仅 `fetch_method: "browser"` 的目标使用 Playwright，CI 会安装浏览器依赖；browser 不是自动兜底，提取与渲染策略只能降低漏抓概率，不承诺零漏报。

`--no-browser` 混合产品只检查 `requests` 目标，被省略的 browser 目标沿用旧状态并标 `skipped_this_run`；整产品都需要 browser 时同样沿用旧目标状态，只有没有旧状态时才产品级 `skipped`。`--products` / `--only` 局部重试则合并旧状态，未检查目标标 `skipped_this_run`，且不清理孤儿快照。`--scope local` 会沿用所有非 local 目标且不重置其 checked 标记，只更新 `meta.last_local_run`；`--scope ci` 会沿用所有 local 目标并标 `skipped_this_run`。快照是否活跃按监控配置判定，不因本次跳过误删。

**产出五件套**（由 bot 自动 commit 回 main）：

| 产物 | 用途 |
| --- | --- |
| `site/generated/update_status.json` | **首页监控告警的聚合源**：每产品聚合状态 + 各目标明细（含 `health`）+ `meta` 计数；详情页健康队列缺失时也从中兜底 |
| `site/generated/snapshots/**` | 正文快照，跨环境共享的持久基线与历史，核实阶段用来做 diff |
| `site/generated/pending_verification.json` | 待核实队列：检测 → 核实的跨轮交接物（合并式，只增不减，直到显式 `--resolve`） |
| `site/generated/monitor_health.json` | 抓取健康队列：每轮由状态重建，记录 `health`、失败原因、连续轮次与建议动作；恢复后自动消失 |
| `site/feed.xml` | Atom 订阅源：timeline + 待核实队列，由 `gen_feed.py` 生成；监控轮更新，CI 校验 |


## ③ 构建与校验：`.github/workflows/ci.yml`

每次 PR 或 push 到 main 触发，依次执行：

1. `.venv/bin/python -m unittest discover -s tests`（全量回归测试）
2. `.venv/bin/python scripts/validate_data.py`（数据结构完整性校验）
3. `.venv/bin/python scripts/gen_readme_table.py --check`（README 汇总表与数据一致）
4. `.venv/bin/python scripts/gen_docs.py --check`（文档页为最新）
5. `.venv/bin/python scripts/gen_product_pages.py --check`（产品详情页与 sitemap 为最新）
6. `.venv/bin/python scripts/gen_feed.py --check`（订阅 feed 为最新）
7. `.venv/bin/python scripts/gen_api.py --check`（只读 API 为最新）

校验通过后，`publish` job 先执行 `git pull --rebase origin main` 同步最新真源，再生成五类产物并跑生成后复验；暂存最终文件后仅有差异时才 bot commit + push。生成后不再 rebase，避免把旧产物叠到新真源上；若同步后又有新推送导致 push 失败，本轮不部署：

- `scripts/gen_data_bundle.py` → `site/generated/bundle.json`：把索引与全部政策合并为单个请求（首页优先加载，白名单裁剪后约 32KB）
- `scripts/gen_docs.py` → `site/docs/*.md` 渲染为 `.html`（`.md` 为唯一源，避免两份手工副本漂移）
- `scripts/gen_product_pages.py` → `site/p/{id}.html` + `site/sitemap.xml`
- `scripts/gen_feed.py` → `site/feed.xml`
- `scripts/gen_api.py` → `site/generated/api/v1/`

## ④ 部署：`.github/workflows/deploy.yml` → GitHub Pages

- 采用 `workflow_run` 监听「数据校验」「政策更新监控」完成，而**不是**监听 push —— 因为 bot 使用 `GITHUB_TOKEN` 提交不会触发 push 事件，改用 `workflow_run` 才能覆盖 bot 提交的产物。
- 部署时现场生成社交分享卡片（`gen_og_image.py`，并显式安装 Noto CJK 字体以免中文变豆腐块），然后只上传 `site/` 作为站点根。

## ⑤ 展示层：前端读取什么

| 读取文件 | 用途 |
| --- | --- |
| `generated/bundle.json`（优先，缺失时回退 `products.json` + `policies/*.json`） | 对比表格、筛选、顶部指标 |
| `generated/update_status.json` | 监控 banner「⚠️ 政策监控于 X 检测到 N 个产品政策可能已更新，待人工核实」，以及监控异常统计；顶部“人工核实日期”优先取全部产品 `last_verified` 的最大值，缺失时才回退 `products.json` 的 `meta.last_updated`，不把监控运行时间冒充数据更新时间 |
| `generated/monitor_health.json`（缺失时从 `update_status.json` 的 `health` 兜底推导） | 首页 banner 下方可展开的"抓取降级明细"，以及详情页"政策监控抓取异常"卡片：逐条列出产品、目标、健康类型、失败原因、上次成功抓取时间 |
| `data/policies/{id}.json`（详情页 `detail.js`） | 单产品详情与长条款原文 |
| `generated/pending_verification.json`（详情页 `detail.js`） | “待核实的政策变更”卡片与 diff 片段；文件缺失或请求失败时静默隐藏 |

首页**不读取** `pending_verification.json`，只读 `update_status.json` 的聚合状态；详情页读取 pending 队列与健康队列（缺失时从状态兜底）。pending 队列同时供本地核实、订阅 feed 与 webhook 通知使用。

## ⑥ 核实层：`skills/policy-change-verify`（本地 agent + 人工）

- **触发**：维护者看到页面 banner，或主动要求核实某个产品的变更。
- **脚本**：`skills/policy-change-verify/scripts/policy_verify.py`（从仓库根目录运行）

```bash
# 列出待核实队列与被标记的产品/目标
.venv/bin/python skills/policy-change-verify/scripts/policy_verify.py --list
# 查看单个产品的某个目标（输出旧→新 diff 与当前政策 JSON）
.venv/bin/python skills/policy-change-verify/scripts/policy_verify.py <product_id> [target]
# 核实收尾：清除队列项 + 清除页面告警
.venv/bin/python skills/policy-change-verify/scripts/policy_verify.py --resolve <product_id> [target]
```

旧快照按 `prev.txt` → 日期存档 → git 历史依次回溯，并自动跳过"内容相同的重基线提交"，避免全库重建基线造成的假差异。

**判断变更性质**：

- **实质性变更**（训练政策、留存期限、版权归属、责任限制等条款实质变化）→ 起草对 `site/data/policies/{id}.json` 的修改：更新对应字段、`last_verified` 置为当天，必要时向 `timeline` 追加条目。**必须先作为提议交给人工确认再落盘。**
- **噪声**（页脚版权年、cookie 横幅、"最后更新"时间戳、旋转令牌，以及 `failed` / `suspicious`）→ 不修改数据。若属于抓取类噪声（例如页面每次加载都变化的令牌），需修复 `extract_text` 的去噪规则并**重新基线** `latest.txt`，否则下一轮仍会误报。

`--resolve` 会同时清除待核实队列项与 `update_status.json` 中的 `changed` 状态（重算产品级状态与全局计数）。首页读聚合状态，详情页读 pending 队列，因此两处必须同步清理，告警才会立即消失。

核实并回写数据后 push，CI 会重新生成 bundle 并部署，告警消失，**闭环回到 ①**。

## 脚本职责速查

| 脚本 | 阶段 | 职责 |
| --- | --- | --- |
| `scripts/check_updates.py` | ② | 抓取、去噪、哈希比对，写状态/快照/队列 |
| `scripts/validate_data.py` | ③ | 校验数据结构完整性 |
| `scripts/gen_data_bundle.py` | ③ | 生成首页用的 `bundle.json` |
| `scripts/gen_docs.py` | ③ | `site/docs/*.md` → `.html` |
| `scripts/gen_readme_table.py` | ③ | README 汇总表与数据同步 |
| `scripts/gen_product_pages.py` | ③ | 产品静态详情页与 sitemap |
| `scripts/gen_feed.py` | ②③ | 生成 / 校验 Atom 订阅源 |
| `scripts/gen_api.py` | ③ | 生成 / 校验只读数据 API |
| `scripts/notify_webhook.py` | ② | 监控轮可选 webhook 通知 |
| `scripts/gen_og_image.py` | ④ | 部署时生成社交分享卡片 |
| `scripts/extract_clauses.py` | 人工辅助 | 从协议 HTML 按同义词组提取条款上下文（避免漏掉"优化模型"这类表述） |
| `skills/.../policy_verify.py` | ⑥ | 提取新旧快照 diff + 核实收尾 |

## 三个交接物的区别

`update_status.json`、`pending_verification.json` 与 `monitor_health.json` 都在记录"待处理"，但服务对象不同：

- `update_status.json`：**每次 monitor 运行整体重算**，是网页告警的数据源。产品状态由目标聚合得出（优先级 `changed` > `failed` > `suspicious` > `ok`），并附带 `health` 聚合字段。
- `pending_verification.json`：**跨轮合并式累积**，只入队 `changed`，历史项保留到本地 `--resolve` 显式清除；监控重新检查时会恢复仍未解决的页面告警，避免后续 304 把它隐藏。
- `monitor_health.json`：**每轮由状态完全重建**，只收 `degraded` / `no_baseline` / `blocked`，记录连续不健康轮次与建议动作。目标恢复正常或下线监控后条目自动消失，无需手工清理。

三者通过 `--resolve`、监控重算与健康队列重建保持同步；`pending_verification.json` 损坏时监控会失败关闭，`monitor_health.json` 损坏时按空队列重建（它可从状态完全推导）。

## 当前已知问题

1. **来源覆盖仍需持续维护**：新增产品或补充证据时，应将关键 Help Center、数据授权和隐私政策登记到 `sources[]`，否则相关附属文档变化不会自动告警。
2. **时间线不是自动生成**：产品没有历史事件时详情页不显示时间线，需人工补充重要政策变更。
3. **抓取降级目标需要人工处置**：首页"抓取降级明细"里的目标不会仅靠重复运行自愈，需按 `next_action` 配置 `content_selector` / `fetch_method=browser` 后用 `--only <pid>:<key>` 重试验证；恢复后健康队列条目自动消失。
