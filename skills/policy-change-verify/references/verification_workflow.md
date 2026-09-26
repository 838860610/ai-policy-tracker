# 变更性质判断清单（实质性 vs 噪声）

监控脚本只报告"文本哈希变了"，无法区分下列两类。本清单用于人工（agent）判断。

## 零、先分清两套状态：`status` 与 `health`

| 字段 | 回答的问题 | 该走哪条路 |
| --- | --- | --- |
| `status`（`ok` / `changed` / `failed` / `suspicious`） | 政策正文相对基线**变没变** | `changed` → 走本清单一～五；`failed` / `suspicious` → 一 |
| `health`（`ok` / `initialized` / `rebaselined` / `degraded` / `no_baseline` / `blocked`） | 这一轮**抓到的正文能不能信** | 非 `ok`/`initialized`/`rebaselined` → 修抓取配置，**不改数据** |

`health` 类问题的处置（`policy_verify.py --list` 末尾会列出）：

1. `--only <pid>:<key> --timeout 60` 单独重试，先排除网络抖动；
2. `last_good_at` 为 `null` 说明该目标从来没有可信正文，正文多半在非标准容器或需 JS 渲染 →
   在**该目标的配置载体**里加 `content_selector`，或设 `fetch_method: "browser"`
   （必要时加 `wait_for_selector`）。载体对应关系：`main` → `targets.main`，
   `toc`/`tob` → `versions.toc`/`versions.tob`，`source_*` → `sources[]` 那个条目；
   优先级为 目标级 > 产品级 > 全局默认。
3. 重试后 `health` 回到 `ok` / `initialized` 即视为修复完成；`monitor_health.json` 中对应条目会自动消失。

注意：连接超时且本机网络本身就访问不了该域名（境外政策站点在受限网络常见）时，
`browser` 也无济于事——这类目标应以 GitHub Actions 上的监控结果为准。

### 空壳目标改抓取方式后，第一轮 changed 多半不是政策变更

把 `requests` 切成 `browser`（或补 `content_selector`）后首次重跑常报 `changed`，原因是旧 baseline
存的是页面标题 / 导航菜单 / 空壳，而不是完整协议正文——空壳页长期抓不到正文、哈希不变，
看起来"很健康"，实际监控的是噪声。判据：旧快照只有 1-2 行且是标题或菜单项
（如「腾讯隐私保护平台」「文档中心 …」）→ 抓取方式问题，`--resolve` 承认新基线即可；
只有 diff 显示协议条款文字本身变化，才按实质性变更改数据。

## 一、直接排除：不是真实条款变化

- **`status == "failed"`**：抓取失败（被墙 / SSL / 超时 / 403）。例如 `gemini`
  在受限网络环境下常直接连不上 `policies.google.com`。→ 标"抓取失败，需人工打开 URL 确认"，不改数据。
- **`status == "suspicious"`**：抓取正文过短（疑似 JS 渲染 / 反爬空壳）。→ 需人工确认抓取目标，不改数据。
- **重建基线误报**：若 `policy_verify.py` 报告的旧快照来源是某次大面积变动的
  git 提交，且 diff 看起来是"整页重排"而非具体条款改动，多半是哈希方案/提取器
  升级导致的全库重算。→ 标误报；脚本已尽量跳过内容相同的历史提交，若仍命中可加大 `--depth` 再取更早基线。

## 二、噪声（虽文本变了，但非政策条款）

典型可忽略：
- 页脚版权年份（`© 2024` → `© 2026`）。
- "最后更新于 2026-XX-XX" 之类的动态时间戳。
- 新增/变动的 cookie 同意横幅、_region 选择器、导航菜单、布局重排。
- A/B 文案、营销标语微调、错别字修正。
- 帮助中心文章的小修（如 `claude` 的 `toc` 指向的是一篇帮助文章而非正式条款，变动频繁且非约束性）。

判断技巧：diff 里若出现的是"免责声明/引导文案/按钮文字"而非
"我们如何使用你的数据 / 保留多久 / 是否用于训练"等约束性陈述，基本是噪声。

## 三、实质性变更（需起草补丁）

命中以下任一维度，才视为真实条款变化：
- **训练政策**：`used_for_training` 真假翻转、`default_state` 变化（默认开启↔关闭）、
  `opt_out` / `opt_out_method` 变化。
- **数据留存**：`data_retention` 的期限、起算点、自动删除设置变化。
- **版权 / 授权范围**：`copyright`、`other_uses` 变化。
- **去标识化**：`deidentified` 变化。
- **责任限制 / 争议解决 / 服务终止**等重大条款。

## 四、确认手段

1. 优先看 `policy_verify.py` 的 diff + 当前政策 JSON，对比条款文字。
2. 必要时打开 `update_status.json` 里给出的真实 URL 复核（尤其 `failed` 项）。
3. 对 `key_clauses` 的改动务必回到原文逐字核对，标注出处与"最后更新"日期。

## 五、输出约定

- 实质性变更：给出"提议修改"——列出要改的字段新值、要追加的 timeline 条目，
  等用户确认后写入。
- 噪声 / 失败：明确标注"误报 / 需人工打开 URL 确认"，不改动数据文件。
- 若已逐条核实完待核实项，使用 `--resolve` 清除队列并同步页面告警。
