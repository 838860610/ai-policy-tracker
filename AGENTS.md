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
.venv/bin/python -m unittest discover -s tests -q   # 121 项回归测试
.venv/bin/python scripts/validate_data.py            # 数据结构校验（0 错 0 警）
.venv/bin/python scripts/gen_readme_table.py --check # README 汇总表与数据一致
.venv/bin/python scripts/gen_docs.py --check         # 文档页是最新
```

改过文档 `.md` 或前端资源后还要重新生成并提交产物：

```bash
.venv/bin/python scripts/gen_docs.py         # site/docs/*.md → *.html（.md 是唯一源）
.venv/bin/python scripts/gen_data_bundle.py  # 生成 site/generated/bundle.json
.venv/bin/python scripts/gen_og_image.py     # 社交卡片（需 pillow，维护用依赖）
```

**不要手工编辑**：`site/generated/**`（`bundle.json` / `update_status.json` /
`monitor_health.json` / `pending_verification.json` / `snapshots/` / `og-card.png`）
和 `site/docs/*.html`——它们都是脚本产物，改了会被 CI 覆盖。

---

## 2. 目录职责

| 路径 | 职责 |
|------|------|
| `site/data/products.json` | 产品 ID 索引（只定展示顺序，不存数据） |
| `site/data/policies/{id}.json` | **唯一人工真源**：政策字段、版本政策、监控配置、timeline |
| `site/` | 站点根（`site/index.html` → `/`），含 `data/` `generated/` `js/` `css/` `docs/` |
| `site/generated/` | 脚本产物，**入库**（首页与 Pages 直接读取，CI 提交） |
| `scripts/` | 监控与构建脚本（`check_updates.py` 是核心，见下） |
| `skills/policy-change-verify/` | 本地核实 skill：抓新旧快照 diff、起草数据修改、`--resolve` 收尾 |
| `tests/test_scripts.py` | 全部回归测试（单文件，类按关注点分组） |

---

## 3. 监控的两套状态（最容易搞混的地方）

监控结果里每个目标有两套**正交**语义，看错会导致误判：

| 字段 | 回答的问题 | 取值 |
|------|-----------|------|
| `status` | 政策正文相对基线**变没变** | `ok` / `changed` / `failed` / `suspicious` / `skipped` |
| `health` | 这一轮**抓到的正文能不能信** | `ok` / `initialized` / `rebaselined` / `degraded` / `no_baseline` / `blocked` |

- `status=changed` → 进**待核实队列** `pending_verification.json`，走 policy-change-verify skill；
- `health` 非 `ok/initialized/rebaselined` → 进**健康队列** `monitor_health.json`，修抓取配置；
- 两者可同时发生，**不要**把抓取失败当政策变更。

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

CI 跑 `--scope ci` 跳过它们，但**沿用上次结果**（含快照引用与 `last_checked`），
只加 `skipped_this_run` 标记。写成 `skipped` 会让覆盖率缩水，且快照会被
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
| `ci.yml`（数据校验） | push main / PR | 跑测试+校验 → 生成并提交 bundle/docs 产物 |
| `monitor.yml`（政策更新监控） | 每周一 09:00 北京时间 / 手动 | `--scope ci` 跑监控 → bot 提交状态/快照/队列 |
| `deploy.yml`（部署 Pages） | 上述两个 workflow_run 成功（限 main） | 发布 `site/` 到 GitHub Pages |

常用触发方式：

```bash
gh workflow run "政策更新监控" --ref main     # 手动跑一次监控
gh run list --limit 5                          # 看最近运行
gh run view <id> --json status,conclusion
gh run view <id> --log-failed | tail -30       # 失败时看日志
```

注意：`monitor.yml` 的 job 要 `git push` 产物，其 `actions/checkout` **不能**加
`persist-credentials: false`（会报 `could not read Username for 'https://github.com'`），
且提交前会 `git pull --rebase origin main` 避免与人工提交冲突。有测试
`test_push_jobs_keep_checkout_credentials` 锁定这两条不变量，改工作流时留意。

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
6. 改完配置**第一轮必然报 `changed`**（旧 baseline 是噪声/空壳），确认后 `--resolve`。

正文过短时 `message` 会附上"实际拿到：标题《…》页面首段「…」"，据此区分
Cloudflare 挑战页 / 登录墙 / 404 / 纯空壳 / 空文档（空文档 = 连接层失败）。

---

## 9. 提交前自查清单

- [ ] 跑完第 1 节的四条校验命令，全绿
- [ ] 改过数据 → `gen_readme_table.py --check` 通过
- [ ] 改过 `site/docs/*.md` → `gen_docs.py` 已重新生成且 `--check` 通过
- [ ] 改过 `site/js|css` → `ASSET_VERSION` 与 `?v=` 已同步
- [ ] 新增抓取行为 → 在 `tests/test_scripts.py` 补了对应回归测试
- [ ] 没有手工编辑 `site/generated/**` 或 `site/docs/*.html`
- [ ] 提交信息用 `feat/fix/docs/chore` 前缀，说明"改了什么、为什么"（`CONTRIBUTING.md` 有格式）
- [ ] `CHANGELOG.md` 的 `[Unreleased]` 已更新
