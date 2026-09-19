# 贡献指南

感谢您对 AI 用户政策追踪器项目的关注！欢迎贡献政策更新、新增产品和改进建议。

参与本项目即表示同意遵守 [行为准则](CODE_OF_CONDUCT.md)；安全相关问题请按 [安全政策](SECURITY.md) 私密报告。

## English quick start

The rest of this guide is in Chinese. The essentials:

1. **One file per product**: `site/data/policies/{id}.json` is the single source of truth (name, company, per-version policy fields, timeline, cited clauses). `site/data/products.json` only lists product IDs in display order.
2. **Every claim needs evidence**: quote the official policy verbatim in `key_clauses`, and set `last_verified` to the date you checked.
3. **Before opening a PR**, run (after `./start.sh` or `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`):

   ```bash
   .venv/bin/python scripts/validate_data.py          # must report 0 errors
   .venv/bin/python scripts/gen_readme_table.py --check
   python3 -m unittest discover -s tests              # regression tests
   ```

4. **Commit message**: `update: ...` / `add: ...` / `fix: ...` / `docs: ...` / `feat: ...`
5. In the PR description, always include the official source URL(s) you verified against.

Questions are welcome via Issues — use the "数据纠错" template if you spotted wrong data.

## 数据模型（重要）

- **`site/data/policies/{id}.json` 是每个产品唯一的数据源**，包含该产品的名称、公司、版本政策、时间线等全部字段
- `site/data/products.json` 只维护产品 ID 的排列顺序（定义首页/README 表格的展示顺序）与项目元信息，**不存储产品数据**
- 修改产品数据只需要改 `site/data/policies/{id}.json` 一个文件，不存在需要同步的两份数据
- **目录分层**：`data/` 只放人工维护的源数据（`products.json` + `policies/`）；脚本产出一律写入 `site/generated/`（`bundle.json`、`update_status.json`、`pending_verification.json`、`snapshots/`、`og-card.png`），**不要手工编辑**这些文件，改动会被下次 CI 覆盖

## 如何贡献政策更新

### 1. 发现政策变更

当监控（`check_updates.py`）检测到政策变更时，CI 会自动：

1. 保存新旧快照到 `site/generated/snapshots/{id}/{target}/`（`latest.txt` 当前、`prev.txt` 变更前）
2. 把 `changed` 目标写入 `site/generated/pending_verification.json`（待核实队列）

**人工跟进步骤**（在本地用 `policy-change-verify` skill）：

1. 运行 `python3 .codebuddy/skills/policy-change-verify/scripts/policy_verify.py --list` 查看待核实项
2. 对每项运行 `python3 .codebuddy/skills/policy-change-verify/scripts/policy_verify.py <product_id> [target]` 看新旧 diff
3. 判断是实质性条款变更还是噪声（页脚年/时间戳/导航重排/抓取失败等属噪声）
4. 如为实质变更：访问官方政策页面，更新 `site/data/policies/{id}.json`，同步 `last_verified` 与 `timeline`
5. 核实并更新数据后，运行 `python3 .codebuddy/skills/policy-change-verify/scripts/policy_verify.py --resolve <product_id>` 从队列移除

### 2. 新增产品

如需添加新的 AI 产品：

1. 在 `site/data/policies/` 下创建 `{id}.json` 详细政策文件（id 用小写英文+连字符，如 `github-copilot.json`）
2. 在 `site/data/products.json` 的 `products` 数组中加入该 ID（决定展示顺序）
3. 确保所有必填字段都已填写
4. 运行 `python3 scripts/gen_readme_table.py` 重新生成 README 汇总表

### 增删产品后必须同步生成产物

新增或删除产品（即改动 `site/data/products.json` 的 `products` 数组）后，**必须重新生成/同步站点产物**，否则 CI 的回归测试会直接红灯：

```bash
# 重新生成 site/generated/bundle.json（首页数据合并包，由 products.json + 全部 policies 重建）
.venv/bin/python scripts/gen_data_bundle.py
```

`site/sitemap.xml` 目前是入库的静态文件（不由脚本自动生成），增删产品时需手工同步：在 `<url>` 列表中加入或删除对应的 `<loc>…/detail.html?id=<id></loc>` 条目。测试 `test_sitemap_matches_products` 会校验 sitemap 与 `products.json` 的 id 集合**完全一致**，多一个少一个都失败。

> 实战踩坑：曾删除 `pangu`/`skyreels` 两个产品后漏了重新生成上述两个产物，导致 `test_bundle_is_slim_and_complete` 与 `test_sitemap_matches_products` 双双失败、CI 红灯。记住——`products.json` 一变，这两个文件必须跟着变。

> 注：`update_status.json` / `pending_verification.json` / `snapshots/` 由监控脚本每轮从当前索引重建，已删除产品的旧条目会在下一轮监控后自动消失，无需手工清理。

### 3. 提交 PR

```bash
# 创建分支
git checkout -b update/xxx-policy

# 修改文件
# ... 编辑数据文件 ...

# 提交前运行校验（首次请先创建虚拟环境，见下方"运行验证"）
.venv/bin/python scripts/validate_data.py
.venv/bin/python scripts/gen_readme_table.py --check
python3 -m unittest discover -s tests

# 提交
git add -A
git commit -m "update: 更新 XXX 产品政策信息"

# 推送并创建 PR
git push origin update/xxx-policy
```

## 数据格式规范

### products.json（仅索引）

```json
{
  "meta": { "project": "...", "last_updated": "YYYY-MM-DD", "...": "..." },
  "products": ["tencent-yuanbao", "doubao", "deepseek"]
}
```

### policies/{id}.json 顶层字段

```json
{
  "id": "product-id",            // 必须与文件名一致，小写英文+连字符
  "name": "产品名称",
  "company": "公司名称",
  "region": "地区",               // 中国/美国/等
  "description": "产品简介",
  "policy_url": "官方政策URL",    // 监控脚本抓取目标
  "last_verified": "YYYY-MM-DD",
  "versions": { "toc": { ... }, "tob": { ... } },
  "timeline": [
    { "date": "YYYY-MM", "event": "事件描述" }
  ],
  "analysis_summary": "分析摘要",
  "key_findings": ["发现1", "发现2"],
  "recommendations": ["建议1", "建议2"],
  "icon": "🛡️",                  // 可选，展示用图标
  "product_url": "产品主页URL"    // 可选
}
```

### 版本字段 (versions.toc / versions.tob)

```json
{
  "used_for_training": true,     // 布尔值
  "training_note": "训练说明",
  "default_state": "默认开启",    // 默认开启/默认关闭
  "opt_out": "设置开关",          // 设置开关/邮件申请/无需退出/合同约定
  "opt_out_method": "退出操作说明",
  "deidentified": false,         // 布尔值
  "data_retention": "30天",
  "copyright": "用户所有",
  "risk_level": "red",           // green/yellow/red
  "key_clauses": ["政策原文条款摘录1", "条款2"],
  "policy_link": "版本专属政策链接",
  "other_uses": "其他用途说明",
  "label": "个人版"               // 详情页标签页文案
}
```

> **注意**：`key_clauses` 必须是政策原文摘录，不要填"待核实"占位文字或评述性文字。`validate_data.py` 会对占位文字给出警告。
>
> **不要把核实过程写进 `key_clauses`**：诸如"该文档已 404""此条引自 A 协议用于对比""2026-08-30 修正了条款编号"这类内容，请放到可选的 `verification_notes`（数组）里——`key_clauses` 会被详情页当作厂商条款渲染，混进核对记录会误导读者。

### 其他可选字段

| 字段 | 位置 | 说明 |
|------|------|------|
| `verification_notes` | `versions.toc` / `versions.tob` | 核实说明数组（非政策原文），不参与条款展示 |
| `monitor` | 顶层 | 设为 `false` 时该产品**不纳入自动监控**。适用于没有独立公开政策页、政策 URL 只能指向产品首页的占位条目，否则监控脚本会对首页做正文哈希，产生持续误报 |
| `toc_note` / `tob_note` | 顶层 | 该版本无数据时的书面说明（填了就不会产生"缺少版本数据"警告） |

## 风险等级评定标准

| 等级 | 颜色 | 条件 |
|------|------|------|
| 低风险 | 🟢 green | 不训练 + 去标识化 + 短期留存 |
| 中风险 | 🟡 yellow | 训练但有退出机制，或留存期较长 |
| 高风险 | 🔴 red | 训练且无退出机制，或长期留存 |

## PR 提交说明

### 提交信息格式

- `update: 更新 XXX 政策信息` — 更新现有产品政策
- `add: 新增 XXX 产品` — 添加新产品
- `fix: 修复 XXX 数据错误` — 修正错误数据
- `docs: 更新文档` — 文档变更
- `feat: 新功能` — 新功能开发

### PR 要求

1. **数据准确**：所有信息必须来源于官方政策，不得推测
2. **核实日期**：更新 `last_verified` 为实际核实日期
3. **格式一致**：遵循现有数据文件的格式规范
4. **校验通过**：`scripts/validate_data.py` 0 错误、`gen_readme_table.py --check` 通过、`python3 -m unittest discover -s tests` 全绿
5. **描述清晰**：PR 描述中说明变更原因和信息来源 URL

## 核实要求

### 必须核实的信息

- [ ] 是否使用用户数据训练模型
- [ ] 默认状态（开启/关闭）
- [ ] 退出机制是否存在及操作方法
- [ ] 数据留存期限
- [ ] 是否去标识化
- [ ] 版权归属
- [ ] 政策链接有效性

### 核实注意事项

1. **使用最新政策**：确保查阅的是最新版本的隐私政策
2. **区分版本**：注意个人版和企业版的差异
3. **交叉验证**：对照产品实际设置界面验证政策描述
4. **记录来源**：在 PR 描述中注明信息来源 URL
5. **标注日期**：准确记录核实日期

## 运行验证

提交 PR 前，请验证。所有 Python 脚本统一使用项目虚拟环境 `.venv`（避免污染系统 Python，也规避新版 Python 禁止直接 pip 装包的限制）：

```bash
# 首次：创建虚拟环境并安装依赖（或直接跑 ./start.sh 自动完成）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 数据结构校验（0 错误才可提交）
.venv/bin/python scripts/validate_data.py

# README 汇总表是否与数据一致
.venv/bin/python scripts/gen_readme_table.py --check

# 回归测试（标准库 unittest，无需额外依赖）
python3 -m unittest discover -s tests -v

# 启动本地服务预览（自动打开浏览器；根目录为 site/，与线上一致）
./start.sh
# 或手动：python3 -m http.server 8080 --directory site，访问 http://localhost:8080 检查页面
```

> **文档约定**：`site/docs/` 下的 `methodology` / `update-monitoring` 是线上站点与 `sitemap.xml` 直接引用的页面，**必须入库**。
> - **`.md` 是唯一源，`.html` 由 `scripts/gen_docs.py` 渲染生成，不要手工编辑 html**（此前两份手工维护导致 html 长期停留在旧版本）；CI 会跑 `--check`，不一致即失败
> - `site/docs/internal/` 存放内部工作底稿（核实报告、优化清单），已被 `.gitignore` 忽略，站点不得引用其中的文件（测试 `tests/test_scripts.py` 会校验这一点）

### 其他维护脚本

```bash
# 条款提取工具：从协议 HTML 中按标准同义词组提取关键条款上下文
.venv/bin/python scripts/extract_clauses.py <协议.html>

# 生成数据合并包（首页加载加速，CI 会自动生成）
.venv/bin/python scripts/gen_data_bundle.py

# 生成社交分享卡片（需额外安装 Pillow：.venv/bin/pip install pillow）
.venv/bin/python scripts/gen_og_image.py

# 运行政策更新监控（检查各产品政策页面是否变化，写待核实队列）
.venv/bin/python scripts/check_updates.py

# 文档页生成：site/docs/*.md 是唯一源，*.html 由脚本渲染（不要手工改 html）
.venv/bin/python scripts/gen_docs.py            # 重新生成
.venv/bin/python scripts/gen_docs.py --check    # CI 用：校验是否已最新
```

### 转录型字段联动复审

更新产品数据时，注意以下字段需联动复审（避免更新一处而遗漏关联字段）：

- `key_clauses` 更新时检查 `other_uses` 是否需同步（元宝案例：条款更新但 other_uses 未同步）
- `training_note` / `used_for_training` 更新时检查 `description` 是否需同步（豆包案例）
- 引用旧版协议字样（如"不可撤销""品牌推广"）时，检查是否需更新为新版表述
- `risk_level` 变更时检查 `key_clauses` 佐证是否充分

### 变更核实（本地）

政策变更核实不再在 CI 内运行 LLM，也不依赖仓库 secret。核实与起草补丁全部在本地由 `policy-change-verify` skill 完成——详见 `site/docs/update-monitoring.md` 的"本地核实"一节与 skill 自带 `SKILL.md`。

感谢您的贡献！
