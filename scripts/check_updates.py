#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 政策更新监控脚本

功能：
  - 读取 site/data/products.json（ID 索引）与 site/data/policies/{id}.json
  - 每个产品监控多个目标 URL：顶层 policy_url（main）+ 各版本独立的 policy_link
    （toc 个人版 / tob 企业版，与 main 去重后逐条检查）
  - 抓取政策页面，剥离 script/style 后提取正文文本、归一化空白，计算 SHA256 哈希
    （直接对原始 HTML 哈希会因时间戳、CSRF token 等动态内容产生大量误报）
  - 支持 ETag / If-Modified-Since 条件请求，页面未变化时服务端返回 304，零误报
  - 与 site/generated/update_status.json 中上次记录对比；哈希变化则标记"⚠️ 政策可能已更新，待核实"
  - 每次成功抓取将正文快照写入 site/generated/snapshots/{id}/{target}/latest.txt；
    首次记录基线或检测到变更时额外写入按日期命名的存档（{YYYY-MM-DD}.txt），
    便于用 git diff / 文本对比工具查看政策到底改了什么
  - 结果写入 site/generated/update_status.json（首页会读取并展示监控状态），告警输出到控制台

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
  site/generated/update_status.json - 每个产品的聚合检查状态 + 各目标 URL 明细（首页读取展示）
  site/generated/snapshots/         - 政策正文快照（latest.txt 为当前内容，日期文件为基线/变更存档）

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
INDEX_FILE = os.path.join(BASE_DIR, "site", "data", "products.json")
POLICIES_DIR = os.path.join(BASE_DIR, "site", "data", "policies")
STATUS_FILE = os.path.join(BASE_DIR, "site", "generated", "update_status.json")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "site", "generated", "snapshots")

# 哈希算法版本：提取/归一化逻辑变化时递增，旧状态会自动重建基线而不是误报"已变更"
# - text-v2：修复响应解码（此前中文被 latin-1 回退解成 mojibake）
# - text-v3：把"提取器变体"并入 scheme。BeautifulSoup 与正则回退剥离的标签集不同，
#   同一页面两条路径产出的归一化文本也不同；不区分的话，一旦 bs4 缺失（未安装依赖）
#   全库哈希会一次性漂移，造成批量误报。故 scheme 形如 text-v3-bs4 / text-v3-regex。
EXTRACTOR = "bs4" if BeautifulSoup is not None else "regex"
HASH_SCHEME = f"text-v3-{EXTRACTOR}"
RETRY_TIMES = 2          # 网络类错误重试次数
RETRY_BACKOFF = 5        # 重试间隔基数（秒）
# 正文最小长度：低于此值视为"空壳正文"（SPA / 反爬只返回标题骨架），
# 不建基线也不报变更——否则既会漏报（正文由 JS 渲染）又会误报（标题微调）。
MIN_BODY_CHARS = 500

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
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"  [错误] 无法读取 {path}：{e}")
        return {}


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
    """写入最新快照；archived=True 时额外写日期存档（首次基线或检测到变更）。
    变更时先把旧 latest.txt 保存为 prev.txt，供 analyze_changes.py 对比。"""
    target_dir = os.path.join(SNAPSHOTS_DIR, pid, key)
    os.makedirs(target_dir, exist_ok=True)
    body = snapshot_text(raw_text)
    if not body:
        return
    latest_path = os.path.join(target_dir, "latest.txt")
    # 变更时先备份旧快照
    if archived and os.path.exists(latest_path):
        prev_path = os.path.join(target_dir, "prev.txt")
        with open(latest_path, encoding="utf-8") as old_f:
            old_body = old_f.read()
        if old_body.strip() and old_body.strip() != body.strip():
            with open(prev_path, "w", encoding="utf-8") as f:
                f.write(old_body)
    with open(latest_path, "w", encoding="utf-8") as f:
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


def response_text(resp):
    """返回正确解码的响应正文。

    requests 对 Content-Type 未声明 charset 的 text/* 响应，按 RFC 2616 回退到
    ISO-8859-1 解码——中文页面会被解成一串拉丁字符（mojibake），再以 UTF-8 写进
    快照就成了双重编码的乱码，人没法读，AI 变更分析也拿不到有效文本。

    处理顺序：
      1. 响应未声明 charset → 用 requests 探测的 apparent_encoding，兜底 utf-8
      2. 响应声明了 ISO-8859-1 但内容其实是 UTF-8 → 反向还原一次
    """
    content_type = (resp.headers.get("Content-Type") or "").lower()

    if "charset" not in content_type:
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    text = resp.text
    if "iso-8859-1" in content_type or "latin-1" in content_type:
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                return repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def fetch_with_retry(url, etag, last_modified, timeout):
    """网络类错误（超时/连接失败）按指数退避重试；HTTP 4xx/5xx 不重试直接抛出。
    429 Too Many Requests：等待 Retry-After 或退避后重试。"""
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
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt < RETRY_TIMES:
                retry_after = e.response.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else RETRY_BACKOFF * (attempt + 2)
                print(f"         被限流（429），{wait}s 后重试…")
                time.sleep(wait)
                continue
            raise
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

        raw_text = extract_text(response_text(resp))
        normalized = normalize_text(raw_text)
        current_hash = compute_hash(normalized)

        if len(normalized) < MIN_BODY_CHARS:
            # 空壳正文：不建基线、不报变更，标记为 suspicious 交由人工处理
            print(f"  [可疑] {name} ({pid}·{label}): 正文仅 {len(normalized)} 字符，"
                  f"疑似 JS 渲染/反爬空壳，未记录基线")
            return base_target_result(url, prev_target, current_hash=prev_hash, status="suspicious",
                                      message=f"抓取正文过短（{len(normalized)} 字符 < "
                                              f"{MIN_BODY_CHARS}），疑似 JS 渲染或反爬，未记录基线",
                                      last_checked=now)

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
        print(f"         URL: {url}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  message=f"检查失败：请求异常 - {e.__class__.__name__}")
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "?"
        print(f"  [失败] {name} ({pid}·{label}): HTTP {status_code} 错误")
        print(f"         URL: {url}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  message=f"检查失败：HTTP {status_code} 错误 - {e}")
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

    if policy.get("monitor") is False:
        # 占位条目（无公开政策页 / 政策 URL 指向产品首页）：不抓取，避免持续误报
        return {"status": "skipped", "message": "该产品已标记为不监控（无独立公开政策页）",
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

    # 聚合规则：changed > failed > suspicious > ok
    if "changed" in statuses:
        status = "changed"
    elif "failed" in statuses:
        status = "failed"
    elif "suspicious" in statuses:
        status = "suspicious"
    else:
        status = "ok"

    changed_keys = [k for k, r in target_results.items() if r["status"] == "changed"]
    failed_keys = [k for k, r in target_results.items() if r["status"] == "failed"]
    suspicious_keys = [k for k, r in target_results.items() if r["status"] == "suspicious"]
    if changed_keys:
        summary = "⚠️ 政策可能已更新，待核实（" + "、".join(
            TARGET_LABELS.get(k, k) for k in changed_keys) + "）"
    elif failed_keys:
        # 全部失败时不能再说"部分"
        if len(failed_keys) == len(statuses):
            summary = "全部目标检查失败（" + "、".join(
                TARGET_LABELS.get(k, k) for k in failed_keys) + "）"
        else:
            summary = "部分目标检查失败（" + "、".join(
                TARGET_LABELS.get(k, k) for k in failed_keys) + "），其余未变化"
    elif suspicious_keys:
        summary = "正文疑似空壳（" + "、".join(
            TARGET_LABELS.get(k, k) for k in suspicious_keys) + "），未记录基线，需人工确认抓取目标"
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
    changed_count = failed_count = skipped_count = suspicious_count = 0
    total_targets = 0

    print(f"\n共 {len(pids)} 个产品需要检查\n")

    for i, pid in enumerate(pids):
        policy = load_policy(pid)
        prev = prev_status.get(pid, {})
        if not policy:
            new_status[pid] = {"status": "failed", "message": "数据文件缺失或不是合法 JSON",
                               "last_checked": datetime.datetime.now().isoformat()}
            failed_count += 1
            continue
        new_status[pid] = check_product(pid, policy, prev, args.timeout, args.delay)
        total_targets += len(new_status[pid].get("targets", {}))

        status = new_status[pid]["status"]
        if status == "changed":
            changed_count += 1
        elif status == "failed":
            failed_count += 1
        elif status == "suspicious":
            suspicious_count += 1
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
            "suspicious": suspicious_count,
            "skipped": skipped_count,
        },
        "products": new_status,
    }

    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    # 原子写：先落临时文件再 rename，避免中途被 kill（CI 超时）留下截断的 JSON
    tmp_path = STATUS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(status_data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATUS_FILE)

    print("\n" + "=" * 60)
    print("检查完成")
    print(f"  产品: {len(pids)}，监控目标: {total_targets}")
    print(f"  未变化: {len(pids) - changed_count - failed_count - suspicious_count - skipped_count}")
    print(f"  已变更: {changed_count}")
    print(f"  失败:   {failed_count}")
    print(f"  可疑:   {suspicious_count}（正文疑似空壳，未记录基线）")
    print(f"  跳过:   {skipped_count}")
    print(f"  状态文件: {STATUS_FILE}")
    print("=" * 60)

    if changed_count == 0 and failed_count == len(pids) and pids:
        print("\n❌ 本轮全部产品检查失败：可能是网络/代理故障或 URL 大面积失效，请人工确认监控是否正常")

    if changed_count > 0:
        print(f"\n⚠️ 告警：检测到 {changed_count} 个产品政策可能已更新，请及时核实！")
        for pid, info in new_status.items():
            if info["status"] == "changed":
                for key, t in (info.get("targets") or {}).items():
                    if t.get("status") == "changed":
                        print(f"  - {pid}（{TARGET_LABELS.get(key, key)}）: {t['url']}")

    if failed_count > 0:
        print(f"\n❌ 以下 {failed_count} 个产品检查失败（下次运行会自动重试）：")
        for pid, info in new_status.items():
            if info["status"] == "failed":
                for key, t in (info.get("targets") or {}).items():
                    if t.get("status") == "failed":
                        msg = t.get("message", "")
                        # 简化消息：提取关键错误类型
                        if "SSLError" in msg:
                            reason = "SSL 证书验证失败（可能是防火墙/代理拦截）"
                        elif "ConnectTimeout" in msg or "Timeout" in msg:
                            reason = "连接超时（网站不可达）"
                        elif "403" in msg:
                            reason = "403 Forbidden（服务器拒绝访问，可能有反爬）"
                        elif "405" in msg:
                            reason = "405 Method Not Allowed（服务器不接受 GET 请求）"
                        elif "ConnectionError" in msg:
                            reason = "连接失败"
                        else:
                            reason = msg
                        print(f"  - {pid}（{TARGET_LABELS.get(key, key)}）: {reason}")
                        print(f"    URL: {t['url']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
