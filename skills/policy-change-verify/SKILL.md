---
name: policy-change-verify
description: "本地核实 AI 产品官方政策页面变更。当用户要核实 ai-policy-tracker 仓库中 site/generated/update_status.json 标记的'政策可能已更新'产品、读取 site/generated/pending_verification.json 待核实队列、或指定某个产品 ID（如 claude / gemini / doubao）时，使用本 skill。它提取新旧政策快照 diff、判断变更是实质性条款变化还是噪声，并起草对 site/data/policies/{id}.json 的修改（字段 + timeline 条目）供人工确认。用于替代 GitHub Actions 中 monitor.yml 的 analyze_changes（已移除）/ 建 Issue（已移除）流程；检测→核实的跨轮交接物现为 pending_verification.json，由本地 agent 调用。"
---

# 政策变更本地核实

## 概述
本 skill 把"政策变更核实"从 GitHub Actions 工作流（monitor.yml 里的
`analyze_changes.py` + "创建/更新 Issue" 步骤）迁移为**本地由 agent 驱动的流程**。
agent 调用本 skill 时，读取监控检测结果（`update_status.json` / 快照 / 开放
Issue），对每个被标记的产品目标提取新旧快照 diff，判断变更性质，并起草对
`site/data/policies/{id}.json` 的修改，最终**交由人工确认后再落盘**。

核心原则：**AI 只负责"核实 + 起草补丁"，人工负责"确认 + 应用"**。
绝不在未获用户明确确认前直接修改政策数据文件，也不要自行 commit/push（除非用户要求）。

## 何时使用
- 用户说"核实一下政策变更""看看哪些政策更新了""处理一下 Issue #N"
  "核对 claude/gemini 的变更"等。
- 用户想确认 `update_status.json` 里 `status=="changed"` 的产品是否真改了条款。
- 用户想基于监控结果更新 `site/data/policies/{id}.json` 并补 timeline。

## 工作流程

### 步骤 1：确定要核实的产品与目标
三种来源，任选其一或合并：
1. **检测结果**：读取仓库根 `site/generated/update_status.json`，收集
   `products` 中 `status=="changed"` 的产品，及其 `targets` 里
   `status=="changed"` 的目标键（`main` / `toc` / `tob`）。
   - `status=="failed"` 表示抓取失败（被墙 / SSL / 超时），**不是真实变更**，
     标注为"抓取失败、需人工打开 URL 确认"，不要当作条款变化。
   - `status=="suspicious"` 表示正文过短（疑似 JS 渲染 / 反爬空壳），同样需人工确认。
2. **待核实队列**：读取 `site/generated/pending_verification.json`，其中 `items` 即为本轮及历史未清除的 `changed` 目标（`pid:key` 为键，含 `url` / `first_seen` / `last_seen`）。也可先跑 `policy_verify.py --list` 直接看队列（该脚本优先展示队列）。
3. 用户直接指定某产品 ID（如 `claude`、`gemini`）。

### 步骤 2：提取新旧快照 diff
对每个（产品, 目标）运行本 skill 附带的脚本（**从仓库根目录运行**）：
```bash
# 一次列出所有被标记项（推荐先看这个）
python3 skills/policy-change-verify/scripts/policy_verify.py --list
# 查看单个产品的某个目标
python3 skills/policy-change-verify/scripts/policy_verify.py <product_id> [target]
# 查看单个产品的全部目标
python3 skills/policy-change-verify/scripts/policy_verify.py <product_id> --all-targets
```
脚本输出：目标 URL、旧快照来源（`prev.txt` / `dated:YYYY-MM-DD` / `git:<sha>`）、
旧→新 unified diff（超长截断）、以及该产品当前的 `site/data/policies/{id}.json` 全文。
脚本已自动跳过"内容相同的历史提交"，可规避一次全库重建基线造成的假差异。

### 步骤 3：判断变更性质（实质性 vs 噪声）
结合 diff 与脚本输出的政策 JSON，按 `references/verification_workflow.md`
的判断清单区分：
- **实质性变更**：训练政策（`used_for_training` / `default_state` / `opt_out`）、
  数据留存期限（`data_retention`）、版权归属、责任限制等条款文字实质变化。
- **噪声**：页脚版权年、cookie 横幅、`最后更新 2026-XX-XX` 时间戳、导航 / 布局
  重排、A/B 文案、抓取残缺（`failed` / `suspicious`）等。
若旧快照来自一次"重建基线"提交（git SHA 显示大面积变动但非真实条款），
判定为误报即可，无需深究。

### 步骤 4：起草补丁（仅实质性变更时）
对确属条款变化的目标，按 `references/policy_schema.md` 的结构，起草编辑操作：
- 更新对应 `versions.<toc|tob>`（或顶层，若目标是 `main` 且影响整体）的字段：
  `used_for_training`、`training_note`、`default_state`、`opt_out`、
  `opt_out_method`、`deidentified`、`data_retention`、`copyright`、
  `other_uses`、`risk_level`、`key_clauses`。
- 将涉及版本的 `last_verified` 更新为当天日期（`YYYY-MM-DD`）。
- 若发生里程碑式变化，向 `timeline` 追加 `{ "date": "<当天>", "event": "..." }`。
- 可选：在版本对象里加 / 更新 `verification_notes`（数组，记 `YYYY-MM-DD 逐字复核...`）。
- 顶层 `description` / `analysis_summary` / `key_findings` 若明显过时也可同步。

**关键约束**：把上述修改作为"提议"呈现给用户，**必须等用户确认后再写入文件**。

### 步骤 5：处理噪声 / 失败项
- 噪声或 `failed` / `suspicious`：在回复中标注"误报 / 需人工打开 URL 确认"，不修改数据。
- 某项已核实并更新数据后，运行
  `python3 skills/policy-change-verify/scripts/policy_verify.py --resolve <product_id> [target]`
  从待核实队列移除（这是检测→核实跨轮持久交接的收尾）。

## 资源
- `scripts/policy_verify.py`：提取新旧快照 diff 与当前政策 JSON 的确定性脚本。
- `references/policy_schema.md`：`site/data/policies/{id}.json` 字段与 timeline 格式。
- `references/verification_workflow.md`：实质性 vs 噪声的判断清单与示例。

## 与 monitor.yml 的关系
monitor.yml 现在**只做检测 + 快照入库 + 写待核实队列**（`check_updates.py`）：每周自动发现变化、
把快照提交入库作为跨环境共享的持久历史、把 `changed` 目标写入
`site/generated/pending_verification.json`。原来的"AI 辅助变更分析"（`analyze_changes.py`，已删除）
与"创建/更新 Issue"（已移除）两步不再存在——核实与改数据全部在本地由本 skill 完成，
不再依赖 `OPENAI_API_KEY` 这类仓库 secret。
