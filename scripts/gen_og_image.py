#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成社交分享卡片 assets/og-card.png（1200×630，Open Graph / Twitter Card 用）。

统计数字从 data/policies/*.json 实时计算（按个人版风险），与 README 汇总表同口径，
重新生成即可保持同步：.venv/bin/python scripts/gen_og_image.py

依赖 Pillow（维护用一次性依赖，未列入 requirements.txt 以保持运行依赖精简）：
  .venv/bin/pip install pillow
"""

import glob
import json
import os

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICIES_DIR = os.path.join(BASE_DIR, "data", "policies")
OUTPUT = os.path.join(BASE_DIR, "assets", "og-card.png")

W, H = 1200, 630
BG = (245, 245, 245)        # 与站点 --bg 一致
TEXT = (31, 31, 31)         # --text
TEXT_2 = (102, 102, 102)    # --text-secondary
TEXT_3 = (153, 153, 153)    # --text-tertiary
PRIMARY = (22, 119, 255)    # --primary
RED = (255, 77, 79)
YELLOW = (250, 173, 20)
GREEN = (82, 196, 26)

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size, bold=False):
    # TTC 内含多字重：1=W6（粗），0=W3（常规）；加载失败退化为常规字重 + 描边加粗
    try:
        return ImageFont.truetype(FONT_PATH, size, index=1 if bold else 0)
    except OSError:
        return ImageFont.truetype(FONT_PATH, size)


def load_stats():
    counts = {"red": 0, "yellow": 0, "green": 0, "none": 0}
    total = 0
    for path in glob.glob(os.path.join(POLICIES_DIR, "*.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        total += 1
        toc = (data.get("versions") or {}).get("toc") or {}
        counts[toc.get("risk_level") or "none"] += 1
    return total, counts


def main():
    total, counts = load_stats()

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 顶部品牌色条
    draw.rectangle([0, 0, W, 10], fill=PRIMARY)

    # 品牌小标 + 主标题 + 副标题
    draw.text((80, 78), "AI POLICY TRACKER", fill=PRIMARY, font=font(30, bold=True))
    draw.text((80, 128), "AI 用户政策追踪器", fill=TEXT, font=font(78, bold=True))
    draw.text((80, 242), "主流 AI 产品是否使用你的数据进行模型训练", fill=TEXT_2, font=font(40))

    # 风险分布胶囊（数字与 README 汇总表同源；字号动态收缩保证整行不超出画布）
    chips = [
        (RED,   (255, 242, 240), f"高风险 {counts['red']} 款"),
        (YELLOW, (255, 251, 230), f"中风险 {counts['yellow']} 款"),
        (GREEN, (246, 255, 237), f"低风险 {counts['green']} 款"),
        (TEXT_3, (255, 255, 255), f"未评定 {counts['none']} 款"),
    ]
    chip_font_size = 34
    while chip_font_size >= 20:
        f_chip = font(chip_font_size)
        widths = [draw.textlength(label, font=f_chip) + 86 for _, _, label in chips]
        if 80 + sum(widths) + 24 * (len(chips) - 1) <= W - 80:
            break
        chip_font_size -= 2
    x = 80
    for (color, bg, label), cw in zip(chips, widths):
        cy0, cy1 = 340, 340 + chip_font_size + 38
        dot_r = chip_font_size // 3
        draw.rounded_rectangle([x, cy0, x + cw, cy1], radius=(cy1 - cy0) // 2, fill=bg,
                               outline=tuple(min(255, c + 40) for c in color), width=2)
        dot_cy = (cy0 + cy1) // 2
        draw.ellipse([x + 28, dot_cy - dot_r, x + 28 + 2 * dot_r, dot_cy + dot_r], fill=color)
        draw.text((x + 68, cy0 + 19), label, fill=TEXT, font=f_chip)
        x += cw + 24

    # 覆盖范围与底部链接
    draw.text((80, 462), f"覆盖 {total} 款产品 · 个人版 / 企业版条款 · 政策变更自动监控",
              fill=TEXT_2, font=font(32))
    draw.text((80, 548), "github.com/838860610/ai-policy-tracker", fill=TEXT_3, font=font(28))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    img.save(OUTPUT, "PNG", optimize=True)
    print(f"已生成 {OUTPUT}（高风险 {counts['red']} / 中风险 {counts['yellow']} / "
          f"低风险 {counts['green']} / 未评定 {counts['none']}，共 {total} 款）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
