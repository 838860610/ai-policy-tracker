#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据校验脚本

检查 data/products.json（ID 索引）与 data/policies/*.json 的结构完整性，
在提交 PR 前运行，防止字段缺失、ID 不一致等问题进入主分支。

用法：
  python3 scripts/validate_data.py

退出码：0 = 通过（可以有警告），1 = 存在错误
"""

import json
import os
import re
import sys
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
INDEX_FILE = os.path.join(DATA_DIR, "products.json")
POLICIES_DIR = os.path.join(DATA_DIR, "policies")

ID_PATTERN = re.compile(r"^[a-z0-9-]+$")

# 训练结论佐证的宽匹配词（key_clauses 引文含任一即视为有佐证）
TRAINING_SYNONYMS = ["训练", "优化", "改进", "提升", "机器学习", "train", "training", "improve"]
# 来源标注：key_clauses 每条应以（来源）结尾
SOURCE_ANNOTATION = re.compile(r"）\s*。?\s*$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

VERSION_REQUIRED = [
    "used_for_training", "default_state", "opt_out", "opt_out_method",
    "deidentified", "data_retention", "copyright", "risk_level", "key_clauses",
]
VERSION_OPTIONAL = ["training_note", "other_uses", "policy_link", "last_verified", "label"]
TOP_REQUIRED = [
    "id", "name", "company", "region", "description", "policy_url",
    "last_verified", "versions", "analysis_summary", "key_findings", "recommendations",
]
RISK_LEVELS = {"green", "yellow", "red"}

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def check_version(where, v):
    for key in VERSION_REQUIRED:
        if key not in v:
            err(f"{where}: 缺少必填字段 {key}")
    for key in VERSION_OPTIONAL:
        if key not in v:
            warn(f"{where}: 缺少可选字段 {key}")
    if "used_for_training" in v and not isinstance(v["used_for_training"], bool):
        err(f"{where}: used_for_training 必须是布尔值，当前为 {v['used_for_training']!r}")
    if "deidentified" in v and not isinstance(v["deidentified"], bool):
        err(f"{where}: deidentified 必须是布尔值，当前为 {v['deidentified']!r}")
    if "risk_level" in v and v["risk_level"] not in RISK_LEVELS:
        err(f"{where}: risk_level 必须是 {sorted(RISK_LEVELS)} 之一，当前为 {v['risk_level']!r}")
    clauses = v.get("key_clauses")
    if clauses is not None:
        if not isinstance(clauses, list) or not clauses:
            err(f"{where}: key_clauses 必须是非空数组")
        else:
            for i, c in enumerate(clauses):
                if not isinstance(c, str) or not c.strip():
                    err(f"{where}: key_clauses[{i}] 不能为空")
                elif c.strip() in ("待核实", "待核实具体条款。", "待核实具体条款，需进一步查阅。"):
                    warn(f"{where}: key_clauses[{i}] 仍是占位文字，需要补充真实条款摘录")
                elif not SOURCE_ANNOTATION.search(c.strip()):
                    warn(f"{where}: key_clauses[{i}] 缺少来源标注（建议以（来源条款号/文档名）结尾）")
    if v.get("data_retention") == "待核实":
        warn(f"{where}: data_retention 仍是占位文字")
    # 风险等级推导（A1-d）：标为绿的版本必须满足方法论四项绿色标准
    def retention_clear_30(ret):
        if not ret:
            return False
        if re.search(r"未明确|待核实|待核|未载明|未说明", ret):
            return False
        return bool(re.search(r"30\s*天|≤\s*30|30日", ret))

    if v.get("risk_level") == "green":
        reasons = []
        if v.get("used_for_training") is not False:
            reasons.append("训练判定非'默认不训练'")
        if v.get("deidentified") is not True:
            reasons.append("未载明去标识化")
        if not retention_clear_30(v.get("data_retention", "")):
            reasons.append("留存期限不明确或超30天")
        cp = v.get("copyright", "")
        if "用户" not in cp or "待核实" in cp:
            reasons.append("版权归属未明确归用户")
        if reasons:
            warn(f"{where}: 标为绿但未满足全部绿色标准：{'；'.join(reasons)}（方法论：绿需四项全部满足；如判定有据可忽略本提示）")

    tn = (v.get("training_note") or "")
    silent_note = any(m in tn for m in ("沉默", "零命中", "未明示"))
    xref = "适用" in tn and "协议" in tn or "详见" in tn
    if not silent_note and not xref and "训练" in tn and isinstance(clauses, list) and clauses:
        joined = " ".join(c for c in clauses if isinstance(c, str))
        if not any(syn in joined for syn in TRAINING_SYNONYMS):
            warn(f"{where}: training_note 声称训练，但 key_clauses 无训练相关原文佐证（标准同义词组：{'/'.join(TRAINING_SYNONYMS)}）")

    # Qoder 教训：条款含训练/优化授权表述却标 used_for_training=false，
    # 必须有加入式（opt-in）或明示不训练的依据，否则判定矛盾
    if v.get("used_for_training") is False and isinstance(clauses, list) and clauses:
        joined = " ".join(c for c in clauses if isinstance(c, str))
        if any(s in joined for s in ("训练", "优化", "改进", "提升", "机器学习")):
            optin = any(m in joined for m in ("加入", "除非", "自愿"))
            negative = any(m in joined for m in ("不会", "不用于", "不使用"))
            silent = any(m in tn for m in ("沉默", "零命中", "未明示"))
            if not (optin or negative or silent):
                warn(f"{where}: key_clauses 含训练/优化授权表述但 used_for_training=false——"
                     f"若为加入式请补充'加入/除非'依据，若为明示不训练请补充否定条款，否则应改为 true")


def validate_policy(pid, path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("id") != pid:
        err(f"{os.path.basename(path)}: 文件内 id={data.get('id')!r} 与文件名 {pid!r} 不一致")
    for key in TOP_REQUIRED:
        if key not in data:
            err(f"{pid}: 缺少必填字段 {key}")
    for key in ("icon", "product_url"):
        if key not in data:
            warn(f"{pid}: 缺少可选字段 {key}")

    lv = data.get("last_verified")
    if lv is not None and not (isinstance(lv, str) and DATE_PATTERN.match(lv)):
        err(f"{pid}: last_verified 格式应为 YYYY-MM-DD，当前为 {lv!r}")
    elif isinstance(lv, str) and DATE_PATTERN.match(lv):
        try:
            d = datetime.date.fromisoformat(lv)
            if d < datetime.date(2025, 1, 1):
                warn(f"{pid}: last_verified={lv} 距今较久，建议重新核实")
        except ValueError:
            err(f"{pid}: last_verified={lv!r} 不是有效日期")

    url = data.get("policy_url")
    if url is not None and not str(url).startswith(("http://", "https://")):
        err(f"{pid}: policy_url 应以 http(s):// 开头，当前为 {url!r}")

    versions = data.get("versions")
    if not isinstance(versions, dict):
        versions = {}
    if "toc" in versions:
        check_version(f"{pid}.versions.toc", versions["toc"])
    elif data.get("toc_note"):
        pass  # 有书面说明的纯开发者产品（无消费端条款）
    else:
        warn(f"{pid}: 没有 toc 版本数据；如为纯开发者产品，请添加 toc_note 说明原因")
    if isinstance(versions, dict):
        if "tob" in versions:
            check_version(f"{pid}.versions.tob", versions["tob"])
        elif data.get("tob_note"):
            pass  # 有书面说明的无 ToB 产品（如未发布企业版），视为合规
        else:
            warn(f"{pid}: 没有 tob 版本数据（详情页会自动隐藏企业版标签）；如确无企业版，请在数据中添加 tob_note 说明原因")

    timeline = data.get("timeline")
    if timeline is not None:
        if not isinstance(timeline, list):
            err(f"{pid}: timeline 必须是数组")
        else:
            for i, item in enumerate(timeline):
                if not isinstance(item, dict) or "date" not in item or "event" not in item:
                    err(f"{pid}: timeline[{i}] 必须包含 date 和 event 字段")

    for key in ("key_findings", "recommendations"):
        v = data.get(key)
        if v is not None and (not isinstance(v, list) or not v):
            err(f"{pid}: {key} 必须是非空数组")


def main():
    if not os.path.exists(INDEX_FILE):
        err(f"索引文件不存在：{INDEX_FILE}")
        report()
        return 1

    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)

    ids = index.get("products")
    if not isinstance(ids, list) or not ids:
        err("products.json 的 products 必须是非空 ID 数组")
        report()
        return 1

    if len(ids) != len(set(ids)):
        err("products.json 的 products 存在重复 ID")

    policy_files = {f[:-5] for f in os.listdir(POLICIES_DIR) if f.endswith(".json")}
    for pid in ids:
        if not isinstance(pid, str) or not ID_PATTERN.match(pid):
            err(f"索引中的 ID {pid!r} 格式非法（只允许小写字母、数字、连字符）")
            continue
        path = os.path.join(POLICIES_DIR, pid + ".json")
        if not os.path.exists(path):
            err(f"索引中的产品 {pid} 缺少数据文件 policies/{pid}.json")
            continue
        try:
            validate_policy(pid, path)
        except json.JSONDecodeError as e:
            err(f"policies/{pid}.json 不是合法 JSON：{e}")

    orphan = policy_files - set(ids)
    if orphan:
        err(f"以下 policy 文件未被索引收录（请加入 products.json 或删除）：{sorted(orphan)}")

    report()
    return 1 if errors else 0


def report():
    for w in warnings:
        print(f"  [警告] {w}")
    for e in errors:
        print(f"  [错误] {e}")
    print()
    if errors:
        print(f"校验失败：{len(errors)} 个错误，{len(warnings)} 个警告")
    else:
        print(f"校验通过：0 个错误，{len(warnings)} 个警告")


if __name__ == "__main__":
    sys.exit(main())
