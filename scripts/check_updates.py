#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 政策更新监控脚本

功能：
  - 读取 data/products.json（ID 索引）与 data/policies/{id}.json
  - 每个产品监控多个目标 URL：顶层 policy_url（main）+ 各版本独立的 policy_link
    （toc 个人版 / tob 企业版，与 main 去重后逐条检查）
  - 抓取政策页面，剥离 script/style 后提取正文文本、归一化空白，计算 SHA256 哈希
    （直接对原始 HTML 哈希会因时间戳、CSRF token 等动态内容产生大量误报）
  - 支持 ETag / If-Modified-Since 条件请求，页面未变化时服务端返回 304，零误报
  - 与 data/update_status.json 中上次记录对比；哈希变化则标记"⚠️ 政策可能已更新，待核实"
  - 每次成功抓取将正文快照写入 data/snapshots/{id}/{target}/latest.txt；
    首次记录基线或检测到变更时额外写入按日期命名的存档（{YYYY-MM-DD}.txt），
    便于用 git diff / 文本对比工具查看政策到底改了什么
  - 结果写入 data/update_status.json（首页会读取并展示监控状态），告警输出到控制台

使用方法：
  .venv/bin/python scripts/check_updates.py [--delay 秒] [--timeout 秒]
  （或先 source .venv/bin/activate 再 python3 scripts/check_updates.py）

依赖安装：
  ./start.sh                                    # 自动创建 .venv 并安装依赖
  # 或手动：
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt    # requests + beautifulsoup4

Cron 配置示例（每周一早上 9 点运行）：
  # 编辑 crontab
  crontab -e

  # 添加以下行（注意修改路径；logs 目录需预先创建：mkdir -p logs）
  0 9 * * 1 cd /path/to/ai-policy-tracker && mkdir -p logs && .venv/bin/python scripts/check_updates.py >> logs/check_updates.log 2>&1

输出文件：
  data/update_status.json - 每个产品的聚合检查状态 + 各目标 URL 明细（首页读取展示）
  data/snapshots/         - 政策正文快照（latest.txt 为当前内容，日期文件为基线/变更存档）

退出码：总是 0（只要状态文件写成功）。个别产品检查失败不视为脚本失败——
结果中的 failed 计数与 Issue 告警会反映失败情况，CI 中失败不应阻塞状态提交。
"""

import argparse
import datetime
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # 退化为正则去标签，建议安装 beautifulsoup4

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_FILE = os.path.join(BASE_DIR, "data", "products.json")
POLICIES_DIR = os.path.join(BASE_DIR, "data", "policies")
STATUS_FILE = os.path.join(BASE_DIR, "data", "update_status.json")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "data", "snapshots")

# 哈希算法版本：提取/归一化逻辑变化时递增，旧状态会自动重建基线而不是误报"已变更"
HASH_SCHEME = "text-v1"
RETRY_TIMES = 2          # 网络类错误重试次数
RETRY_BACKOFF = 5        # 重试间隔基数（秒）

# 监控目标的中文名（控制台输出与 Issue 正文用）
TARGET_LABELS = {"main": "主监控页", "toc": "个人版条款", "tob": "企业版条款"}

USER_AGENT = (
    "Mozilla/5.0 (compatible; AI-Policy-Tracker/1.0; "
    "+https://github.com/838860610/ai-policy-tracker)"
)


def load_product_ids():
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    return index.get("products", [])


def load_policy(pid):
    path = os.path.join(POLICIES_DIR, pid + ".json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_previous_status():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def extract_text(raw_html):
    """剥离 script/style 等非正文标签，提取可见文本。"""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg", "iframe"]):
            tag.decompose()
        return soup.get_text()
    text = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html_lib.unescape(text)


def normalize_text(text):
    """归一化空白：所有连续空白（含换行）折叠为单个空格。

    使哈希对纯排版变化不敏感：换行、缩进、行内标签边界（如 <span> 拆分）
    均不影响结果，只有真实文字增删改才会改变哈希。
    """
    return re.sub(r"\s+", " ", text).strip()


def snapshot_text(text):
    """快照文件的正文格式：逐行归一化并保留段落换行，便于 git diff 逐段比对。

    哈希仍基于 fully-collapsed 的 normalize_text 结果（text-v1 口径），二者独立。
    """
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def save_snapshot(pid, key, raw_text, archived):
    """写入最新快照；archived=True 时额外写日期存档（首次基线或检测到变更）。"""
    target_dir = os.path.join(SNAPSHOTS_DIR, pid, key)
    os.makedirs(target_dir, exist_ok=True)
    body = snapshot_text(raw_text)
    if not body:
        return
    with open(os.path.join(target_dir, "latest.txt"), "w", encoding="utf-8") as f:
        f.write(body + "\n")
    if archived:
        dated = os.path.join(target_dir, datetime.date.today().isoformat() + ".txt")
        with open(dated, "w", encoding="utf-8") as f:
            f.write(body + "\n")


def compute_hash(normalized_text):
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def fetch_url(url, etag=None, last_modified=None, timeout=30):
    """带条件请求的抓取。返回 (response, was_304)。"""
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    resp = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
    if resp.status_code == 304:
        return resp, True
    resp.raise_for_status()
    return resp, False


def fetch_with_retry(url, etag, last_modified, timeout):
    """网络类错误（超时/连接失败）按指数退避重试；HTTP 4xx/5xx 不重试直接抛出。"""
    last_exc = None
    for attempt in range(RETRY_TIMES + 1):
        try:
            return fetch_url(url, etag, last_modified, timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < RETRY_TIMES:
                wait = RETRY_BACKOFF * (attempt + 1)
                print(f"         请求失败（{e.__class__.__name__}），{wait}s 后重试…")
                time.sleep(wait)
    raise last_exc


def collect_targets(policy):
    """汇总一个产品的监控目标：[(key, url), ...]，按 URL 去重。

    main = 顶层 policy_url；toc/tob = 各版本独立的 policy_link（与 main 相同则不重复监控）。
    """
    targets = []
    seen = set()
    main_url = policy.get("policy_url", "")
    if main_url and main_url != "待核实":
        targets.append(("main", main_url))
        seen.add(main_url)
    versions = policy.get("versions") or {}
    for key in ("toc", "tob"):
        link = (versions.get(key) or {}).get("policy_link") or ""
        if link and link not in seen and link != "待核实":
            targets.append((key, link))
            seen.add(link)
    return targets


def base_target_result(url, prev_target, **extra):
    result = {
        "url": url,
        "hash_scheme": HASH_SCHEME,
        "last_checked": datetime.datetime.now().isoformat(),
        "last_changed_date": prev_target.get("last_changed_date"),
    }
    result.update(extra)
    return result


def check_target(pid, name, key, url, prev_target, timeout):
    """检查单个目标 URL，返回该目标的状态明细。"""
    label = TARGET_LABELS.get(key, key)
    # 哈希算法版本不同或没有记录过哈希时，重建基线
    prev_hash = prev_target.get("current_hash") if prev_target.get("hash_scheme") == HASH_SCHEME else None
    if prev_target and prev_hash is None and prev_target.get("current_hash"):
        print(f"  [基线] {name} ({pid}·{label}): 哈希算法已升级，重新记录基线")

    etag = prev_target.get("content_etag")
    last_modified = prev_target.get("content_last_modified")

    try:
        resp, was_304 = fetch_with_retry(url, etag, last_modified, timeout)
        now = datetime.datetime.now().isoformat()

        if was_304:
            print(f"  [OK]   {name} ({pid}·{label}): 内容未变化（304 Not Modified）")
            return base_target_result(url, prev_target, current_hash=prev_hash, status="ok",
                                      content_etag=etag, content_last_modified=last_modified,
                                      message="内容未变化（304 Not Modified）", last_checked=now)

        raw_text = extract_text(resp.text)
        normalized = normalize_text(raw_text)
        current_hash = compute_hash(normalized)

        if prev_hash is None:
            print(f"  [新增] {name} ({pid}·{label}): 首次记录基线")
            save_snapshot(pid, key, raw_text, archived=True)
            result = base_target_result(url, prev_target, current_hash=current_hash, status="ok",
                                        message="首次检查，已记录基线 hash", last_changed_date=None)
        elif current_hash == prev_hash:
            print(f"  [OK]   {name} ({pid}·{label}): 内容未变化")
            result = base_target_result(url, prev_target, current_hash=current_hash, status="ok",
                                        message="内容未变化")
        else:
            print(f"  [⚠️]   {name} ({pid}·{label}): 政策可能已更新！待核实")
            print(f"         URL: {url}")
            save_snapshot(pid, key, raw_text, archived=True)
            result = base_target_result(url, prev_target, current_hash=current_hash, status="changed",
                                        message="⚠️ 政策可能已更新，待核实",
                                        last_changed_date=now)

        result["content_etag"] = resp.headers.get("ETag")
        result["content_last_modified"] = resp.headers.get("Last-Modified")
        return result

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        print(f"  [失败] {name} ({pid}·{label}): 请求失败（重试后仍超时/连接失败）- {e.__class__.__name__}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  message=f"检查失败：请求异常 - {e.__class__.__name__}")
    except requests.exceptions.HTTPError as e:
        print(f"  [失败] {name} ({pid}·{label}): HTTP 错误 - {e}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  message=f"检查失败：HTTP 错误 - {e}")
    except requests.exceptions.RequestException as e:
        print(f"  [失败] {name} ({pid}·{label}): 请求异常 - {e}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  message=f"检查失败：请求异常 - {e}")


def migrate_prev_targets(prev_entry):
    """兼容旧版单 URL 状态格式：旧的扁平记录（含 current_hash）视为 main 目标的历史状态。"""
    if not prev_entry:
        return {}
    targets = prev_entry.get("targets")
    if isinstance(targets, dict):
        return targets
    if prev_entry.get("current_hash"):
        return {"main": prev_entry}
    return {}


def check_product(pid, policy, prev_entry, timeout, delay):
    """检查一个产品的全部目标 URL，返回聚合后的产品级状态（首页兼容旧结构）。"""
    name = policy.get("name", pid)
    targets = collect_targets(policy)

    if not targets:
        print(f"  [跳过] {name} ({pid}): URL 为空或待核实")
        return {"status": "skipped", "message": "URL 为空或待核实，跳过检查",
                "last_checked": datetime.datetime.now().isoformat()}

    prev_targets = migrate_prev_targets(prev_entry)
    target_results = {}
    statuses = []
    for i, (key, url) in enumerate(targets):
        target_results[key] = check_target(pid, name, key, url,
                                           prev_targets.get(key, {}), timeout)
        statuses.append(target_results[key]["status"])
        if i < len(targets) - 1:
            time.sleep(delay)

    # 聚合规则：任一目标变更 → changed；否则任一失败 → failed；否则 ok
    if "changed" in statuses:
        status = "changed"
    elif "failed" in statuses:
        status = "failed"
    else:
        status = "ok"

    changed_keys = [k for k, r in target_results.items() if r["status"] == "changed"]
    if changed_keys:
        summary = "⚠️ 政策可能已更新，待核实（" + "、".join(
            TARGET_LABELS.get(k, k) for k in changed_keys) + "）"
    elif "failed" in statuses:
        failed_keys = [k for k, r in target_results.items() if r["status"] == "failed"]
        summary = "部分目标检查失败（" + "、".join(
            TARGET_LABELS.get(k, k) for k in failed_keys) + "），其余未变化"
    else:
        summary = "内容未变化"

    return {
        "status": status,
        "url": targets[0][1],
        "message": summary,
        "last_checked": datetime.datetime.now().isoformat(),
        "targets": target_results,
    }


def main():
    parser = argparse.ArgumentParser(description="AI 政策更新监控")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="相邻请求间隔秒数（礼貌抓取，默认 1.5）")
    parser.add_argument("--timeout", type=int, default=30,
                        help="单次请求超时秒数（默认 30）")
    args = parser.parse_args()

    print("=" * 60)
    print("AI 政策更新监控脚本")
    print("运行时间：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print(f"哈希方案：{HASH_SCHEME}（正文文本归一化，按版本 URL 逐条监控）")
    print("=" * 60)

    pids = load_product_ids()
    prev_status = load_previous_status().get("products", {})
    new_status = {}
    changed_count = failed_count = skipped_count = 0
    total_targets = 0

    print(f"\n共 {len(pids)} 个产品需要检查\n")

    for i, pid in enumerate(pids):
        policy = load_policy(pid)
        prev = prev_status.get(pid, {})
        new_status[pid] = check_product(pid, policy, prev, args.timeout, args.delay)
        total_targets += len(new_status[pid].get("targets", {}))

        status = new_status[pid]["status"]
        if status == "changed":
            changed_count += 1
        elif status == "failed":
            failed_count += 1
        elif status == "skipped":
            skipped_count += 1

        if i < len(pids) - 1:
            time.sleep(args.delay)

    status_data = {
        "meta": {
            "last_run": datetime.datetime.now().isoformat(),
            "hash_scheme": HASH_SCHEME,
            "total_products": len(pids),
            "total_targets": total_targets,
            "changed": changed_count,
            "failed": failed_count,
            "skipped": skipped_count,
        },
        "products": new_status,
    }

    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status_data, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("检查完成")
    print(f"  产品: {len(pids)}，监控目标: {total_targets}")
    print(f"  未变化: {len(pids) - changed_count - failed_count - skipped_count}")
    print(f"  已变更: {changed_count}")
    print(f"  失败:   {failed_count}")
    print(f"  跳过:   {skipped_count}")
    print(f"  状态文件: {STATUS_FILE}")
    print("=" * 60)

    if changed_count > 0:
        print(f"\n⚠️ 告警：检测到 {changed_count} 个产品政策可能已更新，请及时核实！")
        for pid, info in new_status.items():
            if info["status"] == "changed":
                for key, t in (info.get("targets") or {}).items():
                    if t.get("status") == "changed":
                        print(f"  - {pid}（{TARGET_LABELS.get(key, key)}）: {t['url']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
