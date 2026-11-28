# AGENTS.md

给在本仓库工作的 AI agent（以及接手维护的人）的操作约定与背景速查。

> 术语：项目内"政策"指各 AI 产品的隐私政策 / 服务条款原文。数据源为人工维护的
> `site/data/policies/{id}.json`，页面展示与自动监控都是它的派生物。

---

## 1. 环境与常用命令

**所有 Python 命令必须用项目虚拟环境 `.venv/bin/python`**，不要用系统 `python3`——
新版 Python 禁止直接 pip 装包到系统环境，且系统环境没有 `requests` / `bs4` / `pypdf`。

```bash
./start.sh                       # 首次运行：建 .venv、装依赖、起本地服务（默认 8080）
.venv/bin/python -m pip install -r requirements.txt          # 基础依赖
.venv/bin/pip install -r requirements-browser.txt && .venv/bin/playwright install chromium
                                 # 仅在需要抓 browser 目标（反爬 / JS 渲染）时安装
```

**提交前必须跑的全量校验**（任何改动都跑，约 15 秒）：

```bash
.venv/bin/python -m unittest discover -s tests -q      # 全量回归测试
.venv/bin/python scripts/validate_data.py              # 数据结构校验（0 错 0 警）
.venv/bin/python scripts/gen_readme_table.py --check   # README 汇总表与数据一致
.venv/bin/python scripts/gen_docs.py --check           # 文档页是最新
.venv/bin/python scripts/gen_product_pages.py --check  # 产品详情页与 sitemap 是最新
.venv/bin/python scripts/gen_feed.py --check           # 订阅 feed 是最新
.venv/bin/python scripts/gen_api.py --check            # 只读 API 是最新
```

按改动类型重新生成对应产物（对外文档只跑 `gen_docs.py`；数据 / 页面改动还需其余生成器）：

```bash
.venv/bin/python scripts/gen_docs.py         # site/docs/*.md → *.html（.md 是唯一源）
.venv/bin/python scripts/gen_data_bundle.py  # 生成 site/generated/bundle.json
.venv/bin/python scripts/gen_product_pages.py  # site/detail.html → site/p/{id}.html + sitemap
.venv/bin/python scripts/gen_feed.py         # 生成 site/feed.xml（timeline + 待核实队列，CI --check）
.venv/bin/python scripts/gen_api.py          # 生成 site/generated/api/v1/ 只读 API（CI --check）
.venv/bin/python scripts/gen_og_image.py     # 社交卡片（需 pillow，维护用依赖）
```

**不要手工编辑**：`site/generated/**`（`bundle.json` / `update_status.json` /
`monitor_health.json` / `pending_verification.json` / `snapshots/` / `api/v1/` /
`og-card.png`）、`site/feed.xml`、`site/docs/*.html`、`site/p/*.html` 和
`site/sitemap.xml`——它们都是脚本产物，改了会被 CI 或监控覆盖。

---

## 2. 目录职责

| 路径 | 职责 |
|------|------|
| `site/data/products.json` | 产品 ID 索引（只定展示顺序，不存数据） |
| `site/data/policies/{id}.json` | **唯一人工真源**：政策字段、版本政策、监控配置、timeline |
| `site/` | 站点根（`site/index.html` → `/`），含 `data/` `generated/` `js/` `css/` `docs/` `p/` |
| `site/generated/` | 脚本产物，**入库**（首页与 Pages 直接读取，CI 提交） |
| `site/p/{id}.html` | 每产品独立详情页（`gen_product_pages.py` 产物，入库；含专属 OG/canonical） |
| `scripts/` | 监控与构建脚本（`check_updates.py` 是核心，见下） |
| `skills/policy-change-verify/` | 本地核实 skill：抓新旧快照 diff、起草数据修改、`--resolve` 收尾 |
| `tests/test_scripts.py` | 全部回归测试（单文件，类按关注点分组） |
| `docs/` | **内部维护文档**（架构流程图 mermaid + 交互版 html），不发布、不经 sanitize；对外文档在 `site/docs/`。⚠️ Pages 不要切 "Deploy from branch /docs"，否则内部文档会被公开 |

前端数据读取：首页读 `bundle.json`（缺失时回退索引与逐产品 JSON）、
`update_status.json`、`monitor_health.json`，**不读 pending 队列**；详情页额外读
`data/policies/{id}.json`、`pending_verification.json` 与 `monitor_health.json`
（缺失时从 `update_status.json` 兜底），分别渲染待核实 diff 与抓取异常。

---

## 3. 监控的两套状态（最容易搞混的地方）

监控结果里每个目标有两套**正交**语义，看错会导致误判：

| 字段 | 回答的问题 | 取值 |
|------|-----------|------|
| `status` | 政策正文相对基线**变没变** | `ok` / `changed` / `failed` / `suspicious` / `skipped` |
| `health` | 这一轮**抓到的正文能不能信** | `ok` / `initialized` / `rebaselined` / `degraded` / `no_baseline` / `blocked` |

- 单目标 `status=changed` 只与 `health=ok` 同现 → 进**待核实队列** `pending_verification.json`，走 policy-change-verify skill；
- `health` 非 `ok/initialized/rebaselined` → 进**健康队列** `monitor_health.json`，修抓取配置；
- 同一产品的不同目标可同时需要内容核实与抓取修复；`rebaselined` 只与 `ok`（哈希方案升级）或 `suspicious`（缺基线后完整抓取重建）同现，**不存在 `changed + rebaselined`**；
- **不要**把抓取失败当政策变更。

正文过短或抓取失败时脚本**不会覆盖已有基线**（保住页面展示的历史正文），
只把 `health` 标成降级/无基线/被拦截。

---

## 4. 目标级抓取配置

一个"监控目标（target）"= 一个可独立抓取/比对/重试的 URL，用 `pid:key` 标识。
每个目标有自己的配置载体，优先级 **目标级 > 产品级 > 全局默认**：

| key | 配置载体 | 备注 |
|-----|----------|------|
| `main` | `targets.main` | URL 是顶层 `policy_url`，原本没有内层载体，故用 `targets.main` |
| `toc` / `tob` | `versions.toc` / `versions.tob` | 与业务字段同层 |
| `source_*` | `sources[]` 该条目 | 每条 `sources[]` 就是一个独立监控目标 |

支持的抓取字段（详见 `CONTRIBUTING.md` 与 `skills/policy-change-verify/references/policy_schema.md`）：

- `fetch_method`：`requests`（默认）/ `browser`（playwright，**可选依赖**）
- `content_selector`：CSS 选择器，正文不在 `<main>`/`<article>` 内时指定；命中多个时自动取文本最长的
- `wait_for_selector`：browser 抓取时等该节点出现视为已渲染
- `min_body_chars`：该目标正文下限（默认 500）
- `monitor_scope`：`ci`（默认）/ `local`（仅本地跑，见下）

默认使用 `requests`；**仅配置为 `browser` 的目标**才启用 Playwright，不会在请求失败时
自动兜底。提取、去噪与渲染策略只能降低漏抓 / 误报概率，**不承诺零漏报**。
`--no-browser` 混合产品只检查 requests 目标，被跳过的 browser 目标沿用旧状态；
整产品全 browser 时也沿用旧目标状态，只有从未检查过时才产品级 `skipped`。
`--products` / `--only` 局部重试合并旧状态、标记未检查目标且不清理孤儿快照，
都不等于完成全量监控。`--scope local` 同样必须沿用非 local 目标，不能清空其状态或队列。

---

## 5. 本地专属监控（`monitor_scope: local`）

有些站点 GitHub runner **根本连不上**（`trae`：Cloudflare 拒绝数据中心 IP，
`describe_shell()` 显示"实际拿到：空文档"）。这类目标标记 `monitor_scope: "local"`，
由本地跑、以本地结果为准：

```bash
./scripts/local_monitor.sh                    # 跑全部 local 目标，自动 commit 不 push
./scripts/local_monitor.sh --only trae:main   # 只跑一个
git push origin main                          # 想让首页更新再手动推（触发 Pages 发布）
```

CI 跑 `--scope ci` 不检查它们，但**沿用上次目标结果**（含快照引用与 `last_checked`），
只加 `skipped_this_run` 标记；本地跑 `--scope local` 时反过来沿用所有非 local 目标，
且不把 CI 已检查目标重新标为“本轮未检查”。本地轮次只更新 `meta.last_local_run`，
保留 `meta.last_run` 作为最近一次完整 CI 时间。健康队列的 `consecutive_runs` 与 `last_seen`
不虚增。任何范围跳过都不能删除目标或 pending 项。页面把 local 目标的 CI 跳过显示为
“由本地监控负责”，不再计作监控异常。写成 `skipped` 会让覆盖率缩水，且快照会被
`prune_orphan_snapshots` 当成"不再监控"删掉——别改回那样。

---

## 6. 改数据的红线

- **`key_clauses` 必须是政策原文摘录**，不要写评述、核对记录、占位文字；
  核实过程写进可选的 `verification_notes`。
- 改 `policy_url` / `policy_link` 等 URL → 该目标会报 `changed` 进待核实队列，
  需确认新来源后 `policy_verify.py --resolve`，这是**设计行为**，不是误报。
- 新增首页要展示的字段 → 必须同步加进 `scripts/gen_data_bundle.py` 的
  `BUNDLE_TOP_FIELDS` / `BUNDLE_VERSION_FIELDS` 白名单，否则首页显示"—"。
- 改了 `site/js/*` 或 `site/css/*` → 同步改 `scripts/gen_docs.py` 的 `ASSET_VERSION`
  和 `site/*.html` 里的 `?v=`（测试会校验一致性）。
- 不要在 `targets` 里写 `toc`/`tob` 键（校验会报错），它们属于 `versions.*`。
- 不要给 `content_selector` 用带构建 hash 的 class（如 `content-KzCsn4`），
  站点重新构建就失效；用稳定 `id` 或属性包含选择器（`[class*=content]`）。

---

## 7. 工作流（`.github/workflows/`）

| 工作流 | 触发 | 职责 |
|--------|------|------|
| `ci.yml`（数据校验） | push main / PR / 手动 | 全量回归测试 + 数据校验 + README / docs / product / feed / API 五项 `--check` → main 全绿后先同步最新 main，再生成五类产物、复验、按差异提交；若同步后又有新推送导致 push 失败，不部署旧产物 |
| `monitor.yml`（政策更新监控） | 每周一 09:00 北京时间 / 手动 | `--scope ci` 跑监控 → 生成 feed.xml → webhook 通知（仅本轮新状态，未配置静默跳过，continue-on-error）→ rebase 后 bot 提交状态/快照/队列/feed |
| `deploy.yml`（部署 Pages） | 数据校验成功即部署；政策更新监控成功或失败均部署（校验失败不部署；限 main） | 发布 `site/` 到 GitHub Pages |

常用触发方式：

```bash
gh workflow run "政策更新监控" --ref main     # 手动跑一次监控
gh run list --limit 5                          # 看最近运行
gh run view <id> --json status,conclusion
gh run view <id> --log-failed | tail -30       # 失败时看日志
```

注意：`ci.yml` 的 `publish` 与 `monitor.yml` 的 job 要 `git push` 产物，其
`actions/checkout` **不能**加 `persist-credentials: false`（会报
`could not read Username for 'https://github.com'`）。`ci.yml` 必须在生成前同步最新
main，生成/复验后不再 rebase；若同步后又有新推送导致 push 失败，整轮不部署旧产物。
`monitor.yml` 仍在提交前 `git pull --rebase --autostash origin main`。两者都仅在
`git diff --cached` 非空时 commit + push。有测试 `test_push_jobs_keep_checkout_credentials`
锁定凭据不变量，改工作流时留意。

---

## 8. 排查抓取问题的顺序

某个目标反复 `changed` 或进健康队列时，按这个顺序查（细节见
`site/docs/update-monitoring.md`）：

1. **看 `last_good_at` / `consecutive_runs`**：区分"这轮没抓到"与"一直抓不到"。
2. **`policy_verify.py <pid> [key]` 看 diff**：旧快照只有 1-2 行、且是页面标题或菜单项
   → 是**抓取方式**问题（旧 baseline 是噪声），`--resolve` 承认新基线；
   只有协议条款文字本身变化才是政策变更。
3. **加长超时试跑**：`--only <pid>:<key> --timeout 60` 排除网络抖动。
4. **配抓取配置**：正文在非标准容器 → `content_selector`；JS 渲染 → `fetch_method: "browser"`
   （可加 `wait_for_selector`）；403/429 → 换 `browser`。
5. **CI 连不上但本地能抓** → `monitor_scope: "local"`（见第 5 节）。
6. 改完配置**第一轮可能报 `changed`**（旧 baseline 是噪声/空壳），看 diff 确认后 `--resolve`；只有条款文字变化才改政策数据。

正文过短时 `message` 会附上"实际拿到：标题《…》页面首段「…」"，据此区分
Cloudflare 挑战页 / 登录墙 / 404 / 纯空壳 / 空文档（空文档 = 连接层失败）。

---

## 9. 提交前自查清单

**🔒 提交身份铁律（隐私红线，优先级与第 6 节数据红线同级）**：

- **身份固定**：所有提交的 author/committer 必须是化名
  `Maverick Ping <13211079+838860610@users.noreply.github.com>`
  （仓库 git config 已配置；换机器/换工具提交前先核对
  `git config user.name && git config user.email`）。
- **禁止出现**：真实姓名或本机用户名、个人邮箱（qq/gmail/163/outlook 等私人域名）、
  `/Users/...` 本地绝对路径、API 密钥与令牌——无论在提交信息、diff 还是文件内容里。
  注意：写自查命令示例时也不要把真实用户名当占位符写进本文件。
- **AI 工具代提交**：部分 IDE/agent 会写入自己的 committer 身份（如
  `trae-solo-agent <solo-agent@trae.ai>`）——committer 暴露工具指纹不算事故，
  但 author 仍必须保持上述匿名身份。
- **bot 身份**：`github-actions[bot]` / `dependabot[bot]` 是平台标准身份，无需处理。
- **推送前自查**：

  ```bash
  git log origin/main..main --format="%an <%ae> | %cn <%ce>"   # 身份普查
  git log origin/main..main -p | grep -iE "本机用户名|私人邮箱|/Users/"  # 内容抽查
  # 定期全历史回扫（把占位符换成实际要排查的标识）：
  git log --all --oneline -S"<标识字符串>" -i
  ```

自查清单：

- [ ] 跑完第 1 节的校验命令，全绿
- [ ] 改过数据 → `gen_readme_table.py --check` 通过
- [ ] 改过 `site/docs/*.md` → `gen_docs.py` 已重新生成且 `--check` 通过
- [ ] 改过 `site/detail.html` 或产品数据 → `gen_product_pages.py` 已重新生成且 `--check` 通过
- [ ] 改过 `site/js|css` → `ASSET_VERSION` 与 `?v=` 已同步
- [ ] 新增抓取行为 → 在 `tests/test_scripts.py` 补了对应回归测试
- [ ] 没有手工编辑 `site/generated/**`、`site/docs/*.html`、`site/p/*.html` 或 `site/sitemap.xml`
- [ ] 提交信息用 `feat/fix/docs/chore` 前缀，说明"改了什么、为什么"（`CONTRIBUTING.md` 有格式）
- [ ] `CHANGELOG.md` 的 `[Unreleased]` 已更新
- [ ] 提交身份为化名 + noreply 邮箱，提交信息与内容不含任何个人隐私（见上方铁律）
