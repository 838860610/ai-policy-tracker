# 架构与端到端流程图

> **内部维护文档**，不随站点发布（对外文档在 `site/docs/`，由 `gen_docs.py` 渲染并消毒）。
> 本目录不经过任何渲染管道，可以用 Mermaid / HTML 自由表达。
> 浏览器打开同目录的 [`architecture.html`](architecture.html) 可看带样式的交互版流程图。

## 端到端流程（GitHub 原生渲染）

```mermaid
flowchart TD
    SRC["① 数据层 · 人工唯一真源<br/>site/data/policies/{id}.json + products.json"]
    PAGES["各 AI 产品线上政策页"]

    subgraph ACTIONS["GitHub Actions · 两条工作流（共用写入并发组）"]
        MON["② 监控线 monitor.yml · 每周一 09:00 北京时间 / 手动<br/>check_updates.py --scope ci · 按目标配置选择 requests / browser<br/>抓取 → 提取去噪 → 空白归一化 → 与基线快照全等比对<br/>生成 feed → 可选 webhook（仅本轮新状态）→ rebase 后 bot 提交状态 / 快照 / 队列 / feed"]
        CI["③ 校验线 ci.yml · push / PR / 手动触发<br/>全量回归测试 + validate_data + README / docs / product / feed / api 五项 --check<br/>全绿且为 main push → 先同步最新 main → 生成五类产物 → 复验 → bot 提交"]
    end

    AXIS{"统一判定<br/>status × health"}
    B1["status=changed 且 health=ok → 待核实队列<br/>pending_verification.json<br/>+ 快照存档（prev.txt / 日期档）"]
    B2["health 异常 → 健康队列<br/>monitor_health.json<br/>修抓取配置，不算政策变更"]
    B3["抓取失败 / 空壳 → 绝不覆盖基线<br/>保住历史正文，不误报"]
    B4["monitor_scope=local → CI 不检查<br/>沿用旧状态，仅标 skipped_this_run<br/>本地 local_monitor.sh 跑（commit 不 push，手动 push）"]

    DEPLOY["④ 部署 deploy.yml · workflow_run 触发（限 main）<br/>校验失败不部署 · 监控失败仍部署<br/>OG 社交卡片现场生成 → 发布 site/"]
    SITE["⑤ 展示层<br/>首页读 bundle + update_status + monitor_health<br/>详情页额外读 policies/{id}.json + pending_verification.json + monitor_health.json"]
    VERIFY["⑥ 核实层 · 本地 skill + 人工<br/>skills/policy-change-verify<br/>policy_verify.py diff → 判断 → 改数据 → --resolve"]

    PAGES -->|"按目标配置选 requests / browser；有效基线才接受 304"| MON
    SRC -->|"监控配置 / 目标 URL"| MON
    SRC -->|"gen_*.py 派生产物"| CI

    MON --> AXIS
    AXIS -->|"changed"| B1
    AXIS -->|"health 异常"| B2
    AXIS -->|"failed / suspicious"| B3
    AXIS -->|"local 目标"| B4

    B1 --> VERIFY
    B4 -->|"沿用状态为 changed"| B1
    B4 -->|"沿用状态为 health 异常"| B2
    MON --> DEPLOY
    CI --> DEPLOY
    DEPLOY --> SITE
    SITE -->|"人看到待核实告警"| VERIFY
    VERIFY -->|"实质变更：改 policies/*.json，push 回 main"| SRC
    VERIFY -->|"抓取噪声：修 extract_text 去噪 + 重新基线"| MON

    style ACTIONS fill:none
```

## 分层速览

| 层 | 载体 | 触发 | 详见 |
| --- | --- | --- | --- |
| ① 数据层 | `site/data/policies/{id}.json` | 人工 / 核实回写 | 对外版《数据流水线》 |
| ② 监控线 | `.github/workflows/monitor.yml` → `check_updates.py` | 每周一 09:00 北京 / 手动 | `site/docs/update-monitoring.md` |
| ③ 校验线 | `.github/workflows/ci.yml` | push / PR / 手动 | 对外版《数据流水线》③ |
| ④ 部署 | `.github/workflows/deploy.yml` | workflow_run（两条线完成后） | 对外版《数据流水线》④ |
| ⑤ 展示层 | `site/index.html`、`site/p/{id}.html` | — | 对外版《数据流水线》⑤ |
| ⑥ 核实层 | `skills/policy-change-verify/` | 队列非空 / 人工发起 | 对外版《数据流水线》⑥ |

## 两个容易搞混的判定轴

- **status（变没变）**：`ok` / `changed` / `failed` / `suspicious` / `skipped` —— 只有 `changed` 进待核实队列；
- **health（能不能信）**：`ok` / `initialized` / `rebaselined` / `degraded` / `no_baseline` / `blocked` —— 非 `ok/initialized/rebaselined` 进健康队列，走修抓取配置的路线。

两轴**正交**：同一产品的不同目标可以同时出现 `changed` 与健康异常；单个目标的 `changed` 只与 `health=ok` 同现。`rebaselined` 只与重建后的 `ok`（哈希方案升级）或 `suspicious`（缺基线）同现，**不存在 `changed + rebaselined` 组合**。一次 Cloudflare 挑战只会进健康队列，不会污染"政策是否变化"的判断。抓取失败从不覆盖基线，也不会被当成待核实的政策变更。

浏览器不是自动兜底：仅 `fetch_method: "browser"` 的目标使用 Playwright，其余目标仍用 `requests`。正文提取、去噪、渲染等待与正文下限只能降低漏抓和误报概率，不承诺零漏报；`--no-browser` 与局部重试也不等于完成一轮完整监控。

## 与对外文档的关系

- `site/docs/*.md` 是**对外站点文档**的唯一源，经 `gen_docs.py` 渲染 + sanitize 白名单消毒后发布——所以那边只能用白名单内的标签（表格、代码块、ASCII 图）。
- 本目录是**内部文档**，无消毒、无发布，Mermaid 与 HTML 均可；改动不需要跑 `gen_docs.py`，但涉及对外文档或数据时仍需按 `AGENTS.md` 跑全量校验。
- ⚠️ 仓库 Settings → Pages 若切到 "Deploy from a branch" 并选 `/docs`，会把本目录公开——本项目用的是 Actions 部署 `site/`，**不要切换**。
