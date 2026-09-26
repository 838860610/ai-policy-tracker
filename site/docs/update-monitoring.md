# 更新监控说明

## 概述

本项目采用两层监控机制，并把"政策是否变化"和"抓取是否可信"拆成两条独立信号：

- **检测层**（`scripts/check_updates.py`）：定期检测各 AI 产品的隐私政策、服务条款和 `sources[]` 补充来源是否发生变化（HTML/PDF 正文归一化哈希 + 条件请求）。检测结果写入 `site/generated/update_status.json`，首页会分别展示变更、失败、可疑和未监控状态。正文快照留档到 `site/generated/snapshots/` 并入库，作为跨环境共享的持久历史。
- **待核实队列**：本轮检测为 `changed` 的目标写入 `site/generated/pending_verification.json`，作为"检测 → 核实"的跨轮交接物；在人工 `--resolve` 前，后续 304 不会清除页面告警。
- **抓取健康队列**：本轮抓不到可信正文的目标（被反爬拦截 / 无可用基线 / 降级）写入 `site/generated/monitor_health.json`。它回答的是"监控本身还准不准"，与"政策有没有变"是两回事——政策可能根本没变，但页面已经抓不下来了。
- **核实层（本地）**：维护者在本地调用 `policy-change-verify` skill，提取新旧快照 diff、判断是实质性条款变化还是噪声，并起草对 `site/data/policies/{id}.json` 的修改供人工确认。

### 两套状态为什么要分开

| 维度 | 字段 | 取值 | 含义 |
|------|------|------|------|
| 内容 | `status` | `ok` / `changed` / `failed` / `suspicious` / `skipped` | 政策正文相对上次基线发生了什么 |
| 抓取 | `health` | `ok` / `initialized` / `rebaselined` / `degraded` / `no_baseline` / `blocked` | 这一轮抓到的正文能不能信 |

早期版本只有 `status`，于是"抓取失败"和"政策变更"会混在一起：一次 Cloudflare 挑战会同时污染首页告警和待核实队列。现在：

- 正文确实变了 → `status=changed`，进**待核实队列**，等人核实内容差异；
- 抓取不可信 → `health=degraded/no_baseline/blocked`，进**健康队列**，等人修抓取配置；
- 两者可以同时发生，首页也分别展示。


## 检测原理

为避免误报，脚本不会直接对原始 HTML 做哈希（政策页面普遍含有时间戳、CSRF token、A/B 实验等动态内容，裸哈希几乎每次运行都会误报"已变更"），而是：

1. **正文提取**：剥离 `<script>`、`<style>` 等非正文标签，提取可见文本（使用 BeautifulSoup，未安装时退化为正则去标签）；若目标配置了 `content_selector`，优先按该 CSS 选择器取正文
2. **空白归一化**：压缩行内连续空白、丢弃空行，使哈希对纯排版变化不敏感
3. **归一化哈希**：对归一化后的文本计算 SHA256
4. **条件请求**：携带上次记录的 `ETag` / `Last-Modified`，页面未变化时服务端直接返回 304，不下载正文、零误报
5. **哈希方案版本化**：状态文件中记录 `hash_scheme`；提取算法升级时自动重建基线，而不是误报全部"已变更"
6. **抓取健康判定**：正文过短（默认 < 500 字符）或抓取异常时不覆盖已有基线，只把 `health` 标成降级/无基线/被拦截

### 去噪：让"UI 状态波动"不进哈希

动态 UI 是误报的主要来源。同一条政策、条款正文零差异，却因下列 UI 元素渲染时机不同而长度波动：

| UI 元素 | 实测波动 | 处理方式 |
| --- | --- | --- |
| 语言下拉列表展开与否 | chatgpt/tob 15147 ↔ 15752 字符 | 正文起始标记（`Published:` / `Updated:` + `YYYY年`）之前的头部整体切掉 |
| 新手引导浮层 | doubao-api 11564 ↔ 11593 字符 | 按钮文案（`我知道了 不再提醒` 等）进 `UI_NOISE_PHRASES` |
| 文末推荐挂件 / 反馈区 | qwenwork 7341 ↔ 6066 字符 | 从首个挂件锚点（`精选产品` 等）到文末整体剔除 |
| 页脚 / 版权站壳 | 随渲染时机出现或消失 | 从首个页脚锚点（`京ICP备` 等）到文末整体剔除 |
| 每次加载重新生成的长令牌 | Gemini 隐私页两次抓取令牌不同 | 仅当父节点标记为 token/session/nonce 时移除该长数字 |

两条纪律：

- **位置护栏**：头部截断只在标记出现在全文前 15% 时生效，避免将来某页正文深处出现该词时被误删大段条款（`test_lead_in_marker_guard_still_protects_late_mentions`）。
- **清单要保守**：只剔除**绝不会作为政策条款正文出现**的固定短语。协议正文里可能出现的词不能进清单。改完务必全库扫一遍新短语是否误伤（`grep` 全部 `latest.txt`）。

> **反面教训**：正文起始标记曾用中文的 `生效日期：`，结果腾讯系协议页开头的
> 「文档标题 + 更新日期 + 生效日期」被整段切掉（tencent-yuanbao 少 26 字符、ima 少 62、
> yuanqi 少 28）——而这些字段正是政策版本标识。标记必须用**站点特有且不可省略**的格式
> （OpenAI/英文站的 `Published:` / `Updated:` + `YYYY年`），不能用中文政策文件的通用词。
> 回归由 `test_lead_in_marker_keeps_chinese_title_and_update_date` 锁定。

### browser 渲染取最完整的一次

SPA 页面正文异步渲染，单次抓取可能只出一半正文或只剩页脚壳。脚本固定做 3 次渲染（`BROWSER_RENDER_ATTEMPTS`）并取正文最长的一次（`pick_longest_render`）。

不做"长度超过阈值就提前退出"的优化——各页面完整正文长度差异极大（实测 `support.google.com` 帮助页完整 5.6 万字符，文档站协议页 1.2 万），固定阈值会把渲染未完成的中间态写进基线（实测同页 9500 vs 完整 56422），之后每轮都误报 changed。三次 `goto` 复用同一个 browser 实例，额外成本远小于误报代价。

## 抓取方式与目标级配置

一个**监控目标（target）**是一个可独立抓取、独立比对、独立重试的 URL 单元，用 `pid:key` 标识。key 有 4 类，各自带一个配置载体：

| key | URL 来源 | 配置载体 |
|------|----------|----------|
| `main` | 顶层 `policy_url` | `targets.main` |
| `toc` / `tob` | `versions.toc` / `versions.tob` 的 `policy_link` | `versions.toc` / `versions.tob` |
| `source_*` | `sources[]` 每条的 `url` | `sources[]` 那个条目 |

> `main` 的 URL 就在顶层，天然没有内层对象可挂配置，`targets.main` 是为它专门补的载体，使"每个目标都能独立配置"没有例外。

抓取配置字段与优先级（**目标级 > 产品级 > 全局默认**，顶层字段继续生效，既有数据文件无需迁移）：

| 字段 | 取值 | 说明 |
|------|------|------|
| `fetch_method` | `requests`（默认）/ `browser` | `browser` 用无头 Chromium 抓取，应对 Cloudflare 等 JS 挑战页，依赖可选 playwright |
| `content_selector` | CSS 选择器 | 正文不在 `<main>` / `<article>` 内时指定容器（常见于文档预览页、富文本页） |
| `wait_for_selector` | CSS 选择器 | 浏览器抓取时等待该节点出现即视为已渲染，缩短 SPA 页耗时 |
| `min_body_chars` | 正整数 | 该目标的正文下限，覆盖默认 500 |

配置示例（同一产品里只有企业版条款和 FAQ 页需要浏览器抓取，主监控页仍是普通请求）：

```json
{
  "policy_url": "https://example.com/policy",
  "versions": {
    "tob": {
      "policy_link": "https://example.com/enterprise",
      "fetch_method": "browser"
    }
  },
  "sources": [
    {
      "id": "faq",
      "title": "训练数据 FAQ",
      "url": "https://example.com/faq",
      "fetch_method": "browser",
      "wait_for_selector": ".faq-body",
      "min_body_chars": 800
    }
  ]
}
```

反过来，`main` 需要浏览器而 `toc` 是静态页时，把配置写进 `targets.main` 即可，`toc` 不受影响：

```json
{
  "policy_url": "https://example.com/policy",
  "targets": { "main": { "fetch_method": "browser" } },
  "versions": { "toc": { "policy_link": "https://example.com/terms" } }
}
```

`validate_data.py` 会校验四处载体（顶层 / `targets.main` / `versions.*` / `sources[]`）的 `fetch_method` 取值、选择器类型与正文下限类型；`targets` 里出现 `toc`/`tob` 键或非对象值会直接报错，避免出现"两处配置、优先级不明"。`targets.main` 是纯配置载体，还额外检查拼写错误。

有了目标级配置，`--no-browser` 只会跳过 `browser` 目标，同产品的 `requests` 目标照常检查（早期版本是整个产品一起跳过，且会清空该产品的目标状态——现已改为沿用上次结果）。

> **注意选择器不要用构建产物 class**：SPA 文档站的正文容器 class 常带构建 hash
> （如 `contentFlex-Gj6M`），站点重新构建就会变。`extract_text` 对未命中的选择器会回退到
> 默认启发式，噪声会悄悄回来。要配就配语义稳定的 class / id / 属性，否则宁可只切 `browser`。


## 监控脚本使用方法

### 前置条件

所有 Python 脚本统一使用项目虚拟环境 `.venv` 运行（不污染系统 Python，也规避新版 Python 禁止直接 pip 装包的限制）：

```bash
# 方式一：./start.sh 会自动创建 .venv 并安装基础依赖
./start.sh

# 方式二：手动创建
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # requests + beautifulsoup4 + pypdf + markdown

# 需要抓取浏览器渲染/反爬页面时
.venv/bin/pip install -r requirements-browser.txt
.venv/bin/playwright install chromium
```

### 手动运行

```bash
cd /path/to/ai-policy-tracker

# 默认参数：请求间隔 1.5s，单次超时 30s
.venv/bin/python scripts/check_updates.py

# 自定义参数
.venv/bin/python scripts/check_updates.py --delay 3 --timeout 60

# 未安装 Playwright 时跳过 browser 目标（同产品 requests 目标仍会检查）
.venv/bin/python scripts/check_updates.py --no-browser

# 让存在产品检查失败时返回非零退出码
.venv/bin/python scripts/check_updates.py --fail-on-error

# 只重试某几个产品（其余产品沿用上次状态，不重跑）
.venv/bin/python scripts/check_updates.py --products gemini,minimax

# 只重试具体目标，用于修完抓取配置后验证
.venv/bin/python scripts/check_updates.py --only gemini:main,minimax:source_training_faq

# 调试：不清理已不再监控的孤儿快照
.venv/bin/python scripts/check_updates.py --no-prune
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--delay` | 1.5 | 相邻请求间隔秒数（礼貌抓取，避免触发对方风控） |
| `--timeout` | 30 | 单次请求超时秒数 |
| `--no-browser` | 关闭 | 跳过 `fetch_method=browser` 的目标 |
| `--fail-on-error` | 关闭 | 存在产品检查失败时返回非零退出码 |
| `--products` | 全部 | 只检查指定产品（逗号分隔 pid），其余产品沿用上次状态 |
| `--only` | 全部 | 只检查指定目标，格式 `pid:key`（可逗号分隔） |
| `--no-prune` | 关闭 | 不清理已不再监控的孤儿快照目录 |

网络类错误（超时、连接失败）会自动重试 2 次，按 5s、10s 退避。

### 局部重试：不重跑全量也能验证修复

`--products` / `--only` 属于**局部重试**：只请求被选中的目标，其余产品/目标直接继承上次状态（`partial_run: true`），并自动跳过孤儿快照清理。这样修完一个站点的抓取配置后，验证成本从"全量 70+ 目标十几分钟"降到"单目标几十秒"。

局部重试同样会重算 `update_status.json`、待核实队列和健康队列，因此适合"抓取修好了/改 URL 了"这类收尾动作。


### 输出示例

```
============================================================
AI 政策更新监控脚本
运行时间：2026-09-21 06:00:00
哈希方案：text-v4-bs4（正文文本归一化，按配置来源逐条监控）
============================================================

共 48 个产品需要检查（本次检查 48 个）

  [OK]   ChatGPT (chatgpt·主监控页): 内容未变化（304 Not Modified）
  [新增] Gemini (gemini·主监控页): 首次记录基线
  [可疑] 纳米AI (nano-ai·主监控页): 正文仅 312 字符，疑似 JS 渲染/反爬空壳，无可验证基线
  ...

============================================================
检查完成
  产品: 48，监控目标: 70
  未变化: 30
  已变更: 0
  待核实队列: 0 项（详见 site/generated/pending_verification.json）
  失败:   1
  可疑:   16（正文疑似空壳，未记录基线）
  跳过:   1
  健康队列: 18 项（blocked 0 / 降级 2 / 无基线 16，详见 site/generated/monitor_health.json）
  状态文件: .../site/generated/update_status.json
============================================================

🔧 以下 18 个目标抓取降级（政策未变更，但监控数据不可信）：
  - 纳米AI（nano-ai:main）[no_baseline] 连续 3 轮
    抓取正文过短（312 字符 < 500），疑似 JS 渲染或反爬，无可验证基线
    建议：确认页面是否 JS 渲染或反爬空壳，配置 content_selector / browser 后重试
    可用 --only nano-ai:main 之类的命令单独重试
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
| `[新增]` | 首次检查，记录基线 hash（`health=initialized`，不是异常） |
| `[基线]` | 哈希算法升级或无有效基线，重新记录（`health=rebaselined`） |
| `[失败]` | 请求失败（超时、404 等，重试后仍失败），`health` 为 `degraded`/`no_baseline`/`blocked` |
| `[可疑]` | 正文过短、疑似空壳/反爬，或本地基线缺失 |
| `[跳过]` | URL 为空、未启用监控或显式禁用浏览器抓取 |

### 抓取健康状态（health）

| health | 进入健康队列 | 含义 | 处置 |
|--------|--------------|------|------|
| `ok` | 否 | 正常 | 无需处理 |
| `initialized` | 否 | 首次建立基线，尚无历史可比较 | 无需处理，下一轮起开始比较 |
| `rebaselined` | 否 | 因基线缺失或哈希方案升级而重建 | 人工确认一次新基线是否为真实正文 |
| `degraded` | 是 | 本轮抓取异常，但已保留上次有效快照 | 用 `--only <pid>:<key>` 单独重试并确认正文 |
| `no_baseline` | 是 | 本轮抓取异常且无可验证基线，该产品暂无可靠正文 | 配置 `content_selector` / `fetch_method=browser` 后重试 |
| `blocked` | 是 | 被反爬/限流/权限拒绝（401/403/405/429/451） | 换抓取方式或人工核实来源 |

### update_status.json 格式

```json
{
  "meta": {
    "last_run": "2026-09-21T06:00:00",
    "hash_scheme": "text-v4-bs4",
    "total_products": 48,
    "total_targets": 70,
    "changed": 0,
    "failed": 1,
    "suspicious": 16,
    "skipped": 1,
    "health_issues": 18,
    "health_blocked": 0,
    "health_degraded": 2,
    "health_no_baseline": 16,
    "partial_run": false
  },
  "products": {
    "chatgpt": {
      "name": "ChatGPT",
      "status": "ok",
      "health": "ok",
      "health_issues": 0,
      "url": "https://openai.com/policies/terms-of-use",
      "targets": {
        "main": {
          "url": "https://openai.com/policies/terms-of-use",
          "hash_scheme": "text-v4-bs4",
          "current_hash": "a1b2c3d4e5f6...",
          "fetch_method": "browser",
          "content_etag": null,
          "content_last_modified": null,
          "last_checked": "2026-09-21T06:00:00",
          "last_good_at": "2026-09-21T06:00:00",
          "status": "ok",
          "health": "ok",
          "health_reason": null,
          "message": "内容未变化（304 Not Modified）",
          "last_changed_date": null
        }
      }
    },
    "nano-ai": {
      "name": "纳米AI",
      "status": "suspicious",
      "health": "no_baseline",
      "health_issues": 1,
      "url": "https://www.n.cn/privacy",
      "targets": {
        "main": {
          "url": "https://www.n.cn/privacy",
          "hash_scheme": "text-v4-bs4",
          "current_hash": null,
          "last_checked": "2026-09-21T06:00:00",
          "last_good_at": null,
          "status": "suspicious",
          "health": "no_baseline",
          "health_reason": "render_required",
          "message": "抓取正文过短（312 字符 < 500），疑似 JS 渲染或反爬，无可验证基线",
          "last_changed_date": null
        }
      }
    }
  }
}
```

### monitor_health.json 格式

抓取健康队列完全由 `update_status.json` 重建：目标恢复正常或下线监控后，对应条目会自动消失。

```json
{
  "updated_at": "2026-09-21T06:00:00",
  "items": {
    "nano-ai:main": {
      "pid": "nano-ai",
      "name": "纳米AI",
      "key": "main",
      "label": "主监控页",
      "url": "https://www.n.cn/privacy",
      "health": "no_baseline",
      "health_reason": "render_required",
      "status": "suspicious",
      "message": "抓取正文过短（312 字符 < 500），疑似 JS 渲染或反爬，无可验证基线",
      "last_checked": "2026-09-21T06:00:00",
      "last_good_at": null,
      "consecutive_runs": 3,
      "first_seen": "2026-09-07T06:00:00",
      "last_seen": "2026-09-21T06:00:00",
      "next_action": "确认页面是否 JS 渲染或反爬空壳，配置 content_selector / browser 后重试"
    }
  }
}
```

`consecutive_runs` 是连续不健康轮次；一旦某轮恢复正常，条目被清除，下次再坏重新从 1 开始计数。

### 字段说明

| 字段 | 说明 |
|------|------|
| `meta.last_run` | 最后运行时间（ISO 格式） |
| `meta.hash_scheme` | 当前哈希算法版本 |
| `meta.total_products` | 检查的产品总数 |
| `meta.total_targets` | 检查的监控目标总数 |
| `meta.changed` | 检测到变化的产品数 |
| `meta.failed` | 检查失败的产品数 |
| `meta.suspicious` | 正文可疑或基线缺失的产品数 |
| `meta.skipped` | 跳过检查的产品数 |
| `meta.health_issues` | 健康队列条目数（降级 + 无基线 + 被拦截） |
| `meta.health_blocked` / `health_degraded` / `health_no_baseline` | 三类健康问题各自的目标数 |
| `meta.partial_run` | 本轮是否为局部重试（`--products` / `--only`） |
| `products.{id}.targets.{target}` | 每个 URL 的状态、哈希、ETag、检查时间与健康状态 |
| `targets.{key}.health_reason` | 细分原因：`empty_body` / `render_required` / `blocked` / `network` / `browser_error` / `http_error` / `missing_baseline` / `first_baseline` / `hash_scheme_upgrade` |
| `targets.{key}.last_good_at` | 该目标最后一次成功抓到可信正文的时间；旧状态文件缺该字段时按基线快照的保存时间回填，`no_baseline` 目标为 `null`（从未拿到过可信正文） |
| `targets.{key}.fetch_method` | 本轮实际使用的抓取方式 |
| `products.{id}.status` | 产品聚合状态（ok/changed/failed/suspicious/skipped） |
| `products.{id}.health` | 产品聚合健康状态（取最严重的目标） |
| `products.{id}.health_issues` | 该产品下需要处置的目标数 |
| `products.{id}.message` | 状态描述信息 |
| `products.{id}.last_changed_date` | 最后检测到变化的日期 |


## 监控流程

```
1. 读取 site/data/products.json（ID 索引）
2. 逐个加载 site/data/policies/{id}.json，展开 main / versions / sources[] 监控目标及其抓取配置
3. 读取 site/generated/update_status.json（如存在）中上次的状态
4. 对每个产品（--products / --only 选中的除外）：
   a. 跳过 URL 为空或未启用监控的条目
   b. 仅当 URL、哈希方案和本地快照基线都有效时携带 ETag / If-Modified-Since 发起条件请求
   c. 服务端返回 304 且本地基线有效 → 内容未变化；否则拒绝接受条件响应
   d. 完整抓取 HTML/PDF/文本正文，按 content_selector 取正文，去除导航和明确的动态节点，归一化空白并计算 SHA256
   e. 与已入库的基线快照文本对比（首次基线、URL 变化和哈希方案变化单独处理）
   f. 记录检查结果与新 ETag / Last-Modified；正文过短或抓取失败时不覆盖基线，只更新 health
   g. 等待 --delay 秒再检查下一个（礼貌抓取）
5. 写入 site/generated/update_status.json（首页读取展示）
6. 将 changed 目标合并写入 site/generated/pending_verification.json，并在 resolve 前保留页面告警
7. 将 degraded / no_baseline / blocked 目标写入 site/generated/monitor_health.json（其余产品/目标沿用上次状态）
8. 全量运行时清理已不再监控的孤儿快照（--no-prune 可关闭）
9. 输出告警信息
```

## 故障排查

首页出现"抓取降级明细"时，按 `next_action` 逐条处理：

1. **看 `last_good_at`**：有值说明只是本轮抓取挂了，页面展示的历史正文仍可用；为 `null` 说明这个目标从来没有可信正文。
2. **看 `consecutive_runs`**：只出现 1 轮多半是网络抖动；连续多轮说明抓取方式本身有问题。
3. **先试更长超时**：`--only <pid>:<key> --timeout 60`。连接超时类（`network`）问题常由此解决。
4. **再改抓取配置**（详见下节）：正文在非标准容器 → 配 `content_selector`；页面是 JS 渲染 → 配 `fetch_method: "browser"`（必要时加 `wait_for_selector`）；被 403/429 → 换 `browser` 或人工核实来源。
5. **验证**：`--only <pid>:<key>` 重跑，确认 `health` 回到 `ok`/`initialized`，且健康队列里对应条目消失。

不要用 `--no-prune` 之外的方式绕过清理，也不要手工编辑 `update_status.json` 里的 `current_hash` 来"消掉"告警——快照和哈希必须由脚本重新生成。

### 修好配置后第一轮必然报 changed

把空壳目标从 `requests` 切到 `browser`（或补上 `content_selector`）后，**第一次重跑通常是 `changed`，这是预期行为，不是误报**。

原因：旧的 baseline 往往不是"完整的旧正文"，而是页面标题、导航菜单或空壳。空壳页因为长期抓不到正文、哈希一直不变，看起来"很健康"，实际上监控的是噪声。切到 browser 后第一次抓到真实协议全文，与旧 baseline 自然不同。

正确处置：用 `policy_verify.py <pid>` 看 diff。若确认是"旧 baseline 是噪声、新的是真实协议正文"，用 `--resolve <pid>` 承认新基线；只有 diff 显示**协议条款文字本身**变了，才按实质性变更去改 `policies/{id}.json`。

判断依据很直观：旧快照只有 1-2 行、且内容是页面标题或菜单项（如「腾讯隐私保护平台」「文档中心 火山方舟 Agent Plan …」），就是抓取方式问题，不是政策变更。

### 什么时候该换源而不是修抓取

`browser` 也拿不到正文时（典型是硬登录墙：协议正文只在登录后可见、无静态公开版），`browser` 只会得到空壳或登录页。这时按项目既有做法处理，优先级从高到低：

1. **`sources[]` 登记同一政策的静态可读页面**（CDN 上的 `.htm`、FAQ 页、协议 PDF 都算）——换源时要人工确认政策等价性；
2. **`monitor: false`** —— 确实没有独立公开政策页的占位条目，数据保留、不做自动监控，避免长期噪声进健康队列。

> 注意：选 `sources[]` 来源时要确认它**本身是静态可读的**。`minimax/source_platform_privacy` 就是一次反面例子——登记的是 `platform.minimaxi.com/protocol/privacy-policy`，本身是 Next.js 空壳，结果监控目标从 1 个空壳变成 2 个空壳。登记前先 `curl` 一下看静态 HTML 里有没有正文。

> `baichuan` 是另一个反面教材的**反面**：静态 HTML 里有 `captchaContainer`（登录/验证码组件），看起来像硬登录墙，实际用 browser 渲染后能拿到完整《百川用户协议》（13437 字符）。**先试跑拿证据再决定降级方案**，别凭静态 HTML 的特征猜。

### 已知残留：容器内渲染完整度仍会波动

`content_selector` 能消除"选错 root"（页面有时包 `<main>`、有时不包），但消除不了"容器内内容没渲染完"。`doubao-api` 是已知案例：`#app-content` 内实测 11564 ↔ 20934 字符波动（差 80%），三次渲染取最长仍偶发拿到残缺版，于是每几轮误报一次 `changed`。

这类页面的共同特征：正文极长（2 万字符以上）且分批注入。三个可选应对，按成本排序：

1. **接受误报**（当前做法）——`changed` 进待核实队列，`policy_verify` 一眼能看出是"同一份协议、一个长一个短"，`--resolve` 收尾即可。误报不会静默出错，也不会污染数据；
2. **换更短的来源**——同一政策的 FAQ / 摘要页通常比全文页稳定得多；
3. **接受更高的误报率**——若该政策变动频繁，宁可多看几次 `changed`。

不建议的做法：为了压住误报而调高 `min_body_chars`。那会把"渲染未完成"误判成"空壳降级"，反而让健康队列长期亮红灯，把真问题淹没掉。

### 不要给构建产物 class 配 content_selector

文档站（SPA + CSS-in-JS）的正文容器 class 常带构建 hash（如 `contentFlex-Gj6M`），站点每次重新构建都会变。把它写进 `content_selector` 看似精确，实际会在下次构建后静默失效——`extract_text` 对未命中的选择器会回退到默认启发式，噪声又回来了。判断标准：class 名里带随机 hash 就不配。

**优先配稳定的 `id`**。`doubao-api` 就是这么修好的：文档站页面结构会波动（有时把正文包进 `<main>`、有时不包），`extract_text` 的 root 因此在"仅正文 20951 字符"和"导航+正文 12500 字符"之间跳变，每轮都误报 changed。锁定 `#app-content`（id 由站点保证稳定）后连续多轮"内容未变化"。

### browser 的 locale 与访问地区会影响站点返回的版本

`fetch_browser` 用 `locale="zh-CN"` 打开页面，**多语言/多地区站点会据此切换返回版本**，而 `requests` 路径没有这个行为。两个已实测的后果：

- **语言**：`policies.google.com` 从英文版变成中文版——同一份政策的不同语言版本，正文完全不同，会触发一次 changed。这不是 bug（中文读者看中文版更合适），确认语言稳定后 `--resolve` 承认即可；
- **地区（更麻烦）**：`policies.google.com/terms` 会按访问来源 IP 切换国家版本条款。本地（中国 IP）取到的是**新加坡**版，CI（GitHub 美国 runner）取到的是**美国**版，正文有实质差异（服务提供者、适用法律等）。**这会导致每次在不同网络环境运行都报 changed，且无法靠 `--resolve` 根治。**

唯一可靠解法是在 URL 上显式锁定地区与语言参数（Google 政策页支持 `gl` / `hl`，如 `?gl=US&hl=zh-CN`）。这会改动 `policy_url`，属于数据变更，需人工确认后单独提交——**不要靠反复 resolve 掩盖**，那只是让队列好看，下次换网络环境又会炸。

相比之下，`support.google.com` 的帮助页不按地区变化（`gemini/toc` 只受渲染时机影响，已由 3 次取最长的机制解决）。


## 首页如何展示监控结果

首页 `site/js/app.js` 会尝试加载 `site/generated/update_status.json` 与 `site/generated/monitor_health.json`：

- **文件不存在**（从未运行过监控）：页面不显示任何监控信息
- **全部无变化且无异常**：显示监控上次运行时间和“未检测到政策变更”
- **存在异常**：显示失败、正文可疑、未监控产品和抓取降级目标数量，不把异常伪装成正常
- **检测到变更**：显示醒目的告警横幅，列出可能已更新的产品（可点击进入详情），对应产品的名称旁也会标注 ⚠️
- **存在抓取降级**：横幅下方展开“抓取降级明细”，逐条列出产品、目标、健康类型、失败原因和上次成功抓取时间，并给出建议动作

> 注意：`site/generated/update_status.json`、`site/generated/monitor_health.json` 与 `site/generated/snapshots/` 都由监控流程生成并**入库**——前两者供首页与 Pages 直接读取展示监控状态与健康队列，后者作为跨环境共享的持久历史供本地 agent 做 diff。`monitor.yml` 每次运行后自动提交这三者与 `pending_verification.json`。


## 本地核实（policy-change-verify skill）

监控只负责"发现变化 + 留档"，**不在 CI 内做 AI 分析，也不自动建 Issue**。核实与改数据全部在本地由 `policy-change-verify` skill 完成。

当 `update_status.json` 出现 `changed`，或 `pending_verification.json` 有待核实项时：

1. **列出待核实项**：`python3 skills/policy-change-verify/scripts/policy_verify.py --list`
2. **查看某项目新旧 diff**：`python3 skills/policy-change-verify/scripts/policy_verify.py <product_id> [main|toc|tob|source_*]`
   - 脚本从 `prev.txt` / 日期存档 / git 历史中取回旧快照（自动跳过内容相同的重基线提交），与 `latest.txt` 做 unified diff
   - 同时输出该产品当前的 `site/data/policies/{id}.json`，供判断
3. **判断变更性质**：按 `references/verification_workflow.md` 清单区分——训练政策/退出机制/留存期限等条款文字实质变化为**实质性**；页脚版权年、时间戳、导航重排、A/B 文案、抓取失败（`failed`）/空壳（`suspicious`）为**噪声**
4. **起草补丁**：对实质性变更，按 `references/policy_schema.md` 起草对 `versions.<tier>` 字段与 `timeline` 的修改，**必须等人工确认才写入**
5. **收尾**：核实并更新数据后，`python3 skills/policy-change-verify/scripts/policy_verify.py --resolve <product_id> [target]` 同时清除待核实队列项和页面告警

> 注意：核实结论仅供参考，不自动修改 `site/data/policies/{id}.json`。人工确认后再更新数据文件，并同步 `last_verified` 与 `timeline`；`--resolve` 会同时更新待核实队列和页面告警。
