#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Atom 订阅源 site/feed.xml（脚本产物，不要手工编辑）。

数据源全部是现成文件，不抓取任何远端：
  - site/data/policies/*.json 的 timeline：人工核实过的实质变更（叙事主线）；
  - site/generated/pending_verification.json：监控检测到、尚未核实的变更（含 diff_preview）。

两者按时间倒序合并，取前 MAX_ENTRIES 条。输出必须确定性（同一输入同一输出），
CI 用 --check 校验入库版本是否最新。

用法：
  .venv/bin/python scripts/gen_feed.py            # 重新生成
  .venv/bin/python scripts/gen_feed.py --check    # 仅检查是否已最新（CI 用）
"""

import datetime
import glob
import json
import os
import re
import sys
import xml.sax.saxutils as saxutils
from urllib.parse import quote

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(BASE_DIR, "site")
POLICIES_DIR = os.path.join(SITE_DIR, "data", "policies")
PENDING_FILE = os.path.join(SITE_DIR, "generated", "pending_verification.json")
FEED_FILE = os.path.join(SITE_DIR, "feed.xml")

SITE_URL = "https://838860610.github.io/ai-policy-tracker"
FEED_ID = SITE_URL + "/"
FEED_TITLE = "AI 用户政策追踪器 · 政策变更动态"
FEED_SUBTITLE = "47 款 AI 产品隐私政策 / 训练条款的变更与核实记录"
MAX_ENTRIES = 60

# 时间戳口径与 check_updates.py / validate_data.py 一致：按北京时间
PROJECT_TZ = datetime.timezone(datetime.timedelta(hours=8))
# 无任何条目时的 feed 级 updated 占位（确定性输出，不能用"当前时间"）
EPOCH = "1970-01-01T00:00:00+08:00"


def parse_when(value):
    """把数据里的各种时间写法统一成带时区的 datetime。

    支持 "2026-11-05"、"2025-02"（补 -01）、ISO datetime；
    naive 字符串按北京时间处理（历史数据是 runner UTC / 本地 UTC+8 混写的，
    这里统一按项目时区展示，误差 ≤8h 且方向固定）。
    解析失败返回 None，该条目退化为不参与排序但仍保留（排最后）。
    """
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        text += "-01"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PROJECT_TZ)
    return dt


def rfc3339(dt):
    return dt.isoformat()


def esc(text):
    return saxutils.escape(str(text), {'"': "&quot;"})


def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items")
    return [it for it in items.values() if isinstance(it, dict)] if isinstance(items, dict) else []


def timeline_entries():
    entries = []
    for path in sorted(glob.glob(os.path.join(POLICIES_DIR, "*.json"))):
        pid = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                policy = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        name = policy.get("name") or pid
        timeline = policy.get("timeline") or []
        for idx, event in enumerate(timeline):
            if not isinstance(event, dict) or not event.get("event"):
                continue
            event_text = str(event["event"]).strip()
            date_text = str(event.get("date") or "").strip()
            updated = parse_when(date_text)
            # 截断到句号/60 字，完整叙述放在 content 里
            short = re.split(r"[。；]", event_text, maxsplit=1)[0]
            if len(short) > 60:
                short = short[:60] + "…"
            title = f"{name}：{short}"
            content = (
                f"<p><strong>{esc(name)}</strong> · {esc(date_text)}</p>"
                f"<p>{esc(event_text)}</p>"
                f'<p><a href="{esc(SITE_URL)}/p/{esc(pid)}.html">{esc(name)} 详情页</a> · 来源：人工核实（timeline）</p>'
            )
            entries.append({
                "id": f"{SITE_URL}/timeline/{pid}/{date_text}/{idx}",
                "title": title,
                "updated": updated,
                "link": f"{SITE_URL}/p/{pid}.html",
                "content": content,
            })
    return entries


def pending_entries():
    entries = []
    for item in load_pending():
        pid = str(item.get("pid") or "")
        if not pid:
            continue
        name = item.get("name") or pid
        label = item.get("label") or item.get("key") or ""
        url = item.get("url") or ""
        diff = item.get("diff_preview")
        first_seen = str(item.get("first_seen") or item.get("last_seen") or "")
        updated = parse_when(item.get("last_seen") or item.get("first_seen"))
        # entry id 绑定 first_seen：同一未核实变更不随每轮 last_seen 刷新而重复推送，
        # 核实后条目出队；同目标再次变更会生成新的 first_seen → 新条目。
        # id 里的中文/冒号做 percent-encoding，保证是合法 IRI
        entry_id = (f"{SITE_URL}/pending/{quote(pid + ':' + str(item.get('key') or ''))}"
                    f"/{quote(first_seen)}")
        title = f"待核实：{name}（{label}）检测到政策页面变化"
        content_parts = [
            f"<p><strong>{esc(name)}</strong>（{esc(label)}）的监控目标检测到正文变化，尚未人工核实。</p>",
            url and f'<p><a href="{esc(url)}">{esc(url)}</a></p>',
        ]
        if diff:
            content_parts.append(f"<pre>{esc(diff)}</pre>")
        content_parts.append(
            f'<p><a href="{esc(SITE_URL)}/p/{esc(pid)}.html">{esc(name)} 详情页</a> · 来源：自动监控（待核实队列）</p>'
        )
        entries.append({
            "id": entry_id,
            "title": title,
            "updated": updated,
            "link": f"{SITE_URL}/p/{pid}.html",
            "content": "".join(p for p in content_parts if p),
        })
    return entries


def build_feed_xml():
    entries = timeline_entries() + pending_entries()
    # 升序排（同刻条目按 id 升序保证确定性），尾部切片取最新的 MAX_ENTRIES 条再反转
    entries.sort(key=lambda e: (e["updated"] or datetime.datetime.min.replace(tzinfo=PROJECT_TZ), e["id"]),
                 reverse=False)
    newest = max((e["updated"] for e in entries if e["updated"]), default=None)
    feed_updated = rfc3339(newest) if newest else EPOCH

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <id>{esc(FEED_ID)}</id>",
        f"  <title>{esc(FEED_TITLE)}</title>",
        f"  <subtitle>{esc(FEED_SUBTITLE)}</subtitle>",
        f"  <updated>{feed_updated}</updated>",
        f'  <link rel="self" href="{esc(SITE_URL)}/feed.xml"/>',
        f'  <link rel="alternate" href="{esc(SITE_URL)}/"/>',
        "  <generator>ai-policy-tracker gen_feed.py</generator>",
    ]
    for e in entries[-MAX_ENTRIES:][::-1]:
        updated = rfc3339(e["updated"]) if e["updated"] else feed_updated
        lines += [
            "  <entry>",
            f"    <id>{esc(e['id'])}</id>",
            f"    <title>{esc(e['title'])}</title>",
            f"    <updated>{updated}</updated>",
            f'    <link rel="alternate" href="{esc(e["link"])}"/>',
            f'    <content type="html">{esc(e["content"])}</content>',
            "  </entry>",
        ]
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def main():
    xml = build_feed_xml()
    if "--check" in sys.argv:
        if not os.path.exists(FEED_FILE):
            print(f"[gen_feed] {FEED_FILE} 不存在，请重新生成")
            return 1
        with open(FEED_FILE, encoding="utf-8") as f:
            current = f.read()
        if current == xml:
            print("feed.xml 已是最新")
            return 0
        print("[gen_feed] feed.xml 与当前数据不一致，请重新生成：.venv/bin/python scripts/gen_feed.py")
        return 1
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"已生成 {FEED_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
