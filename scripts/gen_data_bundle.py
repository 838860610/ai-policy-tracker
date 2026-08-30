#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 data/products.json（索引）与全部 data/policies/{id}.json 合并生成 data/bundle.json。

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
INDEX_FILE = os.path.join(BASE_DIR, "data", "products.json")
POLICIES_DIR = os.path.join(BASE_DIR, "data", "policies")
BUNDLE_FILE = os.path.join(BASE_DIR, "data", "bundle.json")


def main():
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)

    policies = []
    for pid in index.get("products", []):
        path = os.path.join(POLICIES_DIR, pid + ".json")
        with open(path, encoding="utf-8") as f:
            policies.append(json.load(f))

    bundle = {"meta": index.get("meta", {}), "policies": policies}
    with open(BUNDLE_FILE, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(BUNDLE_FILE) / 1024
    print(f"已生成 {BUNDLE_FILE}（{len(policies)} 个产品，{size_kb:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
