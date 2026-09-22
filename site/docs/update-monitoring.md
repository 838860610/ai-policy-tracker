# 更新监控说明

## 概述

本项目采用两层监控机制：

- **检测层**（`scripts/check_updates.py`）：定期检测各 AI 产品的隐私政策页面是否发生变化（正文归一化哈希 + 条件请求）。检测结果写入 `site/generated/update_status.json`，**首页读取并展示监控状态**——检测到变更时在表格上方显示告警横幅并在对应产品名旁标注 ⚠️。正文快照留档到 `site/generated/snapshots/` 并入库，作为跨环境共享的持久历史。
- **待核实队列**：本轮检测为 `changed` 的目标写入 `site/generated/pending_verification.json`，作为"检测 → 核实"的跨轮交接物（不再用 GitHub Issue）。
- **核实层（本地）**：维护者在本地调用 `policy-change-verify` skill，提取新旧快照 diff、判断是实质性条款变化还是噪声，并起草对 `site/data/policies/{id}.json` 的修改供人工确认。

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
哈希方案：text-v3-bs4（正文文本归一化，含提取器标识）
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
    "hash_scheme": "text-v3-bs4",
    "total_products": 12,
    "changed": 1,
    "failed": 0,
    "skipped": 0
  },
  "products": {
    "chatgpt": {
      "url": "https://openai.com/policies/terms-of-use",
      "hash_scheme": "text-v3-bs4",
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
      "hash_scheme": "text-v3-bs4",
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
   e. 与已入库的基线快照文本对比（哈希仅作快速路径；哈希方案升级时只要文本未变就判未变，不会整库误报）
   f. 记录检查结果与新 ETag / Last-Modified
   g. 等待 --delay 秒再检查下一个（礼貌抓取）
5. 写入 site/generated/update_status.json（首页读取展示）
6. 将 changed 目标合并写入 site/generated/pending_verification.json（待核实队列，跨轮持久交接）
7. 输出告警信息
```

## 首页如何展示监控结果

首页 `site/js/app.js` 会尝试加载 `site/generated/update_status.json`：

- **文件不存在**（从未运行过监控）：页面不显示任何监控信息
- **全部无变化**：表格上方显示一行"政策监控上次运行：…，未检测到政策变更"
- **检测到变更**：显示醒目的告警横幅，列出可能已更新的产品（可点击进入详情），对应产品的名称旁也会标注 ⚠️

> 注意：`site/generated/update_status.json` 与 `site/generated/snapshots/` 都由监控流程生成并**入库**——前者首页与 Pages 直接读取展示监控状态，后者作为跨环境共享的持久历史供本地 agent 做 diff。`monitor.yml` 每次运行后自动提交这两者与 `pending_verification.json`。

## 本地核实（policy-change-verify skill）

监控只负责"发现变化 + 留档"，**不再在 CI 内做 AI 分析、也不再自动建 Issue**。核实与改数据全部在本地由 `policy-change-verify` skill 完成（项目级 skill，克隆仓库即可用）。

当 `update_status.json` 出现 `changed`，或 `pending_verification.json` 有待核实项时：

1. **列出待核实项**：`python3 skills/policy-change-verify/scripts/policy_verify.py --list`
2. **查看某项目新旧 diff**：`python3 skills/policy-change-verify/scripts/policy_verify.py <product_id> [main|toc|tob]`
   - 脚本从 `prev.txt` / 日期存档 / git 历史中取回旧快照（自动跳过内容相同的重基线提交），与 `latest.txt` 做 unified diff
   - 同时输出该产品当前的 `site/data/policies/{id}.json`，供判断
3. **判断变更性质**：按 `references/verification_workflow.md` 清单区分——训练政策/退出机制/留存期限等条款文字实质变化为**实质性**；页脚版权年、时间戳、导航重排、A/B 文案、抓取失败（`failed`）/空壳（`suspicious`）为**噪声**
4. **起草补丁**：对实质性变更，按 `references/policy_schema.md` 起草对 `versions.<tier>` 字段与 `timeline` 的修改，**必须等人工确认才写入**
5. **收尾**：核实并更新数据后，`python3 skills/policy-change-verify/scripts/policy_verify.py --resolve <product_id>` 从待核实队列移除该项

> 注意：核实结论仅供参考，不自动修改 `site/data/policies/{id}.json`。人工确认后再更新数据文件，并同步 `last_verified` 与 `timeline`。
