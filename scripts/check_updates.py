#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 政策更新监控脚本

功能：
  - 读取 site/data/products.json（ID 索引）与 site/data/policies/{id}.json
  - 每个产品监控多个目标 URL：顶层 policy_url（main）+ 各版本独立的 policy_link
    （toc 个人版 / tob 企业版）+ sources[] 补充来源
  - 抓取政策页面，按 HTML/PDF/文本类型提取正文、归一化空白，计算 SHA256 哈希
    （直接对原始 HTML 哈希会因时间戳、CSRF token 等动态内容产生大量误报）
  - 支持 ETag / If-Modified-Since 条件请求，页面未变化时服务端返回 304，零误报
  - 与 site/generated/update_status.json 中上次记录对比；哈希变化则标记"⚠️ 政策可能已更新，待核实"
  - 每次成功抓取将正文快照写入 site/generated/snapshots/{id}/{target}/latest.txt；
    首次记录基线或检测到变更时额外写入按日期命名的存档（{YYYY-MM-DD}.txt），
    便于用 git diff / 文本对比工具查看政策到底改了什么
  - 结果写入 site/generated/update_status.json（首页会读取并展示监控状态），告警输出到控制台

使用方法：
  .venv/bin/python scripts/check_updates.py [--delay 秒] [--timeout 秒] [--no-browser] [--fail-on-error]
  （或先 source .venv/bin/activate 再 python3 scripts/check_updates.py）

依赖安装：
  ./start.sh                                    # 自动创建 .venv 并安装依赖
  # 或手动：
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt    # requests + beautifulsoup4 + pypdf

  无头浏览器抓取（可选，仅 fetch_method=browser 的产品需要，如 ChatGPT/OpenAI
  政策页被 Cloudflare 拦截）：
    pip install -r requirements-browser.txt && playwright install chromium
  CI（monitor.yml）也会安装 playwright 并监控这类产品；本地若未装 playwright，
  可用 --no-browser 跳过它们（避免 chatgpt 被判 failed）。

Cron 配置示例（每周一早上 9 点运行）：
  # 编辑 crontab
  crontab -e

  # 添加以下行（注意修改路径；logs 目录需预先创建：mkdir -p logs）
  0 9 * * 1 cd /path/to/ai-policy-tracker && mkdir -p logs && .venv/bin/python scripts/check_updates.py >> logs/check_updates.log 2>&1

输出文件：
  site/generated/update_status.json - 每个产品的聚合检查状态 + 各目标 URL 明细（首页读取展示）
  site/generated/snapshots/         - 政策正文快照（latest.txt 为当前内容，日期文件为基线/变更存档）

退出码：默认 0；使用 --fail-on-error 时存在产品检查失败返回非零。
"""

import argparse
import datetime
import hashlib
import html as html_lib
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from urllib.parse import urljoin, urlparse

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
PENDING_FILE = os.path.join(BASE_DIR, "site", "generated", "pending_verification.json")
HEALTH_FILE = os.path.join(BASE_DIR, "site", "generated", "monitor_health.json")

# 哈希算法版本：提取/归一化逻辑变化时递增，旧状态会自动重建基线而不是误报"已变更"
# - text-v2：修复响应解码（此前中文被 latin-1 回退解成 mojibake）
# - text-v4：加入结构化正文选择、PDF 处理和更保守的动态节点过滤。
EXTRACTOR = "bs4" if BeautifulSoup is not None else "regex"
HASH_SCHEME = f"text-v4-{EXTRACTOR}"
RETRY_TIMES = 2          # 网络类错误重试次数
RETRY_BACKOFF = 5        # 重试间隔基数（秒）
# 正文最小长度：低于此值视为"空壳正文"（SPA / 反爬只返回标题骨架），
# 不建基线也不报变更——否则既会漏报（正文由 JS 渲染）又会误报（标题微调）。
MIN_BODY_CHARS = 500
ID_PATTERN = re.compile(r"^[a-z0-9-]+$")
BROWSER_RENDER_ATTEMPTS = 3   # browser 抓取的渲染尝试次数，取正文最长的一次
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_RETRY_AFTER_SECONDS = 300
CONNECT_TIMEOUT_CAP = 5    # 连接阶段超时上限（秒）：域名不可达时快速失败
RETRY_BUDGET_SECONDS = 120  # 单个目标网络重试的总时间上限（秒），避免不可达域名拖垮整轮

# 监控目标的中文名（控制台输出与待核实队列用）
TARGET_LABELS = {"main": "主监控页", "toc": "个人版条款", "tob": "企业版条款"}

# 抓取健康状态（health）：与"政策是否变化"（status）正交。
#   ok           正常，内容可信
#   initialized  首次建立基线，尚无历史可比较（无需处理）
#   rebaselined  因基线缺失/哈希方案升级而重建，需人工确认一次
#   degraded     本轮抓取异常，但已保留上次有效快照（可继续对外展示）
#   no_baseline  本轮抓取异常且无可验证基线（该产品暂无可靠正文）
#   blocked      被反爬/限流/权限拒绝（403/429/401 等）
HEALTH_QUEUED_STATES = ("degraded", "no_baseline", "blocked")
HEALTH_SEVERITY = {"blocked": 3, "no_baseline": 2, "degraded": 1}
HEALTH_ACTIONS = {
    "blocked": "检查反爬/限流策略，必要时为该目标配置 fetch_method=browser 后重试",
    "no_baseline": "确认页面是否 JS 渲染或反爬空壳，配置 content_selector / browser 后重试；"
                    "若连接超时且本机网络无法访问该域名（常见于境外政策站点），"
                    "以 GitHub Actions 监控结果为准",
    "degraded": "已保留上次有效快照；用 --only <pid>:<key> 单独重试并确认正文",
}

USER_AGENT = (
    "Mozilla/5.0 (compatible; AI-Policy-Tracker/1.0; "
    "+https://github.com/838860610/ai-policy-tracker)"
)


def load_product_ids():
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    ids = index.get("products") if isinstance(index, dict) else None
    if not isinstance(ids, list) or not ids:
        raise ValueError("products.json 的 products 必须是非空 ID 数组")
    if any(not isinstance(pid, str) or not ID_PATTERN.match(pid) for pid in ids):
        raise ValueError("products.json 包含非法产品 ID")
    return ids


def load_policy(pid):
    path = os.path.join(POLICIES_DIR, pid + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, json.JSONDecodeError) as e:
        print(f"  [错误] 无法读取 {path}：{e}")
        return {}


def load_previous_status():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError):
            pass
    return {}


# 文档站/反爬页常见的“非内容”UI 碎片（按钮文案、目录锚点、回到顶部等）。
# 这些文本会随渲染时机或 UI 状态偶发出现/消失，导致正文哈希抖动而误报“已变更”
# （例如 docs.trae.cn 偶发渲染出的“复制页面”按钮）。仅剔除明确属于 UI 控件、
# 绝不会作为政策条款正文出现的固定短语，保守清单、避免误删真实条款。
UI_NOISE_PHRASES = (
    "复制页面", "复制代码", "复制链接",
    "编辑此页", "编辑页面", "编辑文档",
    "本页目录", "此页内容", "页面目录",
    "回到顶部", "回到开头", "返回顶部",
    "加载更多", "显示更多", "查看更多",
    # 火山方舟等文档站的新手引导浮层按钮（doubao-api 实测 11564 ↔ 11593 字符，
    # 差异仅此浮层的显示/隐藏状态）
    "我知道了 不再提醒", "我知道了，不再提醒", "不再提醒",
    "On this page", "Back to top", "Copy page", "Copy code", "Copy link",
    "Edit this page", "Table of contents",
)

# 阿里云帮助中心等文档模板会在正文之后异步注入“精选产品 / 精选解决方案 / 配置报价器”
# 等推荐挂件；它们有时渲染有时不渲染，导致正文长度波动（qwenwork 实测 7341↔6066 字符）。
# 这些挂件位于正文之后、永不作为政策条款，故从首个挂件标记起到文末整体剔除。
ALIYUN_WIDGET_ANCHORS = ("精选产品", "精选解决方案", "配置报价器")

# 站点页脚/版权站壳锚点（阿里云、trae 等文档站通用）：这些短语只出现在页脚，
# 绝不会作为政策条款正文。从首个锚点到文末整体剔除，使哈希不受页脚渲染波动影响。
FOOTER_ANCHORS = ("京公网安备", "京ICP备", "企业咨询热线", "营业执照",
                 "关注微信公众号", "版权所有", "TRAE先一步体验未来")

# 帮助中心类页面在文末注入的 UI 尾巴，会随渲染时机变化而误报"已变更"：
# - 谷歌帮助中心："Need more help? ..." → 语言选择器 → Enable Dark Mode → 反馈区，
#   其中嵌有每次加载都重新生成的长数字令牌（Gemini 隐私页两次抓取
#   2706528264544687043 → 14347482587443921844，483 行正文仅此一处不同），
#   实测位于全文 97.3%；
# - Anthropic 帮助中心：文末 "Related Articles" 推荐阅读区块，其中的链接标题
#   顺序/有无会随抓取变化（claude/toc 实测 2736 ↔ 2710 字，差异仅在该区块），
#   实测位于全文 83.4%。
# 这些尾巴绝不作为政策条款，故从首个标记起到文末整体剔除。
HELP_UI_ANCHORS = ("Need more help?", "Enable Dark Mode", "Related Articles")

# 部分站点把导航 / 语言选择器渲染在正文之前，且该区块是否渲染会随抓取时机变化
# （实测 chatgpt/main 旧 6356 → 新 5842 字，差异全部落在头部导航与语言列表，
# 条款正文零差异，且"使用条款生效日期 2026 年 1 月 1 日"新旧一致）。
# 以正文起始标记为界切掉其之前的导航。
#   - chatgpt/tob：语言下拉列表（"OpenAI 输入语言 English (United States) العربية …"）
#     展开与否导致 15147 ↔ 15752 字波动，其后紧跟 "Updated: YYYY年M月D日"（实测占比 4.1%）
#
# 标记只认 OpenAI/英文站的 "Published/Updated: YYYY年" 格式，**不要**加中文的
# "生效日期："——腾讯系协议页开头是「文档标题 + 更新日期 + 生效日期」，
# 用它做标记会把标题和更新日期一起切掉（实测 tencent-yuanbao 少 26 字符、
# ima 少 62、yuanqi 少 28），而这些字段正是政策版本标识，必须保留。
LEAD_IN_MARKER_RE = re.compile(
    r"(?:Published|Updated)\s*:\s*\d{4}\s*年")
LEAD_IN_MAX_RATIO = 0.15

# 动态长数字仅在父节点明确标记为 token/session/nonce 等资源节点时移除。
LONG_TOKEN_RE = re.compile(r"\b\d{16,}\b")


def extract_text(raw_html, content_selector=None):
    """剥离非正文节点，提取可见文本，并剔除 UI 噪音碎片。

    content_selector：可选 CSS 选择器，用于正文不在 main/article 内的页面
    （常见于腾讯系文档预览页、富文本容器）。选择器未命中时回退到默认启发式。
    """
    if raw_html is None:
        return ""
    selector = (content_selector or "").strip()
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg", "iframe",
                         "footer", "nav", "aside"]):
            tag.decompose()
        for node in soup.find_all(string=LONG_TOKEN_RE):
            parent = node.parent
            marker = ""
            if parent is not None:
                marker = " ".join(parent.get("class", [])) + " " + str(parent.get("id", ""))
            if any(word in marker.lower() for word in
                   ("token", "session", "nonce", "trace", "csrf", "resource")):
                node.replace_with("")
        root = None
        if selector:
            try:
                root = soup.select_one(selector)
            except (NotImplementedError, ValueError):
                root = None
        if root is None:
            root = (soup.find("main") or soup.find("article")
                    or soup.find(attrs={"role": "main"}) or soup.body or soup)
        text = root.get_text("\n")
    else:
        text = re.sub(r"(?is)<(script|style|noscript|svg|footer|nav|aside)\b.*?</\1>", " ", raw_html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html_lib.unescape(text)
    for phrase in UI_NOISE_PHRASES:
        text = text.replace(phrase, "")
    for anchor in ALIYUN_WIDGET_ANCHORS + FOOTER_ANCHORS + HELP_UI_ANCHORS:
        idx = text.find(anchor)
        if idx != -1 and idx >= len(text) * 0.6:
            text = text[:idx]
            break
    m = LEAD_IN_MARKER_RE.search(text)
    if m and m.start() < len(text) * LEAD_IN_MAX_RATIO:
        text = text[m.start():]
    return text


def normalize_text(text):
    """归一化空白：所有连续空白（含换行）折叠为单个空格。

    使哈希对纯排版变化不敏感：换行、缩进、行内标签边界（如 <span> 拆分）
    均不影响结果，只有真实文字增删改才会改变哈希。
    """
    return re.sub(r"\s+", " ", text).strip()


def snapshot_text(text):
    """快照文件的正文格式：逐行归一化并保留段落换行，便于 git diff 逐段比对。

    哈希仍基于 fully-collapsed 的 normalize_text 结果，二者独立。
    """
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def atomic_write_text(path, text):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def save_snapshot(pid, key, raw_text, archived):
    """写入最新快照；archived=True 时额外写日期存档（首次基线或检测到变更）。
    变更时先把旧 latest.txt 保存为 prev.txt，供 policy_verify.py 对比。"""
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
        if old_body.lstrip().startswith("%PDF-"):
            if os.path.exists(prev_path):
                os.remove(prev_path)
            old_body = ""
        if old_body.strip() and old_body.strip() != body.strip():
            atomic_write_text(prev_path, old_body)
    atomic_write_text(latest_path, body + "\n")
    if archived:
        dated = os.path.join(target_dir, datetime.date.today().isoformat() + ".txt")
        atomic_write_text(dated, body + "\n")
        prune_dated(target_dir)


def load_baseline_text(pid, key):
    """读取已入库的基线快照文本（归一化），用于"方案无关"的变更比对。

    基线 = 上次成功抓取并存下的 latest.txt，不依赖 update_status 里的哈希，
    因此哈希方案升级（text-v2→text-v4 等）时不会丢失基线、也不会整库误报。
    """
    path = os.path.join(SNAPSHOTS_DIR, pid, key, "latest.txt")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if content.lstrip().startswith("%PDF-"):
            return None
        return normalize_text(content)
    except (OSError, UnicodeError):
        return None


def baseline_saved_at(pid, key):
    """基线快照的保存时间（ISO），用于在没有 last_good_at 字段时回填。

    旧版状态文件没有 last_good_at，但"上次可信正文何时入库"可以从快照 mtime 得到；
    否则一个 degraded（已保留上次快照）的目标会显示"从未成功抓取"，自相矛盾。
    """
    path = os.path.join(SNAPSHOTS_DIR, pid, key, "latest.txt")
    if not os.path.exists(path):
        return None
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(
            timespec="seconds")
    except OSError:
        return None


def prune_dated(target_dir, keep=12):
    """保留最近 keep 个日期存档，避免快照目录（已入库 git）无限膨胀。"""
    dated = [f for f in os.listdir(target_dir)
             if re.match(r"\d{4}-\d{2}-\d{2}\.txt$", f)]
    dated.sort(reverse=True)
    for old in dated[keep:]:
        try:
            os.remove(os.path.join(target_dir, old))
        except OSError:
            pass


def prune_orphan_snapshots(policies):
    """删除已不再监控的目标的快照目录。

    活跃目标按**配置**（policies/{id}.json 展开出的监控目标）判定，而不是按本轮状态：
    本轮被跳过的产品（例如 --no-browser 下的浏览器目标、monitor=false）
    在状态里可能没有 targets，若据此判定就会把仍在监控的快照当成孤儿删掉——
    快照是检测→核实回路唯一的持久历史，删掉等于让历史无法 diff。
    """
    if not os.path.isdir(SNAPSHOTS_DIR):
        return 0
    active = set()
    for pid, policy in policies.items():
        if not isinstance(policy, dict) or policy.get("monitor") is False:
            continue
        for spec in collect_target_specs(policy):
            active.add((pid, spec["key"]))
    removed = 0
    for pid in os.listdir(SNAPSHOTS_DIR):
        pid_dir = os.path.join(SNAPSHOTS_DIR, pid)
        if not os.path.isdir(pid_dir):
            continue
        for key in os.listdir(pid_dir):
            key_dir = os.path.join(pid_dir, key)
            if not os.path.isdir(key_dir):
                continue
            if (pid, key) not in active:
                shutil.rmtree(key_dir)
                removed += 1
        if not os.listdir(pid_dir):
            os.rmdir(pid_dir)
    return removed


def compute_hash(normalized_text):
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def compute_text_hash(text):
    """extract_text → normalize_text → compute_hash 的组合，供去噪一致性自检使用。"""
    return compute_hash(normalize_text(text))


def safe_fetch_url(url, resolve_dns=True):
    try:
        parsed = urlparse(str(url))
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    try:
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".local"):
        return False
    if not resolve_dns:
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True

    addresses = []
    lookup_done = threading.Event()

    def lookup():
        try:
            addresses.extend(socket.getaddrinfo(host, None))
        except socket.gaierror:
            pass
        finally:
            lookup_done.set()

    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    if not lookup_done.wait(timeout=3):
        return False
    if not addresses:
        return False
    for address in addresses:
        try:
            if not ipaddress.ip_address(address[4][0]).is_global:
                return False
        except ValueError:
            return False
    return True


def fetch_url(url, etag=None, last_modified=None, timeout=30):
    """带条件请求的抓取。返回 (response, was_304)。

    超时拆成 (连接, 读取)：连接超时单独收紧到 CONNECT_TIMEOUT_CAP。
    域名完全不可达时（受限网络下的境外政策站点），requests 会按解析出的每个
    地址依次连接，若沿用整体 timeout，单个目标可能耗掉数分钟——3 个 Gemini
    目标就能吃掉一轮监控的大部分时间预算。连接快速失败后由重试逻辑统一判定。
    """
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    connect_timeout = min(CONNECT_TIMEOUT_CAP, timeout)
    current_url = url
    for _ in range(6):
        if not safe_fetch_url(current_url):
            raise requests.exceptions.InvalidURL("仅允许解析到公网地址的 HTTPS URL")
        request_headers = headers if current_url == url else {"User-Agent": USER_AGENT}
        resp = requests.get(current_url, timeout=(connect_timeout, timeout),
                            headers=request_headers, allow_redirects=False, stream=True)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise requests.exceptions.InvalidURL("重定向响应缺少 Location")
            current_url = urljoin(current_url, location)
            resp.close()
            continue
        if resp.status_code == 304:
            resp.close()
            return resp, True
        resp.raise_for_status()
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                resp.close()
                raise requests.exceptions.ContentDecodingError("响应正文超过大小限制")
            chunks.append(chunk)
        resp._content = b"".join(chunks)
        resp._content_consumed = True
        return resp, False
    raise requests.exceptions.TooManyRedirects("重定向次数超过限制")


def extract_pdf_text(content):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


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
    content = getattr(resp, "content", b"") or b""
    if "application/pdf" in content_type or content.startswith(b"%PDF-"):
        return extract_pdf_text(content)

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


def fetch_with_retry(url, etag, last_modified, timeout, budget=RETRY_BUDGET_SECONDS):
    """网络类错误（超时/连接失败）按指数退避重试；HTTP 4xx/5xx 不重试直接抛出。

    429 Too Many Requests：等待 Retry-After 或退避后重试。

    budget 为该目标的墙钟重试预算：域名整体不可达时（例如受限网络访问不到
    境外政策站点），requests 会按解析出的每个地址依次连接，单次尝试可能耗时
    上分钟。超出预算即停止重试并按失败处理，避免单个死目标吃掉整轮时间。
    """
    last_exc = None
    started = time.monotonic()
    for attempt in range(RETRY_TIMES + 1):
        try:
            return fetch_url(url, etag, last_modified, timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt >= RETRY_TIMES:
                break
            if time.monotonic() - started > budget:
                print(f"         已超出单目标重试预算（{budget}s），放弃重试")
                break
            wait = RETRY_BACKOFF * (attempt + 1)
            print(f"         请求失败（{e.__class__.__name__}），{wait}s 后重试…")
            time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt < RETRY_TIMES:
                retry_after = e.response.headers.get("Retry-After")
                wait = (min(int(retry_after), MAX_RETRY_AFTER_SECONDS)
                        if retry_after and retry_after.isdigit()
                        else RETRY_BACKOFF * (attempt + 2))
                print(f"         被限流（429），{wait}s 后重试…")
                time.sleep(wait)
                continue
            raise
    raise last_exc


def pick_longest_render(renders):
    """从多次渲染结果里挑正文最长的一次。

    renders 为 [(可见文本长度, html), ...]。残缺渲染（只出了一半正文或只剩页脚壳）
    不得进基线——否则哈希会长期漂移，每轮都误报"政策可能已更新"。
    """
    best_html, best_len = None, -1
    for nlen, html in renders:
        if nlen > best_len:
            best_len, best_html = nlen, html
    return best_html, best_len


def fetch_browser(url, timeout=30, wait_selector=None):
    """无头浏览器抓取，用于 Cloudflare 等反爬挑战页。

    仅当目标 fetch_method=browser 时调用，依赖可选 playwright（不在主依赖中）。
    返回 (html, was_304)，was_304 恒为 False（浏览器路径不做条件请求）。

    wait_selector：可选 CSS 选择器，等待该节点出现（异步渲染正文容器），
        命中即认为已渲染，可显著缩短 SPA 文档页的抓取耗时。

    可选增强：设置环境变量 OPENAI_CF_CLEARANCE 可导入已在真人浏览器通过
    "Verify you are human" 后得到的 cf_clearance 令牌，大幅提升通过率。
    注意该令牌绑 IP + User-Agent 且短时效，CI（数据中心 IP）通常不保证可用，
    主要供本地人工补抓。未设置时也能跑，只是更可能被重新挑战。
    """
    if not safe_fetch_url(url):
        raise RuntimeError("仅允许抓取解析到公网地址的 HTTPS URL")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "fetch_method=browser 需要 playwright，请先执行："
            "pip install playwright && playwright install chromium"
        )

    cf_token = os.environ.get("OPENAI_CF_CLEARANCE")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(user_agent=USER_AGENT, locale="zh-CN")
        if cf_token:
            ctx.add_cookies([{
                "name": "cf_clearance",
                "value": cf_token,
                "domain": ".openai.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }])
        page = ctx.new_page()

        def safe_route(route):
            if safe_fetch_url(route.request.url, resolve_dns=False):
                route.continue_()
            else:
                route.abort()

        page.route("**/*", safe_route)
        # SPA 文档页正文为异步渲染，单次抓取偶发只渲染一半或只剩页脚壳（如 trae/tob
        # 出现过正文缺失、仅剩 footer 的坏渲染；support.google.com 帮助页实测同页
        # 出现过 9500 与 56422 字符两种结果）。因此重试固定次数，并始终返回
        # 正文最长（最完整）的那次，避免残缺页污染哈希、造成永久误报"已变更"。
        best_html, best_len = None, -1
        renders = []
        for attempt in range(BROWSER_RENDER_ATTEMPTS):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except Exception:
                pass  # 导航超时/跳转异常也尽量取已渲染内容
            if wait_selector:
                # 目标级配置了正文容器：等到该节点出现即认为已渲染
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout * 1000, state="attached")
                except Exception:
                    pass  # 等不到也继续取已渲染内容，交由 min_body_chars 判定
            try:
                # 等真实正文出现（挑战页正文极短）；超时也继续，交由 MIN_BODY_CHARS 判 suspicious
                page.wait_for_function(
                    "document.body && document.body.innerText.length > 800",
                    timeout=timeout * 1000,
                )
            except Exception:
                pass
            try:
                # 给懒加载章节一点时间，再取正文长度判断渲染完整度
                page.wait_for_timeout(600)
            except Exception:
                pass
            inner = ""
            try:
                inner = page.evaluate("document.body ? document.body.innerText : ''")
            except Exception:
                pass
            nlen = len(normalize_text(inner)) if inner else 0
            renders.append((nlen, page.content()))
            # 不做"长度够大就提前退出"的优化：各页面完整正文长度差异极大
            # （support.google.com 帮助页完整 5.6 万字符，文档站协议页 1.2 万），
            # 固定阈值会让渲染未完成的中间态（实测同页 9500 vs 完整 56422）被当成
            # 最终结果写进基线，之后每轮都误报 changed。三次 goto 复用同一个 browser，
            # 额外成本远小于误报代价。
        best_html, best_len = pick_longest_render(renders)
        browser.close()
        return best_html, False


FETCH_CONFIG_FIELDS = ("fetch_method", "content_selector", "wait_for_selector", "min_body_chars")
SUPPORTED_FETCH_METHODS = ("requests", "browser")


def resolve_fetch_config(policy, target_source=None):
    """合并产品级与目标级抓取配置。

    优先级：目标级（targets.main / versions[key] / sources[] 条目）> 产品级 > 全局默认。
    允许在单个来源上覆盖抓取方式、正文选择器、渲染等待选择器和正文下限，
    避免"一个站点需要浏览器抓取"时把同产品所有目标都切成 browser。
    """
    def pick(field, default=None):
        value = None
        if isinstance(target_source, dict):
            value = target_source.get(field)
        if value is None and isinstance(policy, dict):
            value = policy.get(field)
        return default if value is None else value

    method = str(pick("fetch_method", "requests") or "requests")
    min_chars = pick("min_body_chars", MIN_BODY_CHARS)
    try:
        min_chars = int(min_chars)
    except (TypeError, ValueError):
        min_chars = MIN_BODY_CHARS
    if min_chars < 0:
        min_chars = MIN_BODY_CHARS
    return {
        "method": method,
        "min_body_chars": min_chars,
        "content_selector": str(pick("content_selector", "") or "").strip() or None,
        "wait_for_selector": str(pick("wait_for_selector", "") or "").strip() or None,
    }


def collect_target_specs(policy):
    """汇总一个产品的监控目标及其抓取配置，按 URL 去重。

    返回 [{key, url, method, min_body_chars, content_selector, wait_for_selector}, ...]
    """
    specs = []
    seen = set()

    def add_target(key, url, source=None):
        if not url or url == "待核实" or url in seen:
            return
        config = resolve_fetch_config(policy, source)
        specs.append({
            "key": key,
            "url": url,
            "method": config["method"],
            "min_body_chars": config["min_body_chars"],
            "content_selector": config["content_selector"],
            "wait_for_selector": config["wait_for_selector"],
        })
        seen.add(url)

    # main 目标的 URL（policy_url）就在顶层，天然没有内层对象可挂配置。
    # targets.main 补上这个唯一缺失的载体，使"每个目标都能独立配置"没有例外；
    # 顶层字段继续生效（resolve_fetch_config 里目标级优先），既有数据文件无需改动。
    targets_cfg = policy.get("targets") or {}
    main_cfg = targets_cfg.get("main") if isinstance(targets_cfg, dict) else None
    add_target("main", policy.get("policy_url", ""), main_cfg)
    versions = policy.get("versions") or {}
    if not isinstance(versions, dict):
        versions = {}
    for key in ("toc", "tob"):
        version = versions.get(key) or {}
        link = version.get("policy_link", "") if isinstance(version, dict) else ""
        add_target(key, link, version)

    sources = policy.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict) or source.get("monitored") is False:
            continue
        raw_id = str(source.get("id") or index)
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", raw_id)[:48] or str(index)
        key = "source_" + safe_id
        suffix = 2
        while key in {spec["key"] for spec in specs}:
            key = "source_%s_%d" % (safe_id, suffix)
            suffix += 1
        add_target(key, source.get("url", ""), source)
    return specs


def collect_targets(policy):
    """兼容旧接口：只返回 [(key, url), ...]。"""
    return [(spec["key"], spec["url"]) for spec in collect_target_specs(policy)]


def base_target_result(url, prev_target, **extra):
    """构造目标级结果，继承跨轮次稳定字段（上次变更时间、最后成功时间）。"""
    result = {
        "url": url,
        "hash_scheme": HASH_SCHEME,
        "last_checked": datetime.datetime.now().isoformat(),
        "last_changed_date": prev_target.get("last_changed_date"),
        "last_good_at": prev_target.get("last_good_at"),
        "health": "ok",
    }
    result.update(extra)
    result.setdefault("health", "ok")
    return result


def health_for_failure(baseline_ready, blocked=False):
    """抓取失败时的健康状态：能兜住上次快照则降级，否则无基线。"""
    if blocked:
        return "blocked"
    return "degraded" if baseline_ready else "no_baseline"


def check_target(pid, name, key, url, prev_target, timeout, method="requests", config=None):
    """检查单个目标 URL，返回该目标的状态明细。

    method="requests"（默认）：普通 HTTP 抓取，适用绝大多数站点；
    method="browser"：改用无头浏览器抓取（应对 Cloudflare 等反爬挑战页），
        仅当该目标配置 fetch_method=browser 时启用，依赖可选 playwright。

    config：目标级抓取配置（min_body_chars / content_selector / wait_for_selector）。
    返回结果同时包含两套正交语义：
        status —— 政策内容状态（ok/changed/failed/suspicious/skipped）
        health —— 抓取健康状态（ok/initialized/rebaselined/degraded/no_baseline/blocked）
    """
    if not isinstance(prev_target, dict):
        prev_target = {}
    config = config or {}
    min_body_chars = config.get("min_body_chars") or MIN_BODY_CHARS
    content_selector = config.get("content_selector")
    wait_for_selector = config.get("wait_for_selector")
    label = TARGET_LABELS.get(key, key)
    prev_hash = prev_target.get("current_hash") if prev_target.get("hash_scheme") == HASH_SCHEME else None
    baseline = load_baseline_text(pid, key)
    baseline_ready = bool(baseline and baseline.strip())
    if baseline_ready and not prev_target.get("last_good_at"):
        # 旧状态文件没有该字段时，用快照保存时间回填，避免"已保留上次快照"却显示"从未成功"
        saved_at = baseline_saved_at(pid, key)
        if saved_at:
            prev_target = dict(prev_target, last_good_at=saved_at)
    scheme_matches = prev_target.get("hash_scheme") == HASH_SCHEME
    url_matches = prev_target.get("url") == url
    source_changed = bool(prev_target and not url_matches)
    scheme_changed = bool(prev_target and not scheme_matches)
    had_cached_response = bool(
        prev_target.get("current_hash") or prev_target.get("content_etag")
        or prev_target.get("content_last_modified") or prev_target.get("status") in ("ok", "changed")
    )
    missing_baseline = bool(prev_target and had_cached_response and not baseline_ready)
    can_use_validators = bool(
        baseline_ready and scheme_matches and url_matches
        and (prev_target.get("content_etag") or prev_target.get("content_last_modified"))
    )
    etag = prev_target.get("content_etag") if can_use_validators else None
    last_modified = prev_target.get("content_last_modified") if can_use_validators else None
    if scheme_changed:
        print(f"  [基线] {name} ({pid}·{label}): 哈希算法已升级，重新记录基线")
    if source_changed:
        print(f"  [基线] {name} ({pid}·{label}): 监控 URL 已变更，重新核实并记录基线")
    if missing_baseline:
        print(f"  [基线] {name} ({pid}·{label}): 本地基线缺失，禁用条件请求")

    raw_html, was_304, resp = None, False, None
    if method == "browser":
        try:
            raw_html, was_304 = fetch_browser(url, timeout, wait_selector=wait_for_selector)
            print(f"  [浏览器] {name} ({pid}·{label}): 已用无头浏览器抓取")
        except Exception as e:
            print(f"  [失败] {name} ({pid}·{label}): 浏览器抓取失败 - {e}")
            print(f"         URL: {url}")
            return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                      health=health_for_failure(baseline_ready),
                                      health_reason="browser_error",
                                      message=f"浏览器抓取失败：{e}")

    try:
        now = datetime.datetime.now().isoformat()

        if method != "browser":
            resp, was_304 = fetch_with_retry(url, etag, last_modified, timeout)

            if was_304:
                if not baseline_ready or not scheme_matches or not url_matches:
                    return base_target_result(
                        url, prev_target, current_hash=None, status="suspicious",
                        health="no_baseline", health_reason="missing_baseline",
                        message="收到 304，但本地没有可验证的基线，已拒绝接受条件响应",
                        last_checked=now,
                    )
                current_hash = prev_hash or compute_hash(baseline)
                print(f"  [OK]   {name} ({pid}·{label}): 内容未变化（304 Not Modified）")
                return base_target_result(
                    url, prev_target, current_hash=current_hash, status="ok",
                    content_etag=etag, content_last_modified=last_modified,
                    message="内容未变化（304 Not Modified）", last_checked=now,
                    last_good_at=now,
                )

            raw_html = response_text(resp)

        raw_text = extract_text(raw_html, content_selector=content_selector)
        normalized = normalize_text(raw_text)
        current_hash = compute_hash(normalized)

        if len(normalized) < min_body_chars:
            reason = "empty_body" if len(normalized) < 50 else "render_required"
            kept = "，已保留上次有效快照" if baseline_ready else "，无可验证基线"
            print(f"  [可疑] {name} ({pid}·{label}): 正文仅 {len(normalized)} 字符，"
                  f"疑似 JS 渲染/反爬空壳{kept}")
            return base_target_result(
                url, prev_target, current_hash=prev_hash, status="suspicious",
                health=health_for_failure(baseline_ready), health_reason=reason,
                message=f"抓取正文过短（{len(normalized)} 字符 < {min_body_chars}），"
                        f"疑似 JS 渲染或反爬{kept}",
                last_checked=now,
            )

        if source_changed:
            save_snapshot(pid, key, raw_text, archived=True)
            result = base_target_result(
                url, prev_target, current_hash=current_hash, status="changed",
                message="⚠️ 监控 URL 已变更，需重新核实新来源", last_changed_date=now,
                last_good_at=now,
            )
        elif baseline is None:
            print(f"  [新增] {name} ({pid}·{label}): 首次记录基线")
            save_snapshot(pid, key, raw_text, archived=True)
            if missing_baseline:
                result = base_target_result(
                    url, prev_target, current_hash=current_hash, status="suspicious",
                    health="rebaselined", health_reason="missing_baseline",
                    message="本地基线缺失，已重新抓取并重建基线，需人工确认", last_checked=now,
                    last_good_at=now,
                )
            else:
                result = base_target_result(
                    url, prev_target, current_hash=current_hash, status="ok",
                    health="initialized", health_reason="first_baseline",
                    message="首次检查，已记录基线（下一轮开始比较）",
                    last_changed_date=None, last_good_at=now,
                )
        elif scheme_changed:
            save_snapshot(pid, key, raw_text, archived=False)
            result = base_target_result(url, prev_target, current_hash=current_hash, status="ok",
                                        health="rebaselined", health_reason="hash_scheme_upgrade",
                                        message="哈希方案已更新，已重建基线", last_good_at=now)
        elif baseline == normalized:
            result = base_target_result(url, prev_target, current_hash=current_hash, status="ok",
                                        message="内容未变化", last_good_at=now)
        else:
            print(f"  [⚠️]   {name} ({pid}·{label}): 政策可能已更新！待核实")
            print(f"         URL: {url}")
            save_snapshot(pid, key, raw_text, archived=True)
            message = "⚠️ 政策可能已更新，待核实"
            health, health_reason = "ok", None
            if scheme_changed:
                message = "⚠️ 正文发生变化（同时发生哈希方案升级），待核实"
                health, health_reason = "rebaselined", "hash_scheme_upgrade"
            result = base_target_result(url, prev_target, current_hash=current_hash, status="changed",
                                        message=message, last_changed_date=now, last_good_at=now,
                                        health=health, health_reason=health_reason)

        result["fetch_method"] = method
        if method != "browser" and resp is not None:
            result["content_etag"] = resp.headers.get("ETag")
            result["content_last_modified"] = resp.headers.get("Last-Modified")
        else:
            result["content_etag"] = None
            result["content_last_modified"] = None
        return result

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        print(f"  [失败] {name} ({pid}·{label}): 请求失败（重试后仍超时/连接失败）- {e.__class__.__name__}")
        print(f"         URL: {url}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  health=health_for_failure(baseline_ready), health_reason="network",
                                  message=f"检查失败：请求异常 - {e.__class__.__name__}")
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "?"
        blocked = status_code in (401, 403, 405, 429, 451)
        print(f"  [失败] {name} ({pid}·{label}): HTTP {status_code} 错误")
        print(f"         URL: {url}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  health=health_for_failure(baseline_ready, blocked=blocked),
                                  health_reason="blocked" if blocked else "http_error",
                                  message=f"检查失败：HTTP {status_code} 错误 - {e}")
    except requests.exceptions.RequestException as e:
        print(f"  [失败] {name} ({pid}·{label}): 请求异常 - {e}")
        return base_target_result(url, prev_target, current_hash=prev_hash, status="failed",
                                  health=health_for_failure(baseline_ready), health_reason="request",
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


def aggregate_targets(target_results):
    """把目标级状态聚合为产品级状态与摘要文案（changed > failed > suspicious > ok）。"""
    statuses = [r.get("status", "ok") for r in target_results.values()]
    if not statuses:
        return "ok", "内容未变化", 0
    if "changed" in statuses:
        status = "changed"
    elif "failed" in statuses:
        status = "failed"
    elif "suspicious" in statuses:
        status = "suspicious"
    else:
        status = "ok"

    changed_keys = [k for k, r in target_results.items() if r.get("status") == "changed"]
    failed_keys = [k for k, r in target_results.items() if r.get("status") == "failed"]
    suspicious_keys = [k for k, r in target_results.items() if r.get("status") == "suspicious"]
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

    unhealthy = [k for k, r in target_results.items()
                 if r.get("health") in HEALTH_QUEUED_STATES]
    if unhealthy:
        summary += f"（{len(unhealthy)} 个目标抓取降级，已保留上次有效快照）"
    return status, summary, len(unhealthy)


def aggregate_health(target_results):
    """产品级抓取健康状态：取最严重的一个（blocked > no_baseline > degraded）。"""
    worst, worst_score = "ok", 0
    for result in target_results.values():
        health = result.get("health", "ok")
        score = HEALTH_SEVERITY.get(health, 0)
        if score > worst_score:
            worst, worst_score = health, score
    return worst


def merge_partial_product(prev_info, new_info):
    """局部重试时把新结果合并回上次状态：只覆盖被检查的目标，其余目标沿用上次结果。"""
    merged = json.loads(json.dumps(prev_info)) if isinstance(prev_info, dict) else {}
    merged_targets = merged.get("targets")
    if not isinstance(merged_targets, dict):
        merged_targets = {}
    for key, target in (new_info.get("targets") or {}).items():
        merged_targets[key] = target
    merged["targets"] = merged_targets
    merged["name"] = new_info.get("name", merged.get("name"))
    merged["url"] = new_info.get("url") or merged.get("url")
    merged["last_checked"] = new_info.get("last_checked", merged.get("last_checked"))
    status, summary, unhealthy = aggregate_targets(merged_targets)
    merged["status"] = status
    merged["message"] = summary
    merged["health"] = aggregate_health(merged_targets)
    merged["health_issues"] = unhealthy
    return merged


def check_product(pid, policy, prev_entry, timeout, delay, no_browser=False, only_keys=None):
    """检查一个产品的全部（或指定）监控目标，返回聚合后的产品级状态。"""
    name = policy.get("name", pid)
    specs = collect_target_specs(policy)
    if only_keys:
        wanted = set(only_keys)
        specs = [spec for spec in specs if spec["key"] in wanted]
    if not specs:
        print(f"  [跳过] {name} ({pid}): URL 为空、待核实或未匹配 --only 目标")
        return {"name": name, "status": "skipped", "health": "ok", "health_issues": 0,
                "message": "URL 为空或待核实，跳过检查",
                "last_checked": datetime.datetime.now().isoformat()}

    for spec in specs:
        if spec["method"] not in SUPPORTED_FETCH_METHODS:
            return {"name": name, "status": "failed", "health": "blocked", "health_issues": 1,
                    "message": f"目标 {spec['key']} 配置了不支持的抓取方式：{spec['method']!r}",
                    "last_checked": datetime.datetime.now().isoformat()}

    if policy.get("monitor") is False:
        # 占位条目（无公开政策页 / 政策 URL 指向产品首页）：不抓取，避免持续误报
        return {"name": name, "status": "skipped", "health": "ok", "health_issues": 0,
                "message": "该产品已标记为不监控（无独立公开政策页）",
                "last_checked": datetime.datetime.now().isoformat()}

    prev_targets = migrate_prev_targets(prev_entry)

    if no_browser:
        # 未安装 playwright 的环境：只跳过需浏览器抓取的目标，其余目标照常检查
        kept = [spec for spec in specs if spec["method"] != "browser"]
        if not kept:
            # 全部目标都要浏览器：沿用上次结果而不是清空——否则本地无浏览器的一次运行
            # 会把 CI 建立的监控覆盖从状态文件里抹掉（total_targets 缩水、覆盖被低估）
            spec_keys = {spec["key"] for spec in specs}
            preserved = {}
            for key in spec_keys:
                previous = prev_targets.get(key)
                if isinstance(previous, dict):
                    kept_target = dict(previous)
                    kept_target["skipped_this_run"] = True
                    preserved[key] = kept_target
            print(f"  [跳过] {name} ({pid}): 全部目标需浏览器抓取，已被 --no-browser 跳过"
                  f"（沿用上次结果，{len(preserved)} 个目标）")
            return {
                "name": name,
                "status": "skipped",
                "health": aggregate_health(preserved),
                "health_issues": sum(1 for t in preserved.values()
                                     if t.get("health") in HEALTH_QUEUED_STATES),
                "url": specs[0]["url"],
                "message": "全部目标需浏览器抓取，已被 --no-browser 跳过（沿用上次结果）",
                "last_checked": datetime.datetime.now().isoformat(),
                "targets": preserved,
            }
        if len(kept) != len(specs):
            skipped = "、".join(TARGET_LABELS.get(s["key"], s["key"])
                                for s in specs if s["method"] == "browser")
            print(f"  [跳过] {name} ({pid}): 浏览器抓取已禁用（--no-browser），跳过 {skipped}")
        specs = kept

    target_results = {}
    for i, spec in enumerate(specs):
        target_results[spec["key"]] = check_target(
            pid, name, spec["key"], spec["url"], prev_targets.get(spec["key"], {}),
            timeout, method=spec["method"],
            config={k: spec[k] for k in
                    ("min_body_chars", "content_selector", "wait_for_selector")},
        )
        if i < len(specs) - 1:
            time.sleep(delay)

    status, summary, unhealthy = aggregate_targets(target_results)
    return {
        "name": name,
        "status": status,
        "health": aggregate_health(target_results),
        "health_issues": unhealthy,
        "url": specs[0]["url"],
        "message": summary,
        "last_checked": datetime.datetime.now().isoformat(),
        "targets": target_results,
    }


def atomic_write_json(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def load_pending_items():
    if not os.path.exists(PENDING_FILE):
        return {}
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError("无法读取待核实队列 %s：%s" % (PENDING_FILE, e))
    items = data.get("items", {}) if isinstance(data, dict) else None
    if not isinstance(items, dict):
        raise ValueError("待核实队列格式错误：items 必须是对象")
    return items


def reapply_pending_alerts(products, pending_items):
    restored = 0
    for item in pending_items.values():
        if not isinstance(item, dict):
            continue
        pid = item.get("pid")
        key = item.get("key")
        product = products.get(pid)
        targets = (product or {}).get("targets") or {}
        target = targets.get(key)
        if not target or target.get("status") != "ok":
            continue
        target["status"] = "changed"
        target["message"] = "此前检测到政策变化，仍待人工核实"
        target["last_changed_date"] = target.get("last_changed_date") or datetime.datetime.now().isoformat()
        product["status"] = "changed"
        product["message"] = "⚠️ 政策可能已更新，待人工核实"
        restored += 1
    return restored


def update_pending_verification(products):
    """合并式维护"待核实队列"（检测→核实的持久交接物，取代已移除的自动 Issue）。

    products 为本次状态里的产品映射（形如 {pid: info}），与 main 中保持一致。

    - 本轮检测为 changed 的目标入队（首次出现记 first_seen，之后只更新 last_seen）；
    - 已从当前监控目标中移除的历史项自动清理；
    - 只收 changed，failed/suspicious 属监控异常，不入此队列（由 update_status 单独体现）。
    """
    now = datetime.datetime.now().isoformat()
    existing = load_pending_items()
    active_keys = set()
    for pid, info in products.items():
        for key in (info.get("targets") or {}):
            active_keys.add(f"{pid}:{key}")
    items = {
        pk: item for pk, item in existing.items()
        if pk in active_keys and isinstance(item, dict)
    }
    for pid, info in products.items():
        if not isinstance(info, dict):
            continue
        for key, target in (info.get("targets") or {}).items():
            pk = f"{pid}:{key}"
            if pk in items:
                items[pk]["name"] = info.get("name", pid)
                items[pk]["url"] = target.get("url", "")
                items[pk]["label"] = TARGET_LABELS.get(key, key)
    for pid, info in products.items():
        if not isinstance(info, dict) or info.get("status") != "changed":
            continue
        name = info.get("name", pid)
        for key, target in (info.get("targets") or {}).items():
            if target.get("status") != "changed":
                continue
            pk = f"{pid}:{key}"
            old = items.get(pk) or {}
            items[pk] = {
                "pid": pid,
                "name": name,
                "key": key,
                "label": TARGET_LABELS.get(key, key),
                "url": target.get("url", ""),
                "status": "changed",
                "first_seen": old.get("first_seen", now),
                "last_seen": now,
            }
    atomic_write_json(PENDING_FILE, {"updated_at": now, "items": items})
    return items


def load_health_items():
    """读取上一轮健康队列；文件损坏时降级为空队列（健康队列可由状态完全重建）。"""
    if not os.path.exists(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        print(f"  [警告] 健康队列读取失败（{e}），本轮按空队列重建")
        return {}
    items = data.get("items", {}) if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def update_monitor_health(products):
    """独立"抓取健康队列"：跟踪监控可用性，与"政策变化"待核实队列分离。

    与 pending_verification 的分工：
      - pending：正文确实变了，等人核实内容差异；
      - health：本轮抓取不可信（被拦截 / 无基线 / 降级），等人修抓取配置。
    两者互不覆盖：政策可能没变，但抓取已经坏了，首页必须能同时看清这两种情况。

    products 为本次状态里的产品映射（形如 {pid: info}）。
    """
    now = datetime.datetime.now().isoformat()
    existing = load_health_items()
    items = {}
    for pid, info in products.items():
        if not isinstance(info, dict):
            continue
        for key, target in (info.get("targets") or {}).items():
            health = target.get("health", "ok")
            if health not in HEALTH_QUEUED_STATES:
                continue
            pk = f"{pid}:{key}"
            old = existing.get(pk) if isinstance(existing.get(pk), dict) else {}
            items[pk] = {
                "pid": pid,
                "name": info.get("name", pid),
                "key": key,
                "label": TARGET_LABELS.get(key, key),
                "url": target.get("url", ""),
                "health": health,
                "health_reason": target.get("health_reason"),
                "status": target.get("status"),
                "message": target.get("message", ""),
                "last_checked": target.get("last_checked"),
                "last_good_at": target.get("last_good_at"),
                # 连续不健康轮次：恢复后条目会被清除，下次再坏重新计数
                "consecutive_runs": (old.get("consecutive_runs", 0) + 1) if old else 1,
                "first_seen": old.get("first_seen", now),
                "last_seen": now,
                "next_action": HEALTH_ACTIONS.get(health, "检查抓取配置并重试"),
            }
    # 队列完全由当前状态重建：已恢复或已下线监控的目标自动消失
    atomic_write_json(HEALTH_FILE, {"updated_at": now, "items": items})
    return items


def main():
    parser = argparse.ArgumentParser(description="AI 政策更新监控")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="相邻请求间隔秒数（礼貌抓取，默认 1.5）")
    parser.add_argument("--timeout", type=int, default=30,
                        help="单次请求超时秒数（默认 30）")
    parser.add_argument("--no-browser", action="store_true",
                        help="禁用无头浏览器抓取（fetch_method=browser 的产品将被跳过），"
                             "用于未安装 playwright 的 CI 环境")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="存在产品检查失败时返回非零退出码")
    parser.add_argument("--products", default="",
                        help="仅检查指定产品（逗号分隔 pid，如 gemini,minimax）；"
                             "未检查产品沿用上次状态")
    parser.add_argument("--only", default="",
                        help="仅检查指定目标，格式 pid:key（可逗号分隔，如 gemini:toc,minimax:main）")
    parser.add_argument("--no-prune", action="store_true",
                        help="不清理已不再监控的孤儿快照目录")
    args = parser.parse_args()

    print("=" * 60)
    print("AI 政策更新监控脚本")
    print("运行时间：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print(f"哈希方案：{HASH_SCHEME}（正文文本归一化，按配置来源逐条监控）")
    print("=" * 60)

    pids = load_product_ids()
    prev_status = load_previous_status().get("products", {})

    # 局部重试：只重跑指定产品/目标，其余结果原样继承，避免为重试一个站点重跑全量
    selected_pids = []
    only_map = {}

    def select(pid):
        if pid not in selected_pids:
            selected_pids.append(pid)

    if args.products:
        for raw in args.products.split(","):
            pid = raw.strip()
            if not pid:
                continue
            if pid not in pids:
                print(f"[错误] 未知产品 id：{pid!r}")
                return 2
            select(pid)
    if args.only:
        for token in args.only.split(","):
            token = token.strip()
            if not token:
                continue
            if ":" not in token:
                print(f"[错误] --only 需要 pid:key 格式，收到 {token!r}")
                return 2
            pid, key = token.split(":", 1)
            if pid not in pids:
                print(f"[错误] 未知产品 id：{pid!r}")
                return 2
            only_map.setdefault(pid, set()).add(key)
            select(pid)
    partial = bool(args.products or args.only)
    if not partial:
        selected_pids = list(pids)
    else:
        # 保持与 products.json 一致的顺序，便于和全量结果对照
        selected_pids = [pid for pid in pids if pid in set(selected_pids)]
    if partial:
        new_status = {pid: json.loads(json.dumps(info))
                      for pid, info in prev_status.items() if pid in set(pids)}
        for pid in pids:
            new_status.setdefault(pid, {"name": pid, "status": "skipped",
                                        "health": "ok", "health_issues": 0,
                                        "message": "本轮未检查（--products/--only）",
                                        "last_checked": datetime.datetime.now().isoformat()})
        target_count = sum(len(v) for v in only_map.values()) or "全部"
        print(f"局部重试：{len(selected_pids)} 个产品 / {target_count} 个目标，"
              f"其余沿用上次状态")
    else:
        new_status = {}
    changed_count = failed_count = skipped_count = suspicious_count = 0
    policies = {}

    print(f"\n共 {len(pids)} 个产品需要检查（本次检查 {len(selected_pids)} 个）\n")

    for i, pid in enumerate(selected_pids):
        policy = load_policy(pid)
        policies[pid] = policy
        prev = prev_status.get(pid, {})
        only_keys = only_map.get(pid)
        if not policy:
            new_status[pid] = {"name": pid, "status": "failed", "health": "no_baseline",
                               "health_issues": 1, "message": "数据文件缺失或不是合法 JSON",
                               "last_checked": datetime.datetime.now().isoformat()}
            continue
        result = check_product(pid, policy, prev, args.timeout, args.delay,
                               no_browser=args.no_browser, only_keys=only_keys)
        if partial and isinstance(prev, dict) and prev.get("targets"):
            result = merge_partial_product(prev, result)
        new_status[pid] = result

        if i < len(selected_pids) - 1:
            time.sleep(args.delay)

    try:
        pending_items = update_pending_verification(new_status)
    except (OSError, ValueError) as e:
        print(f"[错误] {e}")
        return 1
    restored_count = reapply_pending_alerts(new_status, pending_items)
    if restored_count:
        print(f"  [待核实] 恢复了 {restored_count} 个未解决告警，避免被后续 304 清除")

    current_ids = set(pids)
    new_status = {pid: info for pid, info in new_status.items() if pid in current_ids}
    if not partial and not args.no_prune:
        # 按配置（而非本轮状态）判定活跃目标，避免把被跳过的产品的快照误删
        all_policies = {pid: load_policy(pid) for pid in pids}
        orphan_count = prune_orphan_snapshots(all_policies)
        if orphan_count:
            print(f"  [清理] 移除了 {orphan_count} 个不再监控的快照目录")
    health_items = update_monitor_health(new_status)
    total_targets = sum(len(info.get("targets") or {}) for info in new_status.values())
    changed_count = sum(info.get("status") == "changed" for info in new_status.values())
    failed_count = sum(info.get("status") == "failed" for info in new_status.values())
    suspicious_count = sum(info.get("status") == "suspicious" for info in new_status.values())
    skipped_count = sum(info.get("status") == "skipped" for info in new_status.values())
    pending_count = len(pending_items)
    blocked_count = sum(item.get("health") == "blocked" for item in health_items.values())
    degraded_count = sum(item.get("health") == "degraded" for item in health_items.values())
    no_baseline_count = sum(item.get("health") == "no_baseline" for item in health_items.values())

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
            "health_issues": len(health_items),
            "health_blocked": blocked_count,
            "health_degraded": degraded_count,
            "health_no_baseline": no_baseline_count,
            "partial_run": partial,
        },
        "products": new_status,
    }
    atomic_write_json(STATUS_FILE, status_data)

    print("\n" + "=" * 60)
    print("检查完成")
    print(f"  产品: {len(pids)}，监控目标: {total_targets}")
    print(f"  未变化: {len(pids) - changed_count - failed_count - suspicious_count - skipped_count}")
    print(f"  已变更: {changed_count}")
    print(f"  待核实队列: {pending_count} 项（详见 site/generated/pending_verification.json）")
    print(f"  失败:   {failed_count}")
    print(f"  可疑:   {suspicious_count}（正文疑似空壳，未记录基线）")
    print(f"  跳过:   {skipped_count}")
    print(f"  健康队列: {len(health_items)} 项（blocked {blocked_count} / 降级 {degraded_count} / "
          f"无基线 {no_baseline_count}，详见 site/generated/monitor_health.json）")
    print(f"  状态文件: {STATUS_FILE}")
    print("=" * 60)

    if changed_count == 0 and failed_count == len(pids) and pids and not partial:
        print("\n❌ 本轮全部产品检查失败：可能是网络/代理故障或 URL 大面积失效，请人工确认监控是否正常")

    if changed_count > 0:
        print(f"\n⚠️ 告警：检测到 {changed_count} 个产品政策可能已更新，请及时核实！")
        for pid, info in new_status.items():
            if info["status"] == "changed":
                for key, t in (info.get("targets") or {}).items():
                    if t.get("status") == "changed":
                        print(f"  - {pid}（{TARGET_LABELS.get(key, key)}）: {t['url']}")

    if health_items:
        print(f"\n🔧 以下 {len(health_items)} 个目标抓取降级（政策未变更，但监控数据不可信）：")
        for pk, item in sorted(health_items.items(), key=lambda kv: -HEALTH_SEVERITY.get(kv[1]["health"], 0)):
            print(f"  - {item['name']}（{pk}）[{item['health']}] 连续 {item['consecutive_runs']} 轮")
            print(f"    {item['message']}")
            print(f"    建议：{item['next_action']}")
        print(f"    可用 --only {sorted(health_items)[0]} 之类的命令单独重试")

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
                        elif "429" in msg:
                            reason = "429 Too Many Requests（被限流）"
                        elif "405" in msg:
                            reason = "405 Method Not Allowed（服务器不接受 GET 请求）"
                        elif "ConnectionError" in msg:
                            reason = "连接失败"
                        else:
                            reason = msg
                        print(f"  - {pid}（{TARGET_LABELS.get(key, key)}）: {reason}")
                        print(f"    URL: {t['url']}")
                        if t.get("last_good_at"):
                            print(f"    上次成功抓取: {t['last_good_at']}")

    if args.fail_on_error and failed_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
