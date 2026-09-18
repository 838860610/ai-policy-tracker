#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 辅助政策变更分析（第二层监控）。

功能：
  - 读取 site/generated/update_status.json，找出 status=changed 的产品
  - 对每个变更产品，对比新旧政策正文快照：
      新快照：site/generated/snapshots/{id}/{target}/latest.txt（本次检查抓取）
      旧快照：site/generated/snapshots/{id}/{target}/ 下除 latest.txt 外最新的日期存档，
              或从 git 历史取（site/generated/snapshots/ 已入 git 时）
  - 调用 LLM（OpenAI 兼容 API）对比新旧内容，提取关键变化点：
      - 训练数据政策是否变化
      - 退出/关闭机制是否变化
      - 数据留存期限是否变化
      - 其他关键条款变化
  - 生成结构化变更报告，写入 site/generated/change_reports/{id}_{date}.json
  - 输出 Markdown 摘要到 stdout（供 CI 嵌入 Issue 评论）
  - 无 API key 时降级为纯文本 diff，仍输出可读的变更报告

使用方法：
  # 分析所有变更产品（CI 中调用）
  .venv/bin/python scripts/analyze_changes.py

  # 只分析指定产品
  .venv/bin/python scripts/analyze_changes.py --product kimi

  # 自定义 LLM 端点（OpenAI 兼容）
  OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_MODEL=gpt-4o \
    .venv/bin/python scripts/analyze_changes.py

环境变量：
  OPENAI_API_KEY   - LLM API 密钥（未设置时降级为纯 diff）
  OPENAI_BASE_URL  - API 端点（默认 https://api.openai.com/v1）
  OPENAI_MODEL     - 模型名（默认 gpt-4o-mini）

输出文件：
  site/generated/change_reports/{id}_{date}.json - 结构化变更分析报告
"""

import argparse
import datetime
import difflib
import json
import os
import re
import subprocess
import sys

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS_FILE = os.path.join(BASE_DIR, "site", "generated", "update_status.json")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "site", "generated", "snapshots")
REPORTS_DIR = os.path.join(BASE_DIR, "site", "generated", "change_reports")
POLICIES_DIR = os.path.join(BASE_DIR, "site", "data", "policies")

TARGET_LABELS = {"main": "主监控页", "toc": "个人版条款", "tob": "企业版条款"}

# LLM 配置
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# 分析 prompt：要求 LLM 对比新旧政策文本，输出结构化 JSON
ANALYSIS_PROMPT = """你是一个 AI 产品政策分析专家。请对比以下政策文本的新旧版本，提取关键变化。

重点关注以下维度（如果相关）：
1. 训练数据政策：用户输入/输出是否用于模型训练？默认状态（加入式/退出式）？是否有变化？
2. 退出/关闭机制：用户如何拒绝训练授权？机制是否有变化？
3. 数据留存期限：数据保留时长是否有变化？
4. 知识产权：用户内容版权归属是否有变化？
5. 其他重大条款变化：责任限制、争议解决、服务终止等。

请输出 JSON（不要 markdown 代码块），格式如下：
{
  "has_substantive_change": true/false,
  "change_summary": "一句话概括主要变化",
  "training_policy": {
    "changed": true/false,
    "old": "旧版训练政策描述（如无变化则 null）",
    "new": "新版训练政策描述（如无变化则 null）"
  },
  "opt_out_mechanism": {
    "changed": true/false,
    "detail": "退出机制变化描述（如无变化则 null）"
  },
  "data_retention": {
    "changed": true/false,
    "detail": "留存期限变化描述（如无变化则 null）"
  },
  "other_changes": ["其他重大变化1", "其他重大变化2"],
  "risk_assessment": "风险等级是否可能需要调整的评估（如无需调整则 null）",
  "recommended_actions": ["建议的人工跟进动作1", "动作2"]
}

如果新旧文本实质内容相同（仅排版/导航/广告等非政策内容变化），请设置 has_substantive_change=false。

=== 旧版政策文本 ===
{old_text}

=== 新版政策文本 ===
{new_text}
"""


def load_status():
    if not os.path.exists(STATUS_FILE):
        return {}
    with open(STATUS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_policy(pid):
    path = os.path.join(POLICIES_DIR, pid + ".json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_old_snapshot(pid, key):
    """查找旧快照优先级：
    1. prev.txt（check_updates.py 变更时自动备份的旧 latest.txt）
    2. snapshots 目录下除 latest.txt 外最新的日期存档（非今天）
    3. git 历史中 latest.txt 的上一个版本"""
    target_dir = os.path.join(SNAPSHOTS_DIR, pid, key)
    if not os.path.isdir(target_dir):
        return None

    # 方式1：prev.txt（最可靠的旧版本来源）
    prev_path = os.path.join(target_dir, "prev.txt")
    if os.path.exists(prev_path):
        with open(prev_path, encoding="utf-8") as f:
            return f.read()

    # 方式2：取日期存档中除今天外最新的
    dated_files = []
    today = datetime.date.today().isoformat()
    for fname in os.listdir(target_dir):
        if re.match(r"\d{4}-\d{2}-\d{2}\.txt$", fname) and fname[:-4] != today:
            dated_files.append(fname)
    if dated_files:
        dated_files.sort(reverse=True)
        with open(os.path.join(target_dir, dated_files[0]), encoding="utf-8") as f:
            return f.read()

    # 方式3：从 git 历史取 latest.txt 的上一版本
    latest_path = os.path.join(target_dir, "latest.txt")
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H", "-2", "--", latest_path],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=10,
        )
        commits = result.stdout.strip().split("\n")
        if len(commits) >= 2:
            old_commit = commits[1]
            result = subprocess.run(
                ["git", "show", f"{old_commit}:{latest_path}"],
                capture_output=True, text=True, cwd=BASE_DIR, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
    except Exception:
        pass

    return None


def find_new_snapshot(pid, key):
    """新快照就是 latest.txt。"""
    path = os.path.join(SNAPSHOTS_DIR, pid, key, "latest.txt")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def compute_text_diff(old_text, new_text):
    """生成可读的 unified diff，截取最有变化的区域。"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile="旧版", tofile="新版",
        lineterm="",
    ))
    if not diff:
        return "（无文本差异）"
    # diff 可能很长，截取前后各 100 行
    if len(diff) > 200:
        diff = diff[:100] + ["...", f"（省略 {len(diff) - 200} 行）", "..."] + diff[-100:]
    return "\n".join(diff)


def truncate_text(text, max_chars=15000):
    """截断文本以适应 LLM 上下文限制。"""
    if len(text) <= max_chars:
        return text
    # 保留开头和结尾
    half = max_chars // 2
    return text[:half] + f"\n\n[... 省略 {len(text) - max_chars} 字符 ...]\n\n" + text[-half:]


def call_llm(old_text, new_text):
    """调用 LLM 分析新旧政策文本差异，返回结构化结果。"""
    if not LLM_API_KEY:
        return None

    prompt = ANALYSIS_PROMPT.format(
        old_text=truncate_text(old_text),
        new_text=truncate_text(new_text),
    )

    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"  LLM 调用失败: {e}", file=sys.stderr)
        return None


def analyze_product(pid, target_key, target_info, policy):
    """分析单个产品的单个目标变更。"""
    name = policy.get("name", pid)
    label = TARGET_LABELS.get(target_key, target_key)
    url = target_info.get("url", "")

    old_text = find_old_snapshot(pid, target_key)
    new_text = find_new_snapshot(pid, target_key)

    if not new_text:
        return None
    if not old_text:
        # 没有旧快照，无法对比（首次基线情况）
        return {
            "pid": pid,
            "name": name,
            "target": target_key,
            "label": label,
            "url": url,
            "has_old_snapshot": False,
            "message": "无旧快照可对比（首次基线或旧快照已清理）",
        }

    # 文本 diff
    text_diff = compute_text_diff(old_text, new_text)

    # LLM 分析
    print(f"  调用 LLM 分析 {pid}·{target_key}...")
    llm_result = call_llm(old_text, new_text)

    report = {
        "pid": pid,
        "name": name,
        "target": target_key,
        "label": label,
        "url": url,
        "has_old_snapshot": True,
        "analysis_date": datetime.datetime.now().isoformat(),
        "text_diff": text_diff,
    }

    if llm_result:
        report["llm_analysis"] = llm_result
        report["has_substantive_change"] = llm_result.get("has_substantive_change", True)
        report["change_summary"] = llm_result.get("change_summary", "")
    else:
        report["llm_analysis"] = None
        report["has_substantive_change"] = True  # 无法判定时保守标记
        report["change_summary"] = "LLM 不可用，仅提供文本 diff，需人工判断"

    return report


def save_report(report):
    """保存分析报告到 site/generated/change_reports/。"""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    date = datetime.date.today().isoformat()
    pid = report["pid"]
    target = report["target"]
    path = os.path.join(REPORTS_DIR, f"{pid}_{target}_{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


def render_markdown_summary(reports):
    """渲染 Markdown 摘要（供 Issue 评论）。"""
    if not reports:
        return "未检测到需要分析的变更。"

    lines = ["## AI 辅助政策变更分析报告", ""]
    lines.append(f"分析时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    substantive = [r for r in reports if r.get("has_substantive_change")]
    no_change = [r for r in reports if r.get("has_substantive_change") is False]

    if substantive:
        lines.append(f"### ⚠️ 检测到实质变更（{len(substantive)} 个）")
        lines.append("")
        for r in substantive:
            lines.append(f"#### {r['name']}（{r['label']}）")
            lines.append(f"- URL: {r['url']}")
            if r.get("change_summary"):
                lines.append(f"- 变更摘要：{r['change_summary']}")
            llm = r.get("llm_analysis") or {}
            if llm.get("training_policy", {}).get("changed"):
                tp = llm["training_policy"]
                lines.append(f"- 训练政策变化：{tp.get('new', '')}")
            if llm.get("opt_out_mechanism", {}).get("changed"):
                lines.append(f"- 退出机制变化：{llm['opt_out_mechanism']['detail']}")
            if llm.get("data_retention", {}).get("changed"):
                lines.append(f"- 留存期限变化：{llm['data_retention']['detail']}")
            for change in llm.get("other_changes", []):
                lines.append(f"- 其他变化：{change}")
            if llm.get("risk_assessment"):
                lines.append(f"- 风险评估：{llm['risk_assessment']}")
            for action in llm.get("recommended_actions", []):
                lines.append(f"- 建议动作：{action}")
            lines.append("")

    if no_change:
        lines.append(f"### ✅ 非实质变更（{len(no_change)} 个）")
        lines.append("")
        for r in no_change:
            lines.append(f"- {r['name']}（{r['label']}）：{r.get('change_summary', '仅排版/非政策内容变化')}")
        lines.append("")

    lines.append("### 人工确认指引")
    lines.append("")
    lines.append("1. 实质变更产品：请访问上述 URL 确认变更内容，更新 `site/data/policies/{id}.json`")
    lines.append("2. 非实质变更：无需更新数据文件，下次监控自动以新内容为基线")
    lines.append("3. 完整分析报告：`site/generated/change_reports/` 目录下各产品 JSON 文件")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AI 辅助政策变更分析")
    parser.add_argument("--product", help="只分析指定产品 ID")
    args = parser.parse_args()

    print("=" * 60)
    print("AI 辅助政策变更分析")
    print(f"运行时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if LLM_API_KEY:
        print(f"LLM：{LLM_BASE_URL} / {LLM_MODEL}")
    else:
        print("LLM：未配置 API key，降级为纯文本 diff 模式")
    print("=" * 60)

    status = load_status()
    products = status.get("products", {})
    changed_products = {
        pid: info for pid, info in products.items()
        if info.get("status") == "changed"
    }

    if args.product:
        changed_products = {
            pid: info for pid, info in changed_products.items()
            if pid == args.product
        }

    if not changed_products:
        print("\n没有需要分析的变更产品。")
        return 0

    print(f"\n共 {len(changed_products)} 个变更产品需要分析\n")

    all_reports = []
    for pid, info in changed_products.items():
        policy = load_policy(pid)
        name = policy.get("name", pid)
        print(f"分析 {name} ({pid})...")

        targets = info.get("targets") or {}
        for key, t_info in targets.items():
            if t_info.get("status") != "changed":
                continue
            report = analyze_product(pid, key, t_info, policy)
            if report:
                path = save_report(report)
                print(f"  报告已保存：{path}")
                all_reports.append(report)
        print()

    # 输出 Markdown 摘要
    md = render_markdown_summary(all_reports)
    print("=" * 60)
    print(md)

    # 写入摘要文件（供 CI 使用）
    summary_path = os.path.join(REPORTS_DIR, "_summary.md")
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n摘要已写入：{summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
