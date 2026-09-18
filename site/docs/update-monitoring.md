# 更新监控说明

## 概述

本项目采用两层监控机制：

- **第一层·变化检测**（`scripts/check_updates.py`）：定期检测各 AI 产品的隐私政策页面是否发生变化（正文归一化哈希 + 条件请求）。检测结果写入 `site/generated/update_status.json`，**首页读取并展示监控状态**——检测到变更时在表格上方显示告警横幅并在对应产品名旁标注 ⚠️。
- **第二层·AI 辅助分析**（`scripts/analyze_changes.py`）：检测到变更后，自动对比新旧政策快照，调用 LLM 提取训练政策/退出机制/留存期限等维度的变化，生成结构化报告写入 `site/generated/change_reports/`，并将分析摘要嵌入 GitHub Issue。

## 检测原理

为避免误报，脚本不会直接对原始 HTML 做哈希（政策页面普遍含有时间戳、CSRF token、A/B 实验等动态内容，裸哈希几乎每次运行都会误报"已变更"），而是：

1. **正文提取**：剥离 `<script>`、`<style>` 等非正文标签，提取可见文本（使用 BeautifulSoup，未安装时退化为正则去标签）
2. **空白归一化**：压缩行内连续空白、丢弃空行，使哈希对纯排版变化不敏感
3. **归一化哈希**：对归一化后的文本计算 SHA256
4. **条件请求**：携带上次记录的 `ETag` / `Last-Modified`，页面未变化时服务端直接返回 304，不下载正文、零误报
5. **哈希方案版本化**：状态文件中记录 `hash_scheme`；提取算法升级时自动重建基线，而不是误报全部"已变更"

## 监控脚本使用方法

### 前置条件

所有 Python 脚本统一使用项目虚拟环境 `.venv` 运行（不污染系统 Python，也规避新版 Python 禁止直接 pip 装包的限制）：

```bash
# 方式一：./start.sh 会自动创建 .venv 并安装依赖
./start.sh

# 方式二：手动创建
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # requests + beautifulsoup4
```

### 手动运行

```bash
cd /path/to/ai-policy-tracker

# 默认参数：请求间隔 1.5s，单次超时 30s
.venv/bin/python scripts/check_updates.py

# 自定义参数
.venv/bin/python scripts/check_updates.py --delay 3 --timeout 60
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--delay` | 1.5 | 相邻请求间隔秒数（礼貌抓取，避免触发对方风控） |
| `--timeout` | 30 | 单次请求超时秒数 |

网络类错误（超时、连接失败）会自动重试 2 次，按 5s、10s 退避。

### 输出示例

```
============================================================
AI 政策更新监控脚本
运行时间：2026-08-29 09:00:00
哈希方案：text-v1（正文文本归一化）
============================================================

共 50 个产品需要检查

  [OK]   ChatGPT (chatgpt): 内容未变化（304 Not Modified）
  [OK]   Claude (claude): 内容未变化
  [⚠️]   Gemini (gemini): 政策可能已更新！待核实
         URL: https://policies.google.com/terms
  ...

============================================================
检查完成
  总计: 12
  未变化: 10
  已变更: 1
  失败:   1
  跳过:   0
  状态文件: .../site/generated/update_status.json
============================================================

⚠️ 告警：检测到 1 个产品政策可能已更新，请及时核实！
  - gemini: https://policies.google.com/terms
```

## 定时运行

### Cron（每周运行一次，推荐）

```bash
# 编辑 crontab
crontab -e

# 每周一早上 9 点运行（logs 目录需预先创建：mkdir -p logs）
0 9 * * 1 cd /path/to/ai-policy-tracker && mkdir -p logs && /path/to/ai-policy-tracker/.venv/bin/python scripts/check_updates.py >> logs/check_updates.log 2>&1
```

### 每天运行一次

```bash
0 9 * * * cd /path/to/ai-policy-tracker && mkdir -p logs && /path/to/ai-policy-tracker/.venv/bin/python scripts/check_updates.py >> logs/check_updates.log 2>&1
```

### 使用 systemd timer（替代方案）

创建 `/etc/systemd/system/ai-policy-check.service`：

```ini
[Unit]
Description=AI Policy Update Check

[Service]
Type=oneshot
WorkingDirectory=/path/to/ai-policy-tracker
ExecStart=/path/to/ai-policy-tracker/.venv/bin/python scripts/check_updates.py
```

创建 `/etc/systemd/system/ai-policy-check.timer`：

```ini
[Unit]
Description=Run AI Policy Check weekly

[Timer]
OnCalendar=Mon *-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

启用：

```bash
sudo systemctl enable --now ai-policy-check.timer
```

## 输出说明

### 状态标记含义

| 标记 | 含义 |
|------|------|
| `[OK]` | 内容未变化（含 304 Not Modified） |
| `[⚠️]` | 内容已变化，需要人工核实 |
| `[新增]` | 首次检查，记录基线 hash |
| `[基线]` | 哈希算法升级或无有效基线，重新记录 |
| `[失败]` | 请求失败（超时、404 等，重试后仍失败） |
| `[跳过]` | URL 为空或"待核实"，跳过检查 |

### update_status.json 格式

```json
{
  "meta": {
    "last_run": "2026-08-29T09:00:00",
    "hash_scheme": "text-v1",
    "total_products": 12,
    "changed": 1,
    "failed": 0,
    "skipped": 0
  },
  "products": {
    "chatgpt": {
      "url": "https://openai.com/policies/terms-of-use",
      "hash_scheme": "text-v1",
      "current_hash": "a1b2c3d4e5f6...",
      "content_etag": "\"abc123\"",
      "content_last_modified": "Mon, 24 Aug 2026 10:00:00 GMT",
      "last_checked": "2026-08-29T09:00:00",
      "status": "ok",
      "message": "内容未变化（304 Not Modified）",
      "last_changed_date": null
    },
    "gemini": {
      "url": "https://policies.google.com/terms",
      "hash_scheme": "text-v1",
      "current_hash": "f6e5d4c3b2a1...",
      "content_etag": null,
      "content_last_modified": null,
      "last_checked": "2026-08-29T09:00:00",
      "status": "changed",
      "message": "⚠️ 政策可能已更新，待核实",
      "last_changed_date": "2026-08-29T09:00:00"
    }
  }
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `meta.last_run` | 最后运行时间（ISO 格式） |
| `meta.hash_scheme` | 当前哈希算法版本 |
| `meta.total_products` | 检查的产品总数 |
| `meta.changed` | 检测到变化的产品数 |
| `meta.failed` | 检查失败的产品数 |
| `meta.skipped` | 跳过检查的产品数 |
| `products.{id}.url` | 检查的政策 URL |
| `products.{id}.hash_scheme` | 生成该哈希时的算法版本 |
| `products.{id}.current_hash` | 当前页面正文（归一化）的 SHA256 hash |
| `products.{id}.content_etag` | 服务端返回的 ETag（用于条件请求） |
| `products.{id}.content_last_modified` | 服务端返回的 Last-Modified（用于条件请求） |
| `products.{id}.last_checked` | 最后检查时间 |
| `products.{id}.status` | 检查状态（ok/changed/failed/skipped） |
| `products.{id}.message` | 状态描述信息 |
| `products.{id}.last_changed_date` | 最后检测到变化的日期 |

## 监控流程

```
1. 读取 site/data/products.json（ID 索引）
2. 逐个加载 site/data/policies/{id}.json，获取 policy_url
3. 读取 site/generated/update_status.json（如存在）中上次的状态
4. 对每个产品：
   a. 跳过 URL 为空或"待核实"的条目
   b. 携带 ETag / If-Modified-Since 发起条件请求（失败自动重试）
   c. 服务端返回 304 → 内容未变化
   d. 否则提取正文文本、归一化空白、计算 SHA256
   e. 与上次记录的 hash 对比（hash_scheme 不一致时重建基线）
   f. 记录检查结果与新 ETag / Last-Modified
   g. 等待 --delay 秒再检查下一个（礼貌抓取）
5. 写入 site/generated/update_status.json（首页读取展示）
6. 输出告警信息
```

## 首页如何展示监控结果

首页 `site/js/app.js` 会尝试加载 `site/generated/update_status.json`：

- **文件不存在**（从未运行过监控）：页面不显示任何监控信息
- **全部无变化**：表格上方显示一行"政策监控上次运行：…，未检测到政策变更"
- **检测到变更**：显示醒目的告警横幅，列出可能已更新的产品（可点击进入详情），对应产品的名称旁也会标注 ⚠️

> 注意：`site/generated/update_status.json` 由监控流程生成，但**会入库**——首页与 Pages 直接读取它展示监控状态，`monitor.yml` 每次运行后自动提交。同目录下的 `site/generated/snapshots/` 因体积大、变动频繁而保留在 `.gitignore` 中，需要时用 `git add -f` 强制提交。

## 第二层 AI 辅助分析

### 已实现（2026-09-09）

当检测到政策页面变化后，`scripts/analyze_changes.py` 自动对比新旧快照并调用 LLM 提取关键变化点：

1. **新旧快照对比**：从 `site/generated/snapshots/{id}/{target}/` 取 `latest.txt`（新版）和上一个日期存档或 git 历史（旧版）
2. **AI 对比分析**：调用 OpenAI 兼容 API，按结构化 prompt 提取训练政策/退出机制/留存期限/知识产权等维度的变化
3. **结构化报告**：分析结果写入 `site/generated/change_reports/{id}_{target}_{date}.json`，Markdown 摘要写入 `_summary.md`
4. **Issue 嵌入**：CI 中自动将分析摘要嵌入"政策变更待核实"Issue，人工直接在 Issue 中看到分析结论
5. **降级模式**：未配置 `OPENAI_API_KEY` 时自动降级为纯文本 diff，仍输出可读报告

### 流程

```
check_updates.py 检测到 hash 变化
  → analyze_changes.py 取新旧快照
  → LLM 分析新旧内容差异（无 API key 时降级为文本 diff）
  → 提取关键变化点（训练政策、退出机制、留存期限等）
  → 生成结构化报告 site/generated/change_reports/{id}_{target}_{date}.json
  → 生成 Markdown 摘要 _summary.md
  → CI 自动提交报告 + 嵌入 Issue
  → 人工确认后更新 site/data/policies/{id}.json
```

### 配置

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 | 示例 |
|--------|------|------|
| `OPENAI_API_KEY` | LLM API 密钥 | `sk-...` |
| `OPENAI_BASE_URL` | API 端点（可选，默认 OpenAI） | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 模型名（可选，默认 gpt-4o-mini） | `gpt-4o` |

支持任何 OpenAI 兼容 API（OpenAI / DeepSeek / 智谱 / Moonshot 等）。未配置 `OPENAI_API_KEY` 时自动降级为纯文本 diff 模式。

### 手动运行

```bash
# 降级模式（纯 diff，无需 API key）
.venv/bin/python scripts/analyze_changes.py

# 指定产品
.venv/bin/python scripts/analyze_changes.py --product kimi

# 使用 LLM 分析
OPENAI_API_KEY=sk-... .venv/bin/python scripts/analyze_changes.py
```

### 分析报告格式

`site/generated/change_reports/{id}_{target}_{date}.json`：

```json
{
  "pid": "kimi",
  "name": "Kimi",
  "target": "main",
  "label": "主监控页",
  "url": "https://platform.kimi.com/docs/agreement/userservice",
  "has_old_snapshot": true,
  "analysis_date": "2026-09-09T14:10:00",
  "text_diff": "...",
  "llm_analysis": {
    "has_substantive_change": true,
    "change_summary": "训练授权表述从'模型训练'改为'模型服务优化'",
    "training_policy": {"changed": true, "old": "...", "new": "..."},
    "opt_out_mechanism": {"changed": false, "detail": null},
    "data_retention": {"changed": false, "detail": null},
    "other_changes": [],
    "risk_assessment": "风险等级可能需要从 red 调整为 yellow",
    "recommended_actions": ["更新 key_clauses 中的条款引用", "复核 risk_level"]
  },
  "has_substantive_change": true,
  "change_summary": "训练授权表述从'模型训练'改为'模型服务优化'"
}
```

> 注意：AI 分析结果仅供参考，不自动修改 `site/data/policies/{id}.json`。人工确认分析结论后再更新数据文件。
