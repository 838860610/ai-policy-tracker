#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检测到政策变更时推送 webhook 通知（飞书 / 钉钉 / Telegram / 通用 JSON）。

由 monitor.yml 在监控轮结束后调用：
  python scripts/notify_webhook.py

环境变量：
  WEBHOOK_URL       通知端点；未设置时静默退出（未配置通知不是错误）。
                    WEBHOOK_TYPE=telegram 时填完整 sendMessage API（含 bot token）
  WEBHOOK_TYPE      feishu（默认）/ dingtalk / telegram / generic
  TELEGRAM_CHAT_ID  WEBHOOK_TYPE=telegram 时必填

消息内容从 update_status.json 汇总本轮 changed 目标，并从
pending_verification.json 取各目标的 diff 片段首几行。只做一次性 POST，
不重试（下一轮监控会再触发）；发送失败以退出码 1 结束，workflow 里
continue-on-error 保证通知故障不掩盖监控结果本身。
"""

import json
import os
import sys

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE = os.path.join(BASE_DIR, "site", "generated", "update_status.json")
PENDING_FILE = os.path.join(BASE_DIR, "site", "generated", "pending_verification.json")

SITE_URL = "https://838860610.github.io/ai-policy-tracker"
TARGET_LABELS = {"main": "主监控页", "toc": "个人版", "tob": "企业版"}
MAX_TARGETS_IN_MESSAGE = 10
DIFF_LINES_IN_MESSAGE = 6
MESSAGE_MAX_CHARS = 3500  # Telegram 单条上限 4096，留余量


def collect_changed(status_data):
    """从 update_status.json 提取 changed 目标：[{pid, key, name, label, url}]。
    key 保留原始值（main/toc/tob/source_x），用于回查队列里的 diff_preview。"""
    changed = []
    for pid, info in (status_data.get("products") or {}).items():
        if not isinstance(info, dict):
            continue
        for key, target in (info.get("targets") or {}).items():
            if isinstance(target, dict) and target.get("status") == "changed":
                changed.append({
                    "pid": pid,
                    "key": key,
                    "name": info.get("name") or pid,
                    "label": TARGET_LABELS.get(key, key),
                    "url": target.get("url") or "",
                })
    return changed


def load_pending_state():
    """读待核实队列，返回 ({pid:key → diff_preview}, 队列总条数)；
    队列缺失/损坏时为 ({}, 0)。"""
    if not os.path.exists(PENDING_FILE):
        return {}, 0
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}, 0
    items = data.get("items")
    if not isinstance(items, dict):
        return {}, 0
    previews = {}
    total = 0
    for pk, item in items.items():
        if not isinstance(item, dict):
            continue
        total += 1
        if item.get("diff_preview"):
            previews[pk] = item["diff_preview"]
    return previews, total


def build_text(changed, diff_previews, queue_total):
    """组装纯文本通知。各平台的格式适配在 build_payload，这里只管内容。"""
    lines = [f"⚠️ AI 政策追踪器：本轮检测到 {len(changed)} 项政策可能已更新", ""]
    for item in changed[:MAX_TARGETS_IN_MESSAGE]:
        lines.append(f"· {item['name']}（{item['label']}）")
        if item["url"]:
            lines.append(f"  {item['url']}")
        diff = diff_previews.get(f"{item['pid']}:{item['key']}")
        if diff:
            head = "\n".join("  " + ln for ln in diff.splitlines()[:DIFF_LINES_IN_MESSAGE])
            lines.append(head)
    if len(changed) > MAX_TARGETS_IN_MESSAGE:
        lines.append(f"…另有 {len(changed) - MAX_TARGETS_IN_MESSAGE} 项略")
    lines.append("")
    lines.append(f"待核实队列 {queue_total} 项 · 详情 {SITE_URL}/")
    text = "\n".join(lines)
    if len(text) > MESSAGE_MAX_CHARS:
        text = text[:MESSAGE_MAX_CHARS] + "\n…（通知过长已截断）"
    return text


def build_payload(text, webhook_type, chat_id=None):
    """平台 payload 适配。四种格式的官方文档字段：飞书 msg_type/content，
    钉钉 msgtype/text，Telegram chat_id/text，generic 只约定 text 字段。"""
    if webhook_type == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if webhook_type == "dingtalk":
        return {"msgtype": "text", "text": {"content": text}}
    if webhook_type == "telegram":
        return {"chat_id": chat_id, "text": text}
    return {"text": text}


def platform_ok(body):
    """识别各平台的业务层失败（HTTP 200 但机器人拒绝/限流）。"""
    if not isinstance(body, dict):
        return True  # 非 JSON 响应：交给 HTTP 状态码判断
    if body.get("ok") is False:          # telegram
        return False
    for key in ("errcode", "code", "StatusCode"):  # dingtalk / 飞书新旧格式
        value = body.get(key)
        if value not in (None, 0, "0"):
            return False
    return True


def main():
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("未配置 WEBHOOK_URL，跳过通知（配置 Secrets 后自动生效）")
        return 0
    webhook_type = os.environ.get("WEBHOOK_TYPE", "feishu").strip().lower() or "feishu"

    if not os.path.exists(STATUS_FILE):
        print("update_status.json 不存在，跳过通知")
        return 0
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            status_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"读取 update_status.json 失败，跳过通知：{e}")
        return 0

    changed = collect_changed(status_data)
    if not changed:
        print("本轮无 changed 目标，跳过通知")
        return 0

    diff_previews, queue_total = load_pending_state()
    text = build_text(changed, diff_previews, queue_total)

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    payload = build_payload(text, webhook_type, chat_id or None)
    if webhook_type == "telegram" and not payload.get("chat_id"):
        print("WEBHOOK_TYPE=telegram 需要设置 TELEGRAM_CHAT_ID，跳过通知")
        return 1

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"[webhook] 发送失败：{e.__class__.__name__}: {e}")
        return 1
    if resp.status_code >= 300:
        print(f"[webhook] HTTP {resp.status_code}：{resp.text[:200]}")
        return 1
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not platform_ok(body):
        print(f"[webhook] 平台拒绝（HTTP 200 但业务失败）：{str(body)[:200]}")
        return 1
    print(f"[webhook] 通知已发送（{webhook_type}，{len(changed)} 项变更）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
