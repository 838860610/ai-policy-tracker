# 贡献指南

感谢您对 AI 用户政策追踪器项目的关注！欢迎贡献政策更新、新增产品和改进建议。

## 数据模型（重要）

- **`data/policies/{id}.json` 是每个产品唯一的数据源**，包含该产品的名称、公司、版本政策、时间线等全部字段
- `data/products.json` 只维护产品 ID 的排列顺序（定义首页/README 表格的展示顺序）与项目元信息，**不存储产品数据**
- 修改产品数据只需要改 `data/policies/{id}.json` 一个文件，不存在需要同步的两份数据

## 如何贡献政策更新

### 1. 发现政策变更

当您发现某产品的隐私政策发生变更时，请按以下步骤更新数据：

1. 访问该产品的官方隐私政策页面
2. 阅读新的政策内容，提取关键信息
3. 更新对应的 `data/policies/{id}.json` 文件
4. 更新文件内 `last_verified` 字段为当前核实日期
5. 在 `timeline` 中添加变更记录

### 2. 新增产品

如需添加新的 AI 产品：

1. 在 `data/policies/` 下创建 `{id}.json` 详细政策文件（id 用小写英文+连字符，如 `github-copilot.json`）
2. 在 `data/products.json` 的 `products` 数组中加入该 ID（决定展示顺序）
3. 确保所有必填字段都已填写
4. 运行 `python3 scripts/gen_readme_table.py` 重新生成 README 汇总表

### 3. 提交 PR

```bash
# 创建分支
git checkout -b update/xxx-policy

# 修改文件
# ... 编辑数据文件 ...

# 提交前运行校验（首次请先创建虚拟环境，见下方"运行验证"）
.venv/bin/python scripts/validate_data.py
.venv/bin/python scripts/gen_readme_table.py --check

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
4. **校验通过**：`scripts/validate_data.py` 0 错误、`gen_readme_table.py --check` 通过
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

# 启动本地服务预览（自动打开浏览器）
./start.sh
# 或手动：python3 -m http.server 8080，访问 http://localhost:8080 检查页面
```

感谢您的贡献！
