#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 site/docs/*.md 渲染为同名的 .html 页面（对外发布用）。

背景：此前 methodology / update-monitoring 同时维护 .md 与 .html 两份手工副本，
结果两边逐渐漂移（html 仍写着"第二层 AI 分析（未来功能）"，与已上线的实现相反）。
现在 .md 是唯一源，.html 由本脚本生成，CI 会校验并自动提交。

用法：
  .venv/bin/python scripts/gen_docs.py           # 重新生成全部文档页
  .venv/bin/python scripts/gen_docs.py --check   # 仅检查是否已最新（CI 用）

依赖：markdown（见 requirements.txt）
"""

import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(BASE_DIR, "site", "docs")

# 站点资源版本号：必须与 site/*.html 里的 ?v= 保持一致（tests 会校验）
ASSET_VERSION = "20260919-2"

# 文档页标题与副标题
DOC_META = {
    "methodology": {
        "title": "方法论",
        "subtitle": "AI 用户政策追踪器 · 数据来源与评定标准",
        "description": "AI 用户政策追踪器方法论：数据来源、风险等级评定标准、核实方法与数据字段说明。",
    },
    "update-monitoring": {
        "title": "政策更新监控",
        "subtitle": "AI 用户政策追踪器 · 自动化政策变更监控说明",
        "description": "AI 用户政策追踪器政策更新监控说明：变化检测、快照留档与 AI 辅助变更分析。",
    },
}

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'"
           "%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%9B%A1%EF%B8%8F%3C/text%3E%3C/svg%3E")

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{description}">
  <title>{title} - AI 用户政策追踪器</title>
  <link rel="icon" href="{favicon}">
  <link rel="stylesheet" href="../css/style.css?v={version}">
</head>
<body>
  <div class="header">
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
  </div>

  <div class="docs-body">
{body}
  </div>

  <div class="docs-body">
    <p><a href="../index.html">返回首页</a>{sibling}</p>
  </div>
</body>
</html>
"""


def render_markdown(text):
    """Markdown → HTML。缺 markdown 库时给出可操作的报错（不要让 CI 静默产出空页）。"""
    try:
        import markdown
    except ImportError:
        raise SystemExit("缺少依赖 markdown，请先安装：.venv/bin/pip install -r requirements.txt")
    return markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
    )


def build_html(name, md_text):
    meta = DOC_META.get(name, {"title": name, "subtitle": "AI 用户政策追踪器",
                               "description": "AI 用户政策追踪器文档"})
    body = render_markdown(md_text)
    siblings = [n for n in DOC_META if n != name]
    sibling = "".join(f' | <a href="{n}.html">{DOC_META[n]["title"]}</a>' for n in siblings)
    return TEMPLATE.format(
        title=meta["title"],
        subtitle=meta["subtitle"],
        description=meta["description"],
        favicon=FAVICON,
        version=ASSET_VERSION,
        body=body,
        sibling=sibling,
    )


def main():
    check_only = "--check" in sys.argv[1:]

    md_files = sorted(
        f for f in os.listdir(DOCS_DIR)
        if f.endswith(".md") and not f.startswith("_")
    )
    if not md_files:
        print("site/docs 下没有 .md 源文件")
        return 1

    stale = []
    for md_file in md_files:
        name = md_file[:-3]
        if name not in DOC_META:
            print(f"  [跳过] {md_file}（未在 DOC_META 登记，如需发布请先登记标题）")
            continue
        md_path = os.path.join(DOCS_DIR, md_file)
        html_path = os.path.join(DOCS_DIR, name + ".html")
        with open(md_path, encoding="utf-8") as f:
            new_html = build_html(name, f.read())

        old_html = None
        if os.path.exists(html_path):
            with open(html_path, encoding="utf-8") as f:
                old_html = f.read()

        if old_html == new_html:
            continue

        stale.append(name)
        if check_only:
            continue
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"已生成 {os.path.relpath(html_path, BASE_DIR)}")

    if check_only:
        if stale:
            print(f"文档页与 Markdown 不一致：{stale}，请运行 .venv/bin/python scripts/gen_docs.py")
            return 1
        print("文档页已是最新")
        return 0

    print(f"文档页生成完成（共 {len(md_files)} 个源文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
