#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成只读数据 API：site/generated/api/v1/{products.json, summary.json}（脚本产物，勿手改）。

定位：让第三方（评测文章、研究、工具）把本项目的数据当**数据源**引用，
而不是爬 HTML。零后端成本——产物由 CI 生成并提交，GitHub Pages 直接伺服。

兼容承诺（v1）：
  - schema_version 固定 "1.0"，只增字段不删字段、不改已有字段语义；
  - products[] 顺序与 site/data/products.json 展示顺序一致（不承诺稳定，按 id 取用）；
  - 字段语义见 skills/policy-change-verify/references/policy_schema.md 与
    对外文档 site/docs/methodology.md。

用法：
  .venv/bin/python scripts/gen_api.py            # 重新生成
  .venv/bin/python scripts/gen_api.py --check    # 仅检查是否已最新（CI 用）
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(BASE_DIR, "site")
INDEX_FILE = os.path.join(SITE_DIR, "data", "products.json")
POLICIES_DIR = os.path.join(SITE_DIR, "data", "policies")
API_DIR = os.path.join(SITE_DIR, "generated", "api", "v1")
PRODUCTS_FILE = os.path.join(API_DIR, "products.json")
SUMMARY_FILE = os.path.join(API_DIR, "summary.json")

SITE_URL = "https://838860610.github.io/ai-policy-tracker"
SCHEMA_VERSION = "1.0"

# 生成时间取数据内最新的 last_verified（而不是"现在"）：
# 输出必须确定性，否则 --check 永远不一致
DESCRIPTION = (
    "AI 用户政策追踪器只读 API v1：47 款 AI 产品的隐私政策 / 训练条款结构化数据。"
    "字段语义见 https://github.com/838860610/ai-policy-tracker（policy_schema.md / methodology.md）。"
    "v1 承诺向后兼容：只增字段、不删字段、不改已有字段语义。"
)
DISCLAIMER = "本数据仅供参考，不构成法律建议。各产品政策可能随时变更，请以官方最新政策为准。"


def load_policies():
    """按 products.json 的展示顺序载入全部政策数据；返回 [(pid, policy)]。"""
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    ids = index.get("products") or []
    policies = []
    for pid in ids:
        path = os.path.join(POLICIES_DIR, pid + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                policies.append((pid, json.load(f)))
        except (OSError, json.JSONDecodeError) as e:
            raise SystemExit(f"[gen_api] 无法读取 {path}：{e}")
    return policies


def latest_verified(policies):
    dates = [str(p.get("last_verified") or "")
             for _, p in policies if p.get("last_verified")]
    dates += [str((v or {}).get("last_verified") or "")
              for _, p in policies
              for v in ((p.get("versions") or {}).get(t) for t in ("toc", "tob"))]
    dates = [d for d in dates if d]
    return max(dates) if dates else ""


def build_products(policies):
    generated_at = latest_verified(policies)
    products = []
    for pid, policy in policies:
        entry = dict(policy)
        entry["id"] = pid
        entry["detail_url"] = f"{SITE_URL}/p/{pid}.html"
        products.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "description": DESCRIPTION,
        "disclaimer": DISCLAIMER,
        "count": len(products),
        "products": products,
    }


def build_summary(policies):
    by_region = {}
    risk_counter = {}
    training_statuses = {}
    for _, policy in policies:
        by_region[policy.get("region")] = by_region.get(policy.get("region"), 0) + 1
        versions = policy.get("versions") or {}
        for tier in ("toc", "tob"):
            v = versions.get(tier)
            if not isinstance(v, dict):
                continue
            risk = v.get("risk_level")
            risk_counter[risk] = risk_counter.get(risk, 0) + 1
            status = v.get("training_status")
            training_statuses[status] = training_statuses.get(status, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": latest_verified(policies),
        "description": DESCRIPTION,
        "disclaimer": DISCLAIMER,
        "total_products": len(policies),
        "by_region": by_region,
        "versions_by_risk_level": risk_counter,
        "versions_by_training_status": training_statuses,
        "endpoints": {
            "products": f"{SITE_URL}/generated/api/v1/products.json",
            "summary": f"{SITE_URL}/generated/api/v1/summary.json",
        },
    }


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    policies = load_policies()
    products_doc = build_products(policies)
    summary_doc = build_summary(policies)
    if "--check" in sys.argv:
        problems = []
        for path, doc in ((PRODUCTS_FILE, products_doc), (SUMMARY_FILE, summary_doc)):
            if not os.path.exists(path):
                problems.append(f"{path} 不存在，请重新生成")
                continue
            with open(path, encoding="utf-8") as f:
                current = json.load(f)
            if current != doc:
                problems.append(f"{path} 与当前数据不一致，请重新生成")
        if problems:
            print("[gen_api] " + "；".join(problems))
            return 1
        print("api/v1 已是最新")
        return 0
    os.makedirs(API_DIR, exist_ok=True)
    write_json(PRODUCTS_FILE, products_doc)
    write_json(SUMMARY_FILE, summary_doc)
    print(f"已生成 {PRODUCTS_FILE} 与 {SUMMARY_FILE}（{len(policies)} 个产品）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
