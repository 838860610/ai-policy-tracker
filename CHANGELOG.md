# 更新日志

本项目的所有重要变更都记录在此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

- `Added` 新增功能
- `Changed` 变更/改进
- `Fixed` 修复问题
- `Removed` 移除内容

## [Unreleased]

### Added

- **抓取健康队列**：新增 `site/generated/monitor_health.json`，与"政策变化待核实队列"分离。每轮由 `update_status.json` 完全重建，记录 `health`、失败原因、连续不健康轮次与建议动作；目标恢复后条目自动消失
- **目标级抓取配置**：`versions.*` 与 `sources[]` 条目支持 `fetch_method`、`content_selector`、`wait_for_selector`、`min_body_chars`，不必为一个站点把整产品都切成浏览器抓取；`--no-browser` 现在只跳过 `browser` 目标
- **局部重试**：`check_updates.py` 新增 `--products`、`--only <pid>:<key>`、`--no-prune`，只重跑选中目标、其余继承上次状态（`meta.partial_run`），修完抓取配置后无需重跑全量
- **首页抓取降级明细**：banner 下方可展开"抓取降级明细"，逐条列出产品、目标、健康类型、失败原因与上次成功抓取时间；`monitor_health.json` 缺失时从状态里的 `health` 兜底推导
- `tests/test_scripts.py` 新增 48 项（54 → 91）：`TestFetchHealth`、`TestMonitorHealthQueue`、`TestPartialRetry` 三个新类共 32 项，另在既有类中补 16 项回归（待核实队列入参形状、`--only` 真正筛选、快照不被误删、重试预算、`last_good_at` 回填、健康队列与状态一致性、首页健康明细渲染）。新增真实失败页样本 `tests/fixtures/empty_shell.html`、`render_required_shell.html`，区分 `empty_body` / `render_required`

### Changed

- **状态语义拆分**：目标与产品级结果新增 `health` 字段（`ok`/`initialized`/`rebaselined`/`degraded`/`no_baseline`/`blocked`）与 `last_good_at`、`health_reason`、`fetch_method`。首次建基线由 suspicious 改为 `ok` + `initialized`（不再算异常）；正文过短或抓取失败**不覆盖已有基线**，只标降级/无基线/被拦截；403/405/429/451 归为 `blocked`
- **修复待核实队列被静默清空**：`update_pending_verification` 期望 `{pid: info}` 映射，调用处却传了 `{"products": {...}}` 包装，导致每轮监控都把未解决的 `changed` 项当成"已移除目标"清空。补回归测试
- **修复 `--only` 未真正筛选**：`--only gemini:main` 过去会重跑全部 48 个产品（局部重试形同虚设）。现在只检查选中目标，其余继承上次状态
- **修复被跳过产品的快照被误删**：孤儿快照清理过去按"本轮状态里的 targets"判定活跃目标，`--no-browser` 跳过或 `monitor: false` 的产品会被当成已下线，快照目录（含 `latest.txt` / `prev.txt` / 日期存档）整片删除——快照是检测→核实回路唯一的持久历史。改为按**配置**（`policies/{id}.json` 展开的监控目标）判定；`--no-browser` 跳过整产品时改为沿用上次目标结果（标 `skipped_this_run`），不再抹掉 CI 建立的覆盖
- **目标级配置补齐 `main` 载体**：`main` 的 URL（`policy_url`）在顶层，天然没有内层对象可挂配置——此前"同一产品 main 需 browser、toc 是静态页"配不出来。新增 `targets.main`（只含 `main` 键；`toc`/`tob` 仍写 `versions.*`、补充来源仍写 `sources[]`，避免两处配置歧义），顶层字段继续生效，既有数据文件无需迁移。`validate_data.py` 抽出 `check_fetch_config()` 统一校验四处载体的 `fetch_method` 取值、选择器类型与正文下限类型，`targets.main` 额外检查拼写错误
- **修复 CI 从未真正提交过监控结果**：`ci.yml` 的 publish job 与 `monitor.yml` 都要 `git push` 生成物，但两处 checkout 都写了 `persist-credentials: false`，push 直接失败（`could not read Username for 'https://github.com'`）——仓库历史上没有任何 bot 提交，监控状态与快照每次都跑完就丢。改为这两个 job 保留 checkout 凭据（写权限仍由 `permissions: contents: write` 限定到最小范围），不 push 的 validate/deploy job 仍关凭据。补 `test_push_jobs_keep_checkout_credentials` 锁定
- **修复 bot 提交与人工提交竞争**：监控运行期间若有人 push（本地核实、CI 再生成产物），bot 的 push 会被拒（`fetch first`）而整轮结果丢失。提交前先 `git pull --rebase --autostash origin main`
- **修复 SSRF 防护误杀合法公网 URL**：`safe_fetch_url` 把"DNS 没解析出来/解析超时"和"解析到私有地址"混为一谈，GitHub runner 上偶发慢解析就让合法公网 URL 被记成"仅允许解析到公网地址的 HTTPS URL"，真实故障原因被安全策略掩盖。现在只有**明确解析到私有/保留地址**才拒绝，无法判定时放行让请求自然失败（解析不出来时后续连接同样会失败）；DNS 等待上限 3s → 5s
- **修复 browser 抓取的"提前退出"导致基线不稳定**：曾用"正文超过 8000 字符就提前结束渲染重试"来省时间，但各页面完整正文长度差异极大——实测 `support.google.com` 帮助页同一次抓取出现过 9500 与 56422 字符两种结果，固定阈值会把渲染未完成的中间态写进基线，之后每轮都误报 changed。现固定跑满 3 次渲染并取最长（`pick_longest_render()`），额外成本远小于误报代价
- **正文起始标记只用站点特有格式**：`LEAD_IN_MARKER_RE` 曾加入中文 `生效日期：`，导致腾讯系协议页开头的「文档标题 + 更新日期」被整段切掉（tencent-yuanbao 少 26 字符、ima 少 62、yuanqi 少 28）——这些字段是政策版本标识。现只用 OpenAI/英文站的 `Published:` / `Updated:` + `YYYY年`，并加 `test_lead_in_marker_keeps_chinese_title_and_update_date` 锁定
- **新增两条 UI 去噪规则**：chatgpt/tob 的语言下拉列表展开与否（15147 ↔ 15752 字符）改由头部截断处理；doubao-api 的新手引导浮层（11564 ↔ 11593 字符，差异仅"我知道了 不再提醒"按钮文案）进 `UI_NOISE_PHRASES`
- **`doubao-api` 锁定稳定正文容器**：文档站页面结构波动（有时包 `<main>`、有时不包），`extract_text` 的 root 在"仅正文"与"导航+正文"间跳变。配 `targets.main.content_selector: "#app-content"`（用稳定 id，不用带构建 hash 的 class）后连续多轮稳定
- **修复 13 个 JS 空壳目标的抓取配置**：实测 12 个目标的静态 HTML 只有空壳（`#app`/`#root`/`#__next` 空 div、`BAILOUT_TO_CLIENT_SIDE_RENDERING` 占位），配 browser 后正文从 0 字符恢复到 1.1 万～5.6 万字符。其中 7 个目标此前处于**"假健康"**——旧 baseline 存的是页面标题或导航噪声（如 skyproduction 存的是产品首页标题「天工工作台 - AI视频生成工具」），因此长期显示"内容未变化"；修复后首轮必然报 changed，经 diff 确认为抓取方式变化而非政策变更，已逐条 `--resolve` 承认新基线
- **Gemini 目标改用 browser 后恢复可抓取**：`policies.google.com` 等域名在受限网络下 requests 层连接超时（3 个目标长期 `degraded`），但 Chromium 网络栈可正常访问，health 全部回到 `ok`。因 browser 固定 `locale=zh-CN`，Google 返回中文版而非原先的英文版，构成一次抓取层面的 changed（非政策变更），已 resolve
- `baichuan` 此前疑似登录/验证码墙（静态 HTML 含 `captchaContainer`），实测 browser 渲染后可拿到完整《百川用户协议》（13437 字符），因此保留 browser 监控而非 `monitor: false`——**先试跑拿证据再决定降级方案**
- **不可达域名的重试预算**：连接阶段超时单独收紧到 5s（requests 会按解析出的每个地址依次连接），并为单目标网络重试加 120s 墙钟预算。`policies.google.com` 在受限网络下原本单目标要耗 5 分钟以上、3 个 Gemini 目标足以吃掉一轮监控预算，现在约 105s/目标
- `update_status.json` 的 `meta` 新增 `health_issues` / `health_blocked` / `health_degraded` / `health_no_baseline` / `partial_run`
- 监控工作流超时 30 → 45 分钟，请求间隔 1.5s → 0.5s、单次超时 30s → 20s（全量一轮从超时被杀变成稳定跑完），并提交 `monitor_health.json`
- **监控可靠性修复**：304 仅在本地基线有效时接受；缺基线会强制完整抓取并标记 suspicious，URL 变化进入待核实，队列告警在 resolve 前保持可见
- **数据模型修复**：新增 `training_status` 语义化训练结论和 `sources[]` 补充来源注册表；正文提取支持 PDF、main/article 和动态节点过滤
- **安全边界修复**：监控仅允许公网 HTTPS URL，文档 Markdown 输出清洗原始 HTML，政策链接使用 URL 协议白名单

- **监控/核实流程重构（端到端）**：CI 不再做 AI 分析、不再自动建 Issue。`monitor.yml` 只保留 `check_updates.py` 检测 + 快照入库 + 写 `pending_verification.json` 待核实队列；核实与改数据全部在本地由 `policy-change-verify` skill 完成。移除 `scripts/analyze_changes.py` 与 `OPENAI_API_KEY` 依赖
- **基线方案无关化**：变更检测改以"已入库快照文本"为准（哈希仅作快速路径），哈希方案升级（text-v2→text-v4 等）时不再整库误报/失明；快照 `site/generated/snapshots/` 由 `.gitignore` 忽略改为入库，作为跨环境（CI↔本地）共享的持久历史；日期存档加保留策略（默认 12 份）
- **站点整体迁入 `site/`（方案 D）**：`site/` 即站点根，内含 `index.html`、`detail.html`、`404.html`、`robots.txt`、`sitemap.xml`、`css/`、`js/`、`data/`、`generated/`、`docs/`；仓库根只留文档与工具（21 → 12 项）
- **部署改用 GitHub Actions**：新增 `.github/workflows/deploy.yml`，发布 `site/` 目录；Pages 设置需一次性改为 *Settings → Pages → Source: GitHub Actions*（原因：分支发布只支持 `/(root)` 或 `/docs`，无法指定 `site/`）
- 部署触发用 `workflow_run`（监听「数据校验」「政策更新监控」完成）而非 `push`——bot 用 `GITHUB_TOKEN` 提交的 commit 不会再触发 `push` 事件，否则自动生成的产物发布不出去
- 脚本路径常量全部改为 `site/data` 与 `site/generated`；`start.sh` 改为 `http.server --directory site`；新增 `site/.nojekyll`

- **目录分层**：`site/data/` 只保留人工维护的源数据（`products.json` + `policies/`）；生成物统一放 `site/generated/`——`bundle.json`、`update_status.json`、`pending_verification.json`、`snapshots/`，以及原 `assets/og-card.png`（`assets/` 目录已移除）
- **风险等级校准**：4 处"训练且无退出机制却标黄"改为红（`zai.toc`、`kimi.tob`、`bigmodel.tob`、`glm-coding-plan.toc`），README 汇总表与 OG 图已重新生成（高风险 15 → 17，中风险 24 → 22）
- **方法论口径修订**：红色标准第③条明确为"**训练场景下**未进行去标识化处理"，消除与约 15 个 `deidentified=false` 黄色块的规则冲突
- **文档单源化**：新增 `scripts/gen_docs.py`，`site/docs/*.md` 为唯一源、`*.html` 由脚本渲染，CI 跑 `--check` 并自动提交，彻底消除两份手工副本的漂移
- **首页瘦身**：`bundle.json` 按白名单裁剪（只含表格与展开面板所需字段），202 KB → 30 KB；Google Fonts 改为异步加载（国内访客不再因字体请求阻塞而白屏）；详情行改为展开时才渲染
- `key_clauses` 纪律：非政策原文内容（对比提示、404 核对记录）移入新增的可选字段 `verification_notes`
- 占位条目（政策 URL 只能指向产品首页）新增可选字段 `monitor: false`，监控脚本跳过，避免持续误报
- 补齐 3 个产品"引文出处"的监控目标（`versions.toc.policy_link`，人工确认）：`zcode` → `zcode.z.ai/cn/privacy`；`xunfei-xinghuo` → 《讯飞星火APP用户协议》（`xinghuo.xfyun.cn/policy/`，原 `xfyun.cn/doc/spark/UserAgreement.html` 已 404）；`tencent-yuanbao` → 《腾讯元宝隐私政策》（`privacy.qq.com/document/preview/eb9be565...`）

### Added

- `tests/test_scripts.py` 新增 `test_site_dir_is_the_publish_root`：断言站点根文件齐备，防止漏文件导致线上 404
- `tests/test_scripts.py` 新增 `TestLayout`：断言源数据目录不含生成物、前端只从 `generated/` 读取
- `tests/test_scripts.py` 新增 `TestResponseDecoding`（4 项）：防止响应解码回退到 latin-1 再次产生乱码快照
- `tests/test_scripts.py` 新增 `TestSiteConsistency`（6 项）：页面内相对链接可达性、资源版本号一致、sitemap 与产品索引一致、`deploy.yml` 的 `workflow_run` 名字匹配、bundle 瘦身且完整、文档页无"未来功能"等过时表述
- `scripts/gen_docs.py`：把 `site/docs/*.md` 渲染为发布用 `.html`（依赖 `markdown`，已加入 requirements.txt）

### Fixed

- **修复政策正文快照乱码**：`requests` 对未声明 charset 的 `text/html` 会按 RFC 2616 回退到 ISO-8859-1，中文被解成拉丁字符后再以 UTF-8 存盘，形成双重编码（mojibake），快照无法阅读、AI 变更分析也拿不到有效文本。新增 `response_text()`：未声明 charset 时用探测编码（兜底 utf-8），声明为 ISO-8859-1 的尝试反向还原
- `HASH_SCHEME` 升至 `text-v2`：解码变化会让所有哈希改变，升版后脚本重建基线，避免误报"全部产品政策已变更"
- 修正 `docs/update-monitoring` 中「`update_status.json` 已加入 .gitignore」的过时描述（该文件现已入库，由监控流程提交）
- **文档页 CSS 死链**：`site/docs/*.html` 引用 `../site/css/style.css`（迁移 `site/` 后的遗留路径），部署后 404 导致两个已收录页面完全没有样式
- **8 个纯 ToB 产品详情页首屏空白**：`syncTabs` 只隐藏了标签按钮，没把 `active` 从 `contentToc` 移到 `contentTob`
- **资源版本号分裂**：`index.html` 用 `20260916-1`、`detail.html`/`404.html` 用 `20260909-1`、docs 页无版本号，现统一为单一版本（测试已锁死）
- **监控空转**：12 个产品的正文快照只有 19–93 字节（SPA/反爬只返回标题骨架），却仍记为 `ok` 并建基线；现对低于 `MIN_BODY_CHARS` 的正文标记 `suspicious`，不建基线、不报变更
- **AI 变更告警在最后一公里丢失**：无旧快照的报告缺少 `has_substantive_change`，被摘要的 True/False 两分过滤同时漏掉；现补为 `True`，且 Issue 正文始终逐条列出变更产品
- **状态与队列一致性**：监控会拒绝没有本地基线的 304，未解决的 changed 告警不会被后续 304 清除；队列解析失败时停止写入而不是覆盖历史
- **git 历史回退是死代码**：把绝对路径当作 git pathspec 传给 `git log/show`，永远不会命中，改为 `os.path.relpath`
- **哈希方案覆盖提取器变体**：bs4 与正则回退剥离的标签不同，`HASH_SCHEME` 现形如 `text-v4-bs4` / `text-v4-regex`，避免依赖缺失时全库哈希漂移造成批量误报
- **数据文案与字段矛盾**：`zhipu-qingyan`（摘要说"退出需发邮件"、字段是设置开关）、`ima`（摘要说"评为低风险"、字段是 yellow）
- **脚本健壮性**：`update_status.json` 改为原子写（tmp + `os.replace`）；单个数据文件损坏不再中断整轮监控；全部产品失败时显式告警；`validate_data.py` 补齐漏检（`null` 值、非 dict `versions`、版本块非对象、`policy_link` 非 URL、`region` 枚举、未来日期、`timeline` 日期格式）
- **文档数字口径**：README、首页和方法论统一为 48 款产品、63 个版本块，并同步更新 ToC/ToB 展示说明；`SECURITY.md` 支持版本补 1.3.x，并移除已不可用的"GitHub 站内私信"联系方式

## [1.3.0] - 2026-09-18

### Fixed

- **修复线上死链**：`docs/` 曾被 `.gitignore` 整体忽略，导致首页"方法论"链接与 `sitemap.xml` 中的 `docs/*.html` 在线上 404。现拆分为：`docs/`（对外发布页面，入库）+ `docs/internal/`（内部工作底稿，忽略）
- `data/update_status.json` 与 `data/bundle.json` 不再被忽略（首页依赖其展示监控状态与加速加载），工作流不再需要 `git add -f` 强推

### Added

- `CODE_OF_CONDUCT.md`（行为准则）、`SECURITY.md`（安全政策）
- `CHANGELOG.md`（本文件，原更新日志从 README 迁出）
- `tests/test_scripts.py`：数据与脚本的基础回归测试（unittest，无第三方依赖）
- `.github/dependabot.yml`：曾配置 GitHub Actions 与 pip 依赖自动更新检查，后续按维护策略移除，升级依赖需人工审阅
- `CONTRIBUTING.md` 增加 English quick start 段落

### Changed

- `ci.yml` 拆分为 `validate`（`contents: read`）与 `publish`（仅 main 推送、`contents: write`）两个 job，遵循最小权限原则
- `ci.yml` / `monitor.yml` 增加 `concurrency` 分组，避免并发运行互相覆盖提交
- README 顶部增加 CI / 许可证 / 数据量徽章

## [1.2.0] - 2026-09-12

### Added

- **第二层 AI 辅助变更分析**：新增 `scripts/analyze_changes.py`，监控检测到政策页面变化后自动对比新旧快照，调用 LLM 提取训练政策/退出机制/留存期限等维度变化，生成结构化报告嵌入 Issue
- 支持任何 OpenAI 兼容 API（OpenAI / DeepSeek / 智谱 / Moonshot 等），未配置 API key 时降级为纯文本 diff
- **SEO 与站点**：新增 `404.html`、`robots.txt`、`sitemap.xml`（53 个 URL）、canonical 链接、`<noscript>` 降级提示

### Changed

- `check_updates.py` 变更时自动备份旧快照到 `prev.txt`；429 限流处理（Retry-After）
- `monitor.yml` 新增"AI 辅助变更分析"步骤；pip 缓存；`timeout-minutes: 30`
- **前端优化**：搜索防抖（200ms）、分组折叠状态保持、OG 标签动态更新、风险图例加方法论链接
- **代码质量**：CSS/JS 版本号统一、`.editorconfig` 代码风格配置、`gen_og_image.py` 跨平台字体回退、CI 自动生成 OG 图片
- **文档**：README 目录结构补全、methodology 数据源表更新为 50 款产品、CONTRIBUTING 脚本说明补全、update-monitoring 第二层分析文档

### Fixed

- 数据修正：`VENDOR_SORT` 补字节跳动（app.js + gen_readme_table.py）

## [1.1.0] - 2026-08-29

### Added

- 新增 `scripts/validate_data.py` 数据校验脚本（schema、ID 一致性、占位文字检测）
- README 汇总表改为从数据自动生成（`scripts/gen_readme_table.py`）
- 首页展示监控状态：检测到政策变更时显示告警横幅并在产品名旁标注 ⚠️
- 新增 `start.sh` 一键启动；全部 Python 脚本统一走 `.venv` 虚拟环境
- 新增 favicon、页面 meta 描述

### Changed

- 数据单源化：产品详情数据只保留在 `data/policies/{id}.json`，`products.json` 改为 ID 索引
- 监控脚本改为正文文本归一化哈希 + ETag/If-Modified-Since 条件请求，大幅减少动态页面误报
- 监控脚本支持请求间隔（`--delay`）、失败重试、哈希算法版本化（升级时自动重建基线）
- 前端重构：抽取 `js/common.js` 共享工具；ToC/ToB 与筛选状态写入 URL 可分享；表格行支持键盘导航
- 徽章类名语义化（`badge-good`/`badge-bad`）；筛选按钮改用"低/中/高风险"文案

### Fixed

- 修复 README 汇总表与数据的多处不一致
- 全量数据核实（AI 辅助 + 人工确认）：8 个产品的留存期限/条款摘录按官方政策原文更新，修复 8 条失效政策链接，修正 4 个企业版风险等级

## [1.0.0] - 2025-01-15

### Added

- 初始版本发布：12 款主流 AI 产品的政策对比数据（后扩展至 50 款）
- 支持个人版 (ToC) 和企业版 (ToB) 切换
- 支持风险等级筛选和产品搜索
- 产品详情页包含时间线、关键条款摘录、分析摘要
- 政策更新监控脚本 `check_updates.py`
- 方法论和监控说明文档
