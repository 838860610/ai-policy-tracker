#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
条款提取工具：从协议 HTML 中按标准同义词组提取关键条款上下文。

背景（WorkBuddy 教训）：仅检索"训练"会漏掉以"优化模型"表述的授权条款。
本工具固化了条款分析的标准同义词组与上下文窗口提取方法，
新增/核对条目时对协议页面（curl 或浏览器保存的 HTML）运行本工具。

用法：
  .venv/bin/python scripts/extract_clauses.py <协议.html> [附加关键词 ...]

输出：每个关键词的命中上下文（前后各约 160 字符）。
"""

import html
import os
import re
import sys

# 标准同义词组：分析协议时必须全部检索（新增同义词请同步更新此处与 CONTRIBUTING）
TRAINING_SYNONYMS = [
    "训练", "优化模型", "提升模型", "改进模型", "模型训练",
    "用于训练", "优化训练", "机器学习", "模型优化", "模型服务优化",
    "服务的优化", "优化服务", "改进服务", "提升服务",
]
OTHER_KEYWORDS = ["保存期限", "存储期限", "保留", "撤回", "退出", "关闭",
                  "知识产权", "归属", "企业", "个人版", "隐私模式"]

WINDOW_BEFORE = 160
WINDOW_AFTER = 160


def strip_html(raw):
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    extra = sys.argv[2:]
    raw = open(path, encoding="utf-8", errors="replace").read()
    text = strip_html(raw)
    print(f"[{os.path.basename(path)}] 纯文本长度: {len(text)}")
    keywords = TRAINING_SYNONYMS + OTHER_KEYWORDS + extra
    seen_pairs = set()
    for kw in dict.fromkeys(keywords):
        hits = []
        start = 0
        while len(hits) < 4:
            i = text.find(kw, start)
            if i == -1:
                break
            window = text[max(0, i - WINDOW_BEFORE): i + WINDOW_AFTER]
            key = window[:60]
            if key not in seen_pairs:
                seen_pairs.add(key)
                hits.append(window)
            start = i + len(kw)
        if hits:
            print(f"\n== {kw} ({len(hits)} 处) ==")
            for h in hits:
                print("  · …" + h.strip() + "…")


if __name__ == "__main__":
    main()
