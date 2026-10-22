#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为每个产品生成独立静态详情页 site/p/{id}.html，并同步生成 site/sitemap.xml。

背景：此前所有产品共用 detail.html?id=xxx，页面里的 OG/Twitter 元信息是同一套，
分享到社交平台时卡片标题永远相同。静态页把产品名、简介、canonical 写进 HTML，
无 JavaScript 时也能看到基本信息。

用法：
  .venv/bin/python scripts/gen_product_pages.py          # 重新生成全部产品页与 sitemap
  .venv/bin/python scripts/gen_product_pages.py --check  # 仅检查是否最新（CI 用）

模板：site/detail.html（唯一源）；不要手工编辑 site/p/*.html 与 site/sitemap.xml。
"""

import html as html_lib
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")
DATA_DIR = os.path.join(SITE_DIR, "data")
POLICIES_DIR = os.path.join(DATA_DIR, "policies")
OUT_DIR = os.path.join(SITE_DIR, "p")
TEMPLATE_FILE = os.path.join(SITE_DIR, "detail.html")
SITEMAP_FILE = os.path.join(SITE_DIR, "sitemap.xml")

SITE_URL = "https://838860610.github.io/ai-policy-tracker"
MAX_DESC = 120

# 文档页清单以 gen_docs.DOC_META 为准，避免 sitemap 再维护一份
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from gen_docs import DOC_META  # noqa: E402


def shorten(text, limit=MAX_DESC):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，、；;,. ") + "…"


def esc(text, quote=True):
    return html_lib.escape(str(text or ""), quote=quote)


def build_page(template, policy):
    pid = policy["id"]
    name = policy.get("name") or pid
    company = policy.get("company") or ""
    region = policy.get("region") or ""
    summary = policy.get("analysis_summary") or policy.get("description") or ""
    desc = shorten(summary) or f"{name}（{company}）的 AI 用户隐私政策与训练数据设置详情。"

    title = f"{name} 的隐私政策与训练数据设置 - AI 用户政策追踪器"
    og_title = f"{name} 隐私政策与训练数据设置——AI 用户政策追踪器"
    page_url = f"{SITE_URL}/p/{pid}.html"

    page = template
    viewport = '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    if "<base " in page or viewport not in page:
        raise SystemExit("detail.html 模板结构已变化：缺少 viewport 或已包含 <base>")
    page = page.replace(viewport, viewport + '  <base href="../">\n', 1)

    page = re.sub(
        r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="{esc(desc)}">',
        page, count=1)
    page = re.sub(
        r'<meta property="og:title" content="[^"]*">',
        f'<meta property="og:title" content="{esc(og_title)}">',
        page, count=1)
    page = re.sub(
        r'<meta property="og:description" content="[^"]*">',
        f'<meta property="og:description" content="{esc(desc)}">',
        page, count=1)
    page = re.sub(
        r'<meta property="og:url" content="[^"]*">',
        f'<meta property="og:url" content="{page_url}">',
        page, count=1)
    page = re.sub(
        r'<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'  <meta name="twitter:title" content="{esc(og_title)}">\n'
        f'  <meta name="twitter:description" content="{esc(desc)}">',
        page, count=1)
    page = re.sub(
        r'<link rel="canonical" href="[^"]*">',
        f'<link rel="canonical" href="{page_url}">',
        page, count=1)
    page = re.sub(
        r"<title>[^<]*</title>",
        f"<title>{esc(title, quote=False)}</title>",
        page, count=1)

    page = page.replace("<body>", f'<body data-product-id="{pid}">', 1)

    noscript = (
        "<noscript>\n"
        '    <div style="padding:24px;max-width:760px;margin:0 auto;color:var(--text-secondary);line-height:1.8">\n'
        f"      <p><strong>{esc(name, quote=False)}</strong>"
        f"（{esc(company, quote=False)} · {esc(region, quote=False)}）</p>\n"
        f"      <p>{esc(desc, quote=False)}</p>\n"
        "      <p>本页完整内容（训练开关、退出机制、数据留存、关键条款）需要启用 JavaScript 才能展示。</p>\n"
        "    </div>\n"
        "  </noscript>"
    )
    page = re.sub(r"<noscript>.*?</noscript>", noscript, page, count=1, flags=re.S)
    return page


def build_sitemap(ids):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{SITE_URL}/</loc></url>",
    ]
    lines += [f"  <url><loc>{SITE_URL}/p/{pid}.html</loc></url>" for pid in ids]
    lines += [f"  <url><loc>{SITE_URL}/docs/{name}.html</loc></url>" for name in DOC_META]
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def collect_expected():
    with open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8") as f:
        ids = json.load(f)["products"]
    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        template = f.read()

    expected = {}
    for pid in ids:
        path = os.path.join(POLICIES_DIR, pid + ".json")
        with open(path, encoding="utf-8") as f:
            policy = json.load(f)
        policy.setdefault("id", pid)
        expected[os.path.join(OUT_DIR, pid + ".html")] = build_page(template, policy)
    return ids, expected


def main():
    check_only = "--check" in sys.argv[1:]
    ids, expected = collect_expected()

    if not check_only:
        os.makedirs(OUT_DIR, exist_ok=True)

    stale = []
    for path, content in expected.items():
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = f.read()
        if old == content:
            continue
        stale.append(os.path.relpath(path, BASE_DIR))
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    expected_names = {os.path.basename(p) for p in expected}
    extras = []
    if os.path.isdir(OUT_DIR):
        extras = sorted(
            f"site/p/{n}" for n in os.listdir(OUT_DIR)
            if n.endswith(".html") and n not in expected_names
        )
        if not check_only:
            for name in extras:
                os.remove(os.path.join(BASE_DIR, name))

    sitemap = build_sitemap(ids)
    old_sitemap = None
    if os.path.exists(SITEMAP_FILE):
        with open(SITEMAP_FILE, encoding="utf-8") as f:
            old_sitemap = f.read()
    if old_sitemap != sitemap:
        stale.append("site/sitemap.xml")
        if not check_only:
            with open(SITEMAP_FILE, "w", encoding="utf-8") as f:
                f.write(sitemap)

    if check_only:
        if stale or extras:
            if stale:
                print(f"产品页/sitemap 不是最新：{stale[:5]}")
            if extras:
                print(f"存在多余的产品页：{extras}")
            print("请运行 .venv/bin/python scripts/gen_product_pages.py")
            return 1
        print(f"产品页与 sitemap 已是最新（{len(ids)} 个产品）")
        return 0

    print(f"已生成 {len(expected)} 个产品页与 site/sitemap.xml")
    if extras:
        print(f"已删除多余页面：{extras}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
