# 更新日志

本项目的所有重要变更都记录在此文件。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

- `Added` 新增功能
- `Changed` 变更/改进
- `Fixed` 修复问题
- `Removed` 移除内容

## [Unreleased]

### Changed

- **站点整体迁入 `site/`（方案 D）**：`site/` 即站点根，内含 `index.html`、`detail.html`、`404.html`、`robots.txt`、`sitemap.xml`、`css/`、`js/`、`data/`、`generated/`、`docs/`；仓库根只留文档与工具（21 → 12 项）
- **部署改用 GitHub Actions**：新增 `.github/workflows/deploy.yml`，发布 `site/` 目录；Pages 设置需一次性改为 *Settings → Pages → Source: GitHub Actions*（原因：分支发布只支持 `/(root)` 或 `/docs`，无法指定 `site/`）
- 部署触发用 `workflow_run`（监听「数据校验」「政策更新监控」完成）而非 `push`——bot 用 `GITHUB_TOKEN` 提交的 commit 不会再触发 `push` 事件，否则自动生成的产物发布不出去
- 脚本路径常量全部改为 `site/data` 与 `site/generated`；`start.sh` 改为 `http.server --directory site`；新增 `site/.nojekyll`

- **目录分层**：`site/data/` 只保留人工维护的源数据（`products.json` + `policies/`）；生成物统一放 `site/generated/`——`bundle.json`、`update_status.json`、`snapshots/`、`change_reports/`，以及原 `assets/og-card.png`（`assets/` 目录已移除）
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
- **陈旧摘要被当本轮结论**：`analyze_changes.py` 现在每轮开始先删除上一轮 `_summary.md`，并为状态文件读取加 `JSONDecodeError` 兜底
- **git 历史回退是死代码**：把绝对路径当作 git pathspec 传给 `git log/show`，永远不会命中，改为 `os.path.relpath`
- **哈希方案不覆盖提取器变体**：bs4 与正则回退剥离的标签不同，`HASH_SCHEME` 现形如 `text-v3-bs4` / `text-v3-regex`，避免依赖缺失时全库哈希漂移造成批量误报
- **数据文案与字段矛盾**：`zhipu-qingyan`（摘要说"退出需发邮件"、字段是设置开关）、`ima`（摘要说"评为低风险"、字段是 yellow）
- **脚本健壮性**：`update_status.json` 改为原子写（tmp + `os.replace`）；单个数据文件损坏不再中断整轮监控；全部产品失败时显式告警；`validate_data.py` 补齐漏检（`null` 值、非 dict `versions`、版本块非对象、`policy_link` 非 URL、`region` 枚举、未来日期、`timeline` 日期格式）
- **文档数字口径**：`README.en` 的 64 → 65 条版本条目、首页 "50+" → 50 款；`SECURITY.md` 支持版本补 1.3.x，并移除已不可用的"GitHub 站内私信"联系方式

## [1.3.0] - 2026-09-18

### Fixed

- **修复线上死链**：`docs/` 曾被 `.gitignore` 整体忽略，导致首页"方法论"链接与 `sitemap.xml` 中的 `docs/*.html` 在线上 404。现拆分为：`docs/`（对外发布页面，入库）+ `docs/internal/`（内部工作底稿，忽略）
- `data/update_status.json` 与 `data/bundle.json` 不再被忽略（首页依赖其展示监控状态与加速加载），工作流不再需要 `git add -f` 强推

### Added

- `CODE_OF_CONDUCT.md`（行为准则）、`SECURITY.md`（安全政策）
- `CHANGELOG.md`（本文件，原更新日志从 README 迁出）
- `tests/test_scripts.py`：数据与脚本的基础回归测试（unittest，无第三方依赖）
- `.github/dependabot.yml`：GitHub Actions 与 pip 依赖每周自动更新检查
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
