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

### Added

- `tests/test_scripts.py` 新增 `test_site_dir_is_the_publish_root`：断言站点根文件齐备，防止漏文件导致线上 404

### Changed

- **目录分层（A1）**：`data/` 只保留人工维护的源数据（`products.json` + `policies/`）；全部生成物迁入新的 `generated/` 目录——`bundle.json`、`update_status.json`、`snapshots/`、`change_reports/`，以及原 `assets/og-card.png`（`assets/` 目录已移除）
- 相应更新 `gen_data_bundle.py`、`check_updates.py`、`analyze_changes.py`、`gen_og_image.py` 的产出路径，`js/app.js` 的读取路径，两个工作流的提交路径与 `.gitignore`
- `tests/test_scripts.py` 新增 `TestLayout`（21 项）：断言 `data/` 不含生成物、前端只从 `generated/` 读取，防止回归

### Fixed

- 修正 `docs/update-monitoring` 中「`update_status.json` 已加入 .gitignore」的过时描述（该文件现已入库，由监控流程提交）

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
