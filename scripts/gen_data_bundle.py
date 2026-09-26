#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 site/data/products.json（索引）与全部 site/data/policies/{id}.json 合并生成 site/generated/bundle.json。

首页优先加载 bundle（1 个请求替代 1+N 个，弱网/移动端首屏明显加快）；
bundle 不存在时前端自动回退为逐文件加载，因此本地改完数据忘记生成也不会出错，
只是首页暂时显示旧数据，等 CI 推送后自动补上。

生成时机：
  - CI：推送到 main 后自动重新生成并提交（.github/workflows/ci.yml）
  - 本地：更新数据后手动运行 .venv/bin/python scripts/gen_data_bundle.py（可选）
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_FILE = os.path.join(BASE_DIR, "site", "data", "products.json")
POLICIES_DIR = os.path.join(BASE_DIR, "site", "data", "policies")
BUNDLE_FILE = os.path.join(BASE_DIR, "site", "generated", "bundle.json")

# bundle 只服务首页（表格行 + 展开面板），详情页始终直接读 data/policies/{id}.json。
# 因此按白名单裁剪：key_clauses（长条款原文）等首页不渲染的字段不带进首屏，
# 实测可从 ~200KB 降到约 31KB。
# ⚠️ 首页若要新增展示字段，必须同步加到下面的白名单，否则会显示"—"。
BUNDLE_TOP_FIELDS = ("id", "name", "company", "region", "icon", "toc_note", "tob_note")
BUNDLE_VERSION_FIELDS = ("label", "used_for_training", "training_status", "opt_out",
                         "deidentified", "data_retention", "risk_level")
TRAINING_STATUSES = {
    "explicit_no", "default_off_opt_in", "default_on_opt_out",
    "explicit_yes", "unknown", "inferred",
}


def infer_training_status(version):
    explicit = version.get("training_status")
    if explicit in TRAINING_STATUSES:
        return explicit
    note = str(version.get("training_note") or "")
    state = str(version.get("default_state") or "")
    opt_out = str(version.get("opt_out") or "")
    if version.get("used_for_training") is False:
        if any(term in state for term in ("未明示", "沉默", "待核", "待核实", "未明确")) \
                or state.startswith("—") \
                or any(term in note for term in ("对训练沉默", "保持沉默", "零命中", "未明示模型训练")):
            return "unknown"
        if any(term in note for term in ("加入式", "opt-in", "主动加入", "主动选择")):
            return "default_off_opt_in"
        return "explicit_no"
    if version.get("used_for_training") is True:
        if any(term in note for term in ("按实质口径", "推断", "直接涵盖模型", "未明示模型训练")):
            return "inferred"
        if any(term in opt_out for term in ("设置开关", "联系", "邮件", "撤回", "退出")):
            return "default_on_opt_out"
        return "explicit_yes"
    return "unknown"


def slim_policy(policy):
    """只保留首页渲染所需的字段。"""
    out = {k: policy.get(k) for k in BUNDLE_TOP_FIELDS if k in policy}
    versions = {}
    source_versions = policy.get("versions") or {}
    if not isinstance(source_versions, dict):
        source_versions = {}
    for tier in ("toc", "tob"):
        version = source_versions.get(tier)
        if version:
            versions[tier] = {k: version.get(k) for k in BUNDLE_VERSION_FIELDS if k in version}
            versions[tier]["training_status"] = infer_training_status(version)
    out["versions"] = versions
    return out


def main():
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)

    policies = []
    for pid in index.get("products", []):
        path = os.path.join(POLICIES_DIR, pid + ".json")
        with open(path, encoding="utf-8") as f:
            policies.append(slim_policy(json.load(f)))

    bundle = {"meta": index.get("meta", {}), "policies": policies}
    with open(BUNDLE_FILE, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(BUNDLE_FILE) / 1024
    print(f"已生成 {BUNDLE_FILE}（{len(policies)} 个产品，{size_kb:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
