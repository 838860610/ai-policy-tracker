# 政策数据文件结构（site/data/policies/{id}.json）

每个产品一个文件，文件名即产品 ID（如 `claude.json`、`gemini.json`、`doubao.json`）。
所有产品 ID 列表见 `site/data/products.json` 的 `products` 数组（仅顺序索引，不重复存数据）。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 产品 ID（与文件名一致） |
| `name` | string | 中文/英文产品名 |
| `company` | string | 厂商 |
| `region` | string | 地区，如 `中国` / `美国` |
| `description` | string | 一句话概述训练/隐私要点 |
| `policy_url` | string | 顶层监控页 URL（对应监测目标 `main`） |
| `last_verified` | string | 最近核实日期 `YYYY-MM-DD` |
| `versions` | object | 见下，键为 `toc` / `tob`（可只含其一） |
| `timeline` | array | 里程碑事件，元素见下 |
| `analysis_summary` | string | 综述 |
| `key_findings` | array<string> | 关键发现 |
| `recommendations` | array<string> | 给用户建议 |
| `icon` | string | emoji 图标 |
| `product_url` | string | 产品主页 |

## versions.{toc|tob} 字段

`tro`/`tob` 分别对应监测目标 `toc`（个人版条款）、`tob`（企业版条款）。
每个版本对象字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `used_for_training` | bool | 是否将用户输入/输出用于模型训练 |
| `training_note` | string | 训练政策详述（含默认状态、例外、引文背景） |
| `default_state` | string | `默认开启（可关闭）` / `默认关闭` / 其他表述 |
| `opt_out` | string | `设置开关` / `无需退出` / `由组织协议约定` 等 |
| `opt_out_method` | string | 如何退出（设置路径 / 默认即不训练等） |
| `deidentified` | bool | 是否去标识化处理 |
| `data_retention` | string | 数据留存期限表述 |
| `copyright` | string | 内容版权归属（通常 `用户所有`） |
| `other_uses` | string | 其他用途（如 `模型训练、品牌推广`） |
| `risk_level` | string | `red` / `yellow` / `green` |
| `key_clauses` | array<string> | 原文引文清单（带出处与日期） |
| `policy_link` | string | 该版本的监测 URL（对应 `toc`/`tob` 目标） |
| `last_verified` | string | 该版本最近核实日期 `YYYY-MM-DD` |
| `label` | string | 版本中文名，如 `个人版` / `Claude for Work` |
| `verification_notes` | array<string> | （可选）复核记录，格式 `YYYY-MM-DD 逐字复核：...` |

## timeline 元素

```json
{ "date": "2025-09-28", "event": "消费者条款更新：对话默认用于模型训练（退出式），保留最长5年" }
```

## risk_level 口径（来自项目方法论）

标 `green` 需**四项同时满足**：① 默认不训练 / 可 opt-out；② 去标识化；
③ 留存明确且 ≤ 30 天；④ 版权归用户。否则按缺失项标 `yellow` 或 `red`。

## 起草补丁时的注意点

- 改了某个版本条款 → 同步更新该版本的 `last_verified` 为当天日期。
- 仅当发生里程碑变化（如训练默认状态翻转、留存期限变更）才追加 `timeline`。
- `key_clauses` 优先用**逐字原文引文**并标注出处与"最后更新"日期，避免意译。
- 顶层 `description` / `analysis_summary` / `key_findings` 若因本次变更而过时，一并更新。
- 所有修改先作为"提议"呈现给用户，确认后再写入。
