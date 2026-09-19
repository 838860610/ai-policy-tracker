# AI 用户政策追踪器

> 主流 AI 产品是否使用用户数据进行模型训练 — 一个纯前端的 AI 产品隐私政策对比追踪工具。

[![数据校验](https://github.com/838860610/ai-policy-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/838860610/ai-policy-tracker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

[English](README.en.md) | 简体中文

## 功能特性

- **对比表格**：一目了然地查看 50 款主流 AI 产品（国内 46 + 海外 4）的数据使用政策
- **ToC/ToB 切换**：分别查看个人版和企业版的政策差异，切换状态写入 URL，可直接分享链接
- **风险等级标注**：绿色（低风险）、黄色（中风险）、红色（高风险）直观标注，支持按风险筛选
- **搜索**：支持按产品名称或公司搜索
- **详情页面**：每个产品提供详细的政策分析、关键条款摘录、时间线
- **更新监控**：Python 脚本自动检测政策页面变化（正文归一化哈希 + 条件请求，避免动态内容误报），检测结果直接展示在首页
- **本地核实流程**：检测到政策变更后，由本地 `policy-change-verify` skill 提取新旧快照 diff、判断变更是实质性条款变化还是噪声，并起草对 `site/data/policies/{id}.json` 的修改供人工确认（CI 不再自动分析或建 Issue）
- **可访问性**：表格行支持键盘导航（Tab + Enter）
- **纯前端**：无需后端、无需构建工具，开箱即用

## 快速开始

### 本地运行

```bash
# 克隆项目
git clone https://github.com/838860610/ai-policy-tracker.git
cd ai-policy-tracker

# 一键启动：自动创建 .venv 虚拟环境、安装依赖、打开浏览器
./start.sh

# 或指定端口
./start.sh 9000
```

> 手动方式：`python3 -m http.server 8080 --directory site` 后访问 `http://localhost:8080`（静态页面本身不依赖 Python 包；`--directory site` 是因为站点文件都在 `site/` 下）。
> 注意：直接双击 index.html 无法使用——浏览器禁止 file:// 协议下的 fetch 请求，数据加载不出来，必须通过 HTTP 服务访问。

### 部署到 GitHub Pages

站点文件集中在 `site/` 目录，由 GitHub Actions 部署：

1. **一次性设置**：仓库 **Settings → Pages → Build and deployment → Source 选 "GitHub Actions"**
2. `.github/workflows/deploy.yml` 在「数据校验」或「政策更新监控」工作流跑完后自动重新部署（也可在 Actions 页手动触发）

访问地址不变：**<https://838860610.github.io/ai-policy-tracker/>** —— `site/` 即站点根，所以 `site/index.html` → `/`、`site/robots.txt` → `/robots.txt`。

> **为什么不用 "Deploy from a branch"**：Pages 的分支发布只认 `/(root)` 和 `/docs` 两个目录，指定不了 `site/`。要用自定义目录就必须走 Actions 部署，代价是多一个部署工作流 + 一次性切换设置。
>
> **为什么用 `workflow_run` 而不是 `push` 触发**：CI/监控用 `GITHUB_TOKEN` 提交的 commit 不会再触发 `push` 事件，那样自动生成的 `bundle.json`、`update_status.json` 就发布不出去；`workflow_run` 在上游工作流结束后触发，人和 bot 的提交都能覆盖到。

页面内资源与数据全部为相对路径引用，项目页子路径下可正常工作。

### 目录结构

```
ai-policy-tracker/
├── site/                   # 站点根目录——部署时发布的正是这个目录
│   │                       #   （site/index.html → /，site/robots.txt → /robots.txt）
│   ├── index.html          # 首页 - 对比表格
│   ├── detail.html         # 产品详情页
│   ├── 404.html            # GitHub Pages 404 页面
│   ├── robots.txt
│   ├── sitemap.xml
│   ├── .nojekyll           # 禁止 Jekyll 处理，原样发布
│   ├── css/
│   │   └── style.css       # 样式文件
│   ├── js/
│   │   ├── common.js       # 首页/详情页共享工具
│   │   ├── app.js          # 首页逻辑
│   │   └── detail.js       # 详情页逻辑
│   ├── data/               # 人工维护的源数据（改数据只动这里）
│   │   ├── products.json   # 产品 ID 索引（定义列表顺序）
│   │   └── policies/       # 各产品全部数据（唯一数据源）
│   │       ├── chatgpt.json
│   │       ├── claude.json
│   │       └── ...
│   ├── generated/          # 全部自动生成物，一律不手工编辑
│   │   ├── bundle.json     # 合并数据包（gen_data_bundle.py，首页加速，CI 提交）
│   │   ├── update_status.json # 监控状态（check_updates.py，首页读取展示）
│   │   ├── pending_verification.json # 待核实队列（changed 目标的跨轮交接物）
│   │   ├── snapshots/      # 政策正文快照（入库，作为跨环境核实的持久历史）
│   │   └── og-card.png     # Open Graph 分享卡片（gen_og_image.py）
│   └── docs/               # 对外发布文档（methodology / update-monitoring）
│       │                   #   注意：站点与 sitemap 直接引用这些页面，必须入库
│       └── internal/       # 内部工作底稿（核实报告、优化清单，.gitignore 忽略）
├── scripts/
│   ├── check_updates.py    # 政策更新监控脚本（检测 + 快照入库 + 写待核实队列）
│   ├── validate_data.py    # 数据校验脚本
│   ├── gen_readme_table.py # README 汇总表生成脚本
│   ├── gen_data_bundle.py  # 数据合并包生成脚本（首页加速）
│   ├── gen_og_image.py     # 社交分享卡片生成脚本
│   └── extract_clauses.py  # 条款提取工具
├── tests/                  # 回归测试（unittest，无第三方依赖）
├── .github/
│   ├── workflows/          # CI/CD 工作流
│   ├── ISSUE_TEMPLATE/     # Issue 模板
│   └── dependabot.yml      # 依赖自动更新
├── requirements.txt
├── start.sh                # 一键启动（venv + 依赖 + 本地服务）
├── README.md
├── CONTRIBUTING.md         # 贡献指南
├── CODE_OF_CONDUCT.md      # 行为准则
├── SECURITY.md             # 安全政策
├── CHANGELOG.md            # 变更日志
└── LICENSE
```

> **数据模型**：`site/data/policies/{id}.json` 是每个产品唯一的数据源（含名称、公司、版本政策、时间线等全部字段），`site/data/products.json` 只维护产品 ID 的排列顺序。修改产品数据只需要改一个文件。
>
> **源数据 vs 生成物**：`site/data/` 下只有人工维护的源数据；`site/generated/` 下全部由脚本产出（`bundle.json`、`update_status.json`、`pending_verification.json`、`snapshots/`、`og-card.png`），**不要手工编辑**，改了也会被下次 CI 覆盖（其中 `snapshots/` 为监控历史、`pending_verification.json` 为待核实队列）。

## 对比汇总表

<!-- TABLE:START -->
**风险分布**（按个人版条款，共 48 款）：🔴 高风险 16 款 · 🟡 中风险 22 款 · 🟢 低风险 0 款 · 未评定 10 款

国内平台（44 款产品，按厂商拼音排序）：

| 产品 | 厂商 | 个人版训练 | 退出机制 | 企业版训练 | 风险等级 |
|------|------|-----------|---------|-----------|---------|
| 纳米 AI（360） | 360 | ✅ 是 | 未明示退出机制 | — | 🔴 高 |
| 360 智脑 | 360 | ✅ 是 | 未明示退出机制 | ✅ 是 | 🔴 高 |
| 阿里云百炼（Model Studio） | 阿里云 | — | — | ❌ 否 | — |
| Qoder CN（AI 编程智能体，原通义灵码） | 阿里巴巴（通义云启运营） | ✅ 是 | 撤回同意 | ✅ 是 | 🟡 中 |
| 千问办公（QwenWork） | 阿里巴巴 | — | — | — | — |
| 千问 App（原通义千问） | 阿里云 | ✅ 是 | ⚠️ 需邮件申请 | — | 🟡 中 |
| 百川智能（Baichuan AI） | 百川智能 | ✅ 是 | 未明示退出机制 | — | 🔴 高 |
| 文心快码（Baidu Comate） | 百度 | ❌ 否 | 撤回同意 / 企业管理关闭 | ❌ 否 | 🟡 中 |
| 百度智能云千帆 | 百度 | — | — | ❌ 否 | — |
| 文心（原文心一言/文小言） | 百度 | ❌ 否 | 未明示退出机制 | — | 🟡 中 |
| 小艺（华为 HarmonyOS） | 华为 | ✅ 是 | 未明示退出机制 | — | 🔴 高 |
| 阶跃开放平台 | 阶跃星辰 | — | — | ✅ 是 | — |
| 阶跃 AI（原跃问） | 阶跃星辰 | ✅ 是 | ✅ 支持 | — | 🟡 中 |
| 讯飞开放平台（星火大模型 API） | 科大讯飞 | — | — | ✅ 是 | — |
| 讯飞星火 | 科大讯飞 | ✅ 是 | ⚠️ 需邮件申请 | — | 🟡 中 |
| 讯飞智作 | 科大讯飞 | ✅ 是 | 未明示退出机制 | — | 🔴 高 |
| 可灵AI | 快手 | ✅ 是 | ⚠️ 需邮件申请 | — | 🟡 中 |
| 可灵 AI 开放平台 | 快手 | — | — | ❌ 否 | — |
| Mureka（昆仑万维音乐） | 昆仑万维 | ❌ 否 | ⚠️ 需邮件申请 | — | 🟡 中 |
| SkyProduction（昆仑万维） | 昆仑万维 | ✅ 是 | ⚠️ 需邮件申请 | — | 🔴 高 |
| 天工（昆仑万维） | 昆仑万维 | ✅ 是 | 未明示独立退出开关 | — | 🟡 中 |
| 零一万物（01.AI） | 零一万物 | — | — | — | — |
| MiniMax（海螺 AI / 开放平台） | MiniMax（上海稀宇科技） | ✅ 是 | 联系撤回 | ❌ 否 | 🔴 高 |
| 商汤日日新（SenseNova） | 商汤科技 | ❌ 否 | 未明示 | — | 🟡 中 |
| DeepSeek | 深度求索 | ✅ 是 | ✅ 支持 | ✅ 是 | 🟡 中 |
| CodeBuddy（AI 编程助手） | 腾讯（腾讯云） | ✅ 是 | 联系关闭（隐私声明第十一条） | ✅ 是 | 🔴 高 |
| ima（腾讯 AI 知识管家） | 腾讯 | ❌ 否 | 无需退出（知识库数据不用于训练） | — | 🟡 中 |
| 腾讯元宝 | 腾讯 | ❌ 否 | ✅ 支持 | — | 🟡 中 |
| WorkBuddy（AI 办公智能体） | 腾讯（腾讯云运营） | ✅ 是 | ✅ 支持 | ✅ 是 | 🟡 中 |
| 腾讯元器 | 腾讯 | ❌ 否 | 未明示 | ❌ 否 | 🟡 中 |
| Kimi | 月之暗面 | ✅ 是 | ⚠️ 需邮件申请 | ✅ 是 | 🔴 高 |
| AMiner（科研 AI 助手） | 智谱AI | ✅ 是 | 未明示退出机制 | — | 🔴 高 |
| AutoClaw（智谱本地智能体，澳龙） | 智谱AI | ✅ 是 | 未明示退出机制（授权不可撤销） | — | 🔴 高 |
| AutoGLM（智谱） | 智谱AI | ❌ 否 | 设置开关（初始化时选择）+ 联系撤回 | — | 🟡 中 |
| 智谱开放平台（bigmodel.cn） | 智谱AI | — | — | ✅ 是 | — |
| GLM Coding Plan（智谱） | 智谱AI | ✅ 是 | 无（匿名化使用不依赖授权同意） | ❌ 否 | 🔴 高 |
| ZCode（智谱 AI 编程） | 智谱AI | ❌ 否 | ✅ 支持 | — | 🟡 中 |
| 智谱清言 | 智谱AI | ✅ 是 | ✅ 支持 | — | 🟡 中 |
| Zread.ai（GitHub 项目解读） | 智谱AI | — | — | — | — |
| 扣子 / Coze（智能体平台） | 字节跳动 | ✅ 是 | ✅ 支持 | ✅ 是 | 🟡 中 |
| 豆包 | 字节跳动 | ✅ 是 | ✅ 支持 | ❌ 否 | 🟡 中 |
| 豆包大模型 API（火山方舟） | 火山引擎（字节跳动） | — | — | ❌ 否 | — |
| 即梦 AI（Dreamina） | 字节跳动（脸萌科技） | ✅ 是 | ⚠️ 需邮件申请 | ✅ 是 | 🔴 高 |
| Trae（AI IDE） | 字节跳动 | ✅ 是 | 指引路径 | ❌ 否 | 🟡 中 |

海外平台（4 款产品，按厂商排序）：

| 产品 | 厂商 | 个人版训练 | 退出机制 | 企业版训练 | 风险等级 |
|------|------|-----------|---------|-----------|---------|
| Claude | Anthropic | ✅ 是 | ✅ 支持 | ❌ 否 | 🔴 高 |
| Gemini | Google | ✅ 是 | ✅ 支持 | ❌ 否 | 🟡 中 |
| ChatGPT | OpenAI | ✅ 是 | ✅ 支持 | ❌ 否 | 🔴 高 |
| Z.ai（智谱全球 AI 助手） | 智谱AI | ✅ 是 | 未明示退出机制 | ❌ 否 | 🔴 高 |
<!-- TABLE:END -->

> 上表及风险分布由 `scripts/gen_readme_table.py` 从数据自动生成，请勿手改。详细信息请访问[在线对比表格](https://838860610.github.io/ai-policy-tracker/)或各产品详情页。

## 数据来源

数据来源于各 AI 产品官方发布的隐私政策、服务条款和使用条件，逐条注明条款出处与核实日期。

## 更新监控

项目内置自动化的政策更新监控，定时检测政策页面变化，但**只负责"发现变化 + 留档"**，不判断、不改数据、不建 Issue；判断与改数据都在本地由 `policy-change-verify` skill 完成（见下方"本地核实流程"）。所有 Python 脚本统一使用项目虚拟环境 `.venv` 运行（不污染系统 Python，也规避新版 Python 禁止直接 pip 装包的限制）：

```bash
# 方式一：用 start.sh 一键准备（创建 .venv 并安装依赖，已就绪则秒过）
./start.sh

# 方式二：手动创建虚拟环境
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 运行监控脚本（每周一由 CI 自动跑；也可本地手动）
.venv/bin/python scripts/check_updates.py
```

脚本对政策页面正文（剥离 script/style、归一化空白后）计算哈希，并使用 ETag/If-Modified-Since 条件请求，避免页面动态内容导致的误报。检测结果写入 `site/generated/update_status.json`，**首页会自动展示监控状态**：无变化时显示上次运行时间，检测到变更时在表格上方展示告警横幅并在对应产品旁标注 ⚠️。

监控按产品逐条覆盖独立条款链接（顶层 policy_url + 个人版/企业版各自的 policy_link，URL 去重）。正文快照留档到 `site/generated/snapshots/`（`latest.txt` 为当前内容，`prev.txt` 为变更前的旧快照，日期文件为历史存档）并**入库**作为跨环境共享的持久历史——本地 agent 正是靠 git 拉到这些快照来做 diff。本轮检测为 `changed` 的目标会被写入 `site/generated/pending_verification.json`（待核实队列），作为"检测 → 核实"的跨轮交接物（不再用 Issue）。

### 本地核实流程（替代原"AI 自动分析 + 建 Issue"）

检测到变更后，**不在 CI 内自动分析**，而是由维护者在本地调用 `policy-change-verify` skill：

```bash
# 列出待核实队列 + 所有被标记目标（优先看队列）
python3 .codebuddy/skills/policy-change-verify/scripts/policy_verify.py --list
# 查看某产品某个目标的旧→新 diff 与当前政策数据
python3 .codebuddy/skills/policy-change-verify/scripts/policy_verify.py <product_id> [main|toc|tob]
```

skill 提取新旧快照 diff、判断是实质性条款变化还是噪声（页脚年/时间戳/导航重排/抓取失败等属噪声），并**起草**对 `site/data/policies/{id}.json` 的字段 + timeline 修改，**必须等人工确认才写入**。核实并更新数据后，用 `--resolve <product_id>` 从待核实队列移除该项。

其他校验与维护脚本：

```bash
.venv/bin/python scripts/validate_data.py    # 校验数据结构完整性（提交前运行）
.venv/bin/python scripts/gen_readme_table.py # 从数据重新生成 README 汇总表
python3 -m unittest discover -s tests -v     # 回归测试（无需第三方依赖，装了 pytest 也可用 pytest tests/）
```

仓库内置 GitHub Actions 工作流：

- `.github/workflows/monitor.yml`——每周一北京时间 09:00 自动运行 `check_updates.py`：检测变化、提交 `update_status.json` + 快照 + 待核实队列（推送到 GitHub 后生效，也可在 Actions 页手动触发）。**不含** AI 分析 / 建 Issue 步骤
- `.github/workflows/ci.yml`——PR 与主分支推送时自动运行回归测试、数据校验和汇总表一致性检查；main 推送后重新生成 `site/generated/bundle.json` 和 OG 图片（写权限仅授予该发布 job）
- `.github/workflows/deploy.yml`——在上述工作流跑完后把 `site/` 目录部署到 GitHub Pages（也可手动触发）
- `.github/dependabot.yml`——每周检查 GitHub Actions 与 pip 依赖更新

## 更新日志

完整变更记录见 [CHANGELOG.md](CHANGELOG.md)，以下为最近版本摘要：

### v1.3.0 (2026-09-18)

- **修复线上死链**：`docs/` 曾被 `.gitignore` 整体忽略，首页方法论与 sitemap 中的 `docs/*.html` 线上 404；现拆分为发布页面（入库）+ `site/docs/internal/`（忽略）
- **社区文档**：新增 `CODE_OF_CONDUCT.md`（行为准则）、`SECURITY.md`（安全政策）、`CHANGELOG.md`（变更日志）
- **回归测试**：新增 `tests/test_scripts.py`（数据完整性、汇总表生成、发布文档链接有效性），CI 已接入
- **工程**：CI 拆分为只读校验 job 与 main 发布 job（最小权限）、工作流并发控制、dependabot、贡献指南英文快速上手

## 贡献指南

欢迎贡献政策更新和新产品数据！请阅读 [贡献指南](CONTRIBUTING.md) 了解如何参与。提交 PR 前请运行 `.venv/bin/python scripts/validate_data.py`、`.venv/bin/python scripts/gen_readme_table.py --check` 与 `python3 -m unittest discover -s tests`。

参与本项目即表示你同意遵守 [行为准则](CODE_OF_CONDUCT.md)；如发现安全相关问题，请按 [安全政策](SECURITY.md) 私密报告。完整版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT License](LICENSE) © 2025-2026

## 免责声明

本项目数据仅供参考，不构成法律建议。各产品政策可能随时变更，请以官方最新政策为准。在做出重要决策前，请咨询专业法律人士。

数据核实日期见各产品详情页的"最后核实"字段。建议定期运行监控脚本检查政策更新。
