#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
README 汇总表生成脚本

从 data/ 下的实际数据生成 README.md 的对比汇总表（国内/海外两张表，按厂商排序）
与风险分布统计行，消除手写表格与数据的漂移。表格内容位于 README.md 的
<!-- TABLE:START --> 与 <!-- TABLE:END --> 标记之间。

用法：
  .venv/bin/python scripts/gen_readme_table.py          # 更新 README.md
  .venv/bin/python scripts/gen_readme_table.py --check  # 仅检查是否最新（CI 用）
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
README_FILE = os.path.join(BASE_DIR, "README.md")

START_MARK = "<!-- TABLE:START -->"
END_MARK = "<!-- TABLE:END -->"

RISK_EMOJI = {"green": "🟢 低", "yellow": "🟡 中", "red": "🔴 高"}
OPT_OUT_DISPLAY = {
    "设置开关": "✅ 支持",
    "邮件申请": "⚠️ 需邮件申请",
    "无需退出": "—",
}

# 厂商归一化：company 字段前缀 → 统一厂商名
VENDOR_RULES = [
    ("火山引擎", "字节跳动"),
    ("字节跳动", "字节跳动"),
    ("腾讯", "腾讯"),
    ("阿里云", "阿里巴巴"),
    ("阿里巴巴", "阿里巴巴"),
    ("百度", "百度"),
    ("深度求索", "DeepSeek（深度求索）"),
    ("OpenAI", "OpenAI"),
    ("Anthropic", "Anthropic"),
    ("Google", "Google"),
    ("智谱AI", "智谱AI"),
    ("月之暗面", "月之暗面（Moonshot AI）"),
    ("科大讯飞", "科大讯飞"),
    ("快手", "快手"),
    ("MiniMax", "MiniMax"),
    ("阶跃星辰", "阶跃星辰"),
    ("昆仑万维", "昆仑万维"),
    ("商汤", "商汤科技"),
    ("360", "360"),
    ("华为", "华为"),
    ("百川", "百川智能"),
    ("零一万物", "零一万物"),
]

# 厂商排序键（拼音），同厂商内按条目 id 稳定排序
VENDOR_SORT = {
    "阿里巴巴": "alibaba",
    "百川智能": "baichuan",
    "百度": "baidu",
    "华为": "huawei",
    "阶跃星辰": "jieyue",
    "科大讯飞": "kedaxunfei",
    "快手": "kuaishou",
    "昆仑万维": "kunlun",
    "零一万物": "lingyi",
    "MiniMax": "minimax",
    "商汤科技": "shangtang",
    "DeepSeek（深度求索）": "shendu",
    "腾讯": "tengxun",
    "月之暗面（Moonshot AI）": "yue",
    "智谱AI": "zhipu",
    "Anthropic": "anthropic",
    "Google": "google",
    "OpenAI": "openai",
    "360": "360",
}


def vendor_of(company):
    for prefix, vendor in VENDOR_RULES:
        if company.startswith(prefix):
            return vendor
    return company


def sort_key(product, vendor):
    return (VENDOR_SORT.get(vendor, vendor), product["id"])


def load_products():
    with open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8") as f:
        index = json.load(f)
    products = []
    for pid in index["products"]:
        with open(os.path.join(DATA_DIR, "policies", pid + ".json"), encoding="utf-8") as f:
            products.append(json.load(f))
    return products


def training_cell(value):
    return "✅ 是" if value is True else "❌ 否" if value is False else "—"


def opt_out_cell(value):
    return OPT_OUT_DISPLAY.get(value, value if value else "—")


def build_stats(products):
    """风险分布统计行，口径与表格"风险等级"列一致（个人版条款，无 toc 块计未评定）。"""
    counts = {"red": 0, "yellow": 0, "green": 0}
    unrated = 0
    for p in products:
        toc = p.get("versions", {}).get("toc") or {}
        level = toc.get("risk_level")
        if level in counts:
            counts[level] += 1
        else:
            unrated += 1
    return (
        f"**风险分布**（按个人版条款，共 {len(products)} 款）："
        f"🔴 高风险 {counts['red']} 款 · 🟡 中风险 {counts['yellow']} 款 · "
        f"🟢 低风险 {counts['green']} 款 · 未评定 {unrated} 款"
    )


def build_table(products):
    lines = [
        "| 产品 | 厂商 | 个人版训练 | 退出机制 | 企业版训练 | 风险等级 |",
        "|------|------|-----------|---------|-----------|---------|",
    ]
    for p in products:
        toc = p.get("versions", {}).get("toc") or {}
        tob = p.get("versions", {}).get("tob") or {}
        risk = RISK_EMOJI.get(toc.get("risk_level"), "—")
        lines.append(
            "| {name} | {vendor} | {toc_train} | {opt_out} | {tob_train} | {risk} |".format(
                name=p.get("name", p["id"]),
                vendor=p.get("company", "—"),
                toc_train=training_cell(toc.get("used_for_training")),
                opt_out=opt_out_cell(toc.get("opt_out")),
                tob_train=training_cell(tob.get("used_for_training")) if tob else "—",
                risk=risk,
            )
        )
    return "\n".join(lines)


def main():
    check_only = "--check" in sys.argv[1:]
    products = load_products()

    domestic, overseas = [], []
    for p in products:
        vendor = vendor_of(p.get("company", ""))
        bucket = overseas if p.get("region") not in (None, "中国") else domestic
        bucket.append((vendor, p))
    domestic.sort(key=lambda x: sort_key(x[1], x[0]))
    overseas.sort(key=lambda x: sort_key(x[1], x[0]))

    parts = [
        build_stats(products),
        f"国内平台（{len(domestic)} 款产品，按厂商拼音排序）：\n\n"
        + build_table([p for _, p in domestic]),
    ]
    if overseas:
        parts.append(
            f"海外平台（{len(overseas)} 款产品，按厂商排序）：\n\n"
            + build_table([p for _, p in overseas])
        )
    else:
        parts.append("海外平台：暂无收录条目（见优化清单 B3）")
    new_block = START_MARK + "\n" + "\n\n".join(parts) + "\n" + END_MARK

    with open(README_FILE, encoding="utf-8") as f:
        readme = f.read()

    if START_MARK not in readme or END_MARK not in readme:
        print(f"错误：README.md 缺少 {START_MARK} / {END_MARK} 标记，无法定位表格")
        return 1

    start = readme.index(START_MARK)
    end = readme.index(END_MARK) + len(END_MARK)
    current_block = readme[start:end]

    if current_block == new_block:
        print("README 汇总表已是最新")
        return 0

    if check_only:
        print("README 汇总表与数据不一致，请运行 .venv/bin/python scripts/gen_readme_table.py 更新")
        return 1

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(readme[:start] + new_block + readme[end:])
    print(f"已更新 README.md 汇总表（国内 {len(domestic)} + 海外 {len(overseas)} = {len(products)} 个产品）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
