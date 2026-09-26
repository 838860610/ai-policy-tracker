#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
policy-change-verify skill 的本地核实助手。

从 site/generated/pending_verification.json（待核实队列，优先）与 update_status.json
（含 failed/suspicious）找出需要核实的产品与目标，对每个目标用 prev.txt / 日期存档 /
git 历史可靠地取回"旧快照"（自动跳过内容相同的重基线提交），
与 latest.txt（新快照）做 unified diff，并输出该产品的当前政策 JSON，
供 agent 判断实质变更并起草补丁。核实完成并更新数据后，用 --resolve 做收尾：
清除待核实队列项，并同步把 update_status.json 中对应目标改为 ok，使页面上的
"待核实"告警立即消失（页面告警只读 update_status.json，与队列互不影响）。

用法（从仓库根目录运行）：
  python3 policy_verify.py --list
  python3 policy_verify.py <product_id> [target]
  python3 policy_verify.py <product_id> --all-targets
  python3 policy_verify.py --resolve <product_id> [target]   # 核实收尾：清队列 + 清页面告警

  --repo PATH   仓库根目录（默认当前工作目录）
  --list        列出 update_status.json 中所有被标记的产品与目标
  --depth N     取旧快照时回溯的 git 历史提交数（默认 6）
  --max-diff N  diff 最大行数（默认 240，超出前后截断）
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

TARGET_LABELS = {"main": "主监控页", "toc": "个人版条款", "tob": "企业版条款"}
FLAGGED = ("changed", "failed", "suspicious")
ID_PATTERN = re.compile(r"^[a-z0-9-]+$")
TARGET_PATTERN = re.compile(r"^(?:main|toc|tob|source_[A-Za-z0-9_-]+)$")


def repo_root(arg_repo):
    return os.path.abspath(arg_repo or os.getcwd())


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


def load_status(root):
    path = os.path.join(root, "site", "generated", "update_status.json")
    if not os.path.exists(path):
        print("[错误] 找不到 %s（请先运行 check_updates.py 或在仓库根目录执行）" % path, file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print("[错误] update_status.json 解析失败：%s" % e, file=sys.stderr)
        sys.exit(2)


def product_name(root, pid):
    pj = os.path.join(root, "site", "data", "policies", pid + ".json")
    if os.path.exists(pj):
        try:
            with open(pj, encoding="utf-8") as f:
                return json.load(f).get("name", pid)
        except Exception:
            pass
    return pid


def pending_path(root):
    return os.path.join(root, "site", "generated", "pending_verification.json")


def load_pending(root):
    path = pending_path(root)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print("[错误] pending_verification.json 解析失败：%s" % e, file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(data, dict) or not isinstance(data.get("items", {}), dict):
        print("[错误] pending_verification.json 格式错误：items 必须是对象", file=sys.stderr)
        raise SystemExit(2)
    return data


def list_pending(data):
    items = (data or {}).get("items", {})
    if not items:
        print("待核实队列为空。")
        return
    print("待核实队列（检测→核实的持久交接物；核实并更新数据后用 --resolve 清除）：\n")
    for pk, it in sorted(items.items()):
        print("● %s（%s） %s  %s" % (pk, it.get("name", ""), it.get("label", ""), it.get("url", "")))
        print("    首次发现: %s  最近发现: %s" % (it.get("first_seen", ""), it.get("last_seen", "")))
    print()


def resolve_pending(root, pid, key):
    """核实完成并更新数据后，从待核实队列移除对应项（跨轮持久交接的收尾）。"""
    path = pending_path(root)
    if not os.path.exists(path):
        print("[提示] 没有待核实队列文件，无需清除。")
        return
    data = load_pending(root)
    items = data.get("items", {})
    if not isinstance(items, dict):
        print("[错误] pending_verification.json 的 items 必须是对象", file=sys.stderr)
        raise SystemExit(2)
    if key:
        removed = items.pop("%s:%s" % (pid, key), None) is not None
    else:
        removed_keys = [k for k in items if k.startswith(pid + ":")]
        for k in removed_keys:
            items.pop(k, None)
        removed = bool(removed_keys)
    data["items"] = items
    data["updated_at"] = datetime.datetime.now().isoformat()
    atomic_write_json(path, data)
    if removed:
        print("[完成] 已从待核实队列移除 %s%s 的相关项。" %
              (pid, ("/" + key) if key else " 全部目标"))
    else:
        print("[提示] 队列中没有 %s%s 的项。" % (pid, ("/" + key) if key else ""))


def clear_page_alert(root, pid, key):
    """清除页面上的"待核实"告警：把该产品（默认全部 changed 目标）在
    update_status.json 中标记为 ok，并重算产品级状态与全局计数。

    页面 banner 只读 update_status.json，与 pending_verification 队列互不影响，
    因此只清队列不足以让告警消失，必须同步改动这里。
    只处理 changed（failed/suspicious 属监控异常，交给各自的修复流程，不在此掩盖）。
    """
    path = os.path.join(root, "site", "generated", "update_status.json")
    if not os.path.exists(path):
        print("[提示] 没有 update_status.json，无需清除页面告警。")
        return
    data = load_status(root)

    products = data.get("products") or {}
    prod = products.get(pid)
    if not prod:
        print("[提示] update_status.json 中没有产品 %s，页面告警已忽略。" % pid)
        return

    now = datetime.datetime.now().isoformat()
    cleared = []
    for k, t in (prod.get("targets") or {}).items():
        if key and k != key:
            continue
        if t.get("status") != "changed":
            continue
        t["status"] = "ok"
        t["message"] = "已人工核实（policy_verify --resolve）"
        t["resolved_at"] = now
        t["last_changed_date"] = None
        cleared.append(k)

    if not cleared:
        print("[提示] %s%s 在 update_status.json 中没有 changed 目标（或已处理）。" %
              (pid, ("/" + key) if key else ""))
        return

    statuses = [t.get("status") for t in (prod.get("targets") or {}).values()]
    prod["status"] = ("changed" if "changed" in statuses else
                      "failed" if "failed" in statuses else
                      "suspicious" if "suspicious" in statuses else
                      "skipped" if "skipped" in statuses else "ok")
    if prod["status"] == "ok":
        prod["message"] = "内容未变化（本次核实后已确认）"
    # health 与 status 正交：核实内容不会让抓取降级消失，按实际 health 重算
    severities = {"degraded": 1, "no_baseline": 2, "blocked": 3}
    healths = [t.get("health") or "ok" for t in (prod.get("targets") or {}).values()]
    prod["health"] = max(healths, key=lambda h: severities.get(h, 0))
    prod["health_issues"] = sum(1 for h in healths if h in severities)

    counts = {"changed": 0, "failed": 0, "suspicious": 0, "skipped": 0}
    for p in products.values():
        s = p.get("status")
        if s in counts:
            counts[s] += 1
    meta = data.get("meta") or {}
    meta.update(counts)
    meta["total_products"] = len(products)
    # 健康计数同步重算（--resolve 不直接改健康队列，但页面 meta 不能留着旧数字）
    health_items = {}
    for other_pid, p in products.items():
        for k, t in (p.get("targets") or {}).items():
            h = t.get("health")
            if h in severities:
                health_items["%s:%s" % (other_pid, k)] = h
    meta["health_issues"] = len(health_items)
    for h in severities:
        meta["health_" + h] = sum(1 for v in health_items.values() if v == h)
    data["meta"] = meta

    atomic_write_json(path, data)

    print("[完成] 已清除 %s 的页面告警（目标：%s），产品状态 → %s；"
          "全局计数 changed=%d failed=%d suspicious=%d。" %
          (pid, "、".join(cleared), prod["status"],
           meta.get("changed", 0), meta.get("failed", 0), meta.get("suspicious", 0)))


HEALTH_LABELS = {
    "blocked": "被拦截（反爬/限流）",
    "no_baseline": "无可用基线",
    "degraded": "抓取降级（已保留上次快照）",
}


def list_health(root, status):
    """列出抓取健康问题：这些目标不该进待核实队列，而是要修抓取配置。"""
    items = []
    for pid, info in (status.get("products") or {}).items():
        for key, t in (info.get("targets") or {}).items():
            health = t.get("health")
            if health in HEALTH_LABELS:
                items.append((pid, key, t, health))
    if not items:
        return
    print("抓取健康问题 %d 个（政策未变更，但监控数据不可信，需修抓取配置）：\n" % len(items))
    for pid, key, t, health in items:
        last_good = t.get("last_good_at") or "从未成功抓取"
        print("● %s（%s）  health=%s  %s" % (
            pid, product_name(root, pid), health, HEALTH_LABELS[health]))
        print("    - %s (%s): %s" % (key, TARGET_LABELS.get(key, key), t.get("url", "")))
        print("      原因: %s" % t.get("message", ""))
        print("      上次成功: %s" % last_good)
        print("      处置: .venv/bin/python scripts/check_updates.py --only %s:%s --timeout 60"
              % (pid, key))
        print()


def list_flagged(root, status):
    prods = [(pid, info) for pid, info in (status.get("products") or {}).items()
             if info.get("status") in FLAGGED]
    if not prods:
        print("未在 update_status.json 中发现 changed/failed/suspicious 的产品。")
    else:
        print("发现 %d 个被标记产品：\n" % len(prods))
        for pid, info in prods:
            print("● %s（%s）  status=%s" % (pid, product_name(root, pid), info.get("status")))
            for key, t in (info.get("targets") or {}).items():
                if t.get("status") in FLAGGED:
                    print("    - %s (%s): %s  %s" % (key, TARGET_LABELS.get(key, key),
                                                     t.get("status"), t.get("url", "")))
            print()
    list_health(root, status)


def read_text(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.lstrip().startswith("%PDF-"):
            return None
        return text
    except Exception:
        return None


def git_show(root, rel, sha):
    try:
        r = subprocess.run(["git", "show", "%s:%s" % (sha, rel)],
                           capture_output=True, text=True, cwd=root, timeout=15)
        if r.returncode == 0 and r.stdout.strip() and not r.stdout.lstrip().startswith("%PDF-"):
            return r.stdout
    except Exception:
        pass
    return None


def get_old_text(root, pid, key, depth):
    """优先 prev.txt → 非今天日期存档 → git 历史中首个内容不同的提交。
    自动跳过'重建基线'产生的内容相同提交，规避整库重算造成的假差异。"""
    base = os.path.join(root, "site", "generated", "snapshots", pid, key)
    latest_path = os.path.join(base, "latest.txt")
    new = read_text(latest_path)
    if new is None:
        return None, "none"

    prev = read_text(os.path.join(base, "prev.txt"))
    if prev is not None and prev.strip() and prev.strip() != new.strip():
        return prev, "prev.txt"

    today = datetime.date.today().isoformat()
    dated = []
    if os.path.isdir(base):
        for fn in os.listdir(base):
            if re.match(r"\d{4}-\d{2}-\d{2}\.txt$", fn) and fn[:-4] != today:
                dated.append(fn)
    dated.sort(reverse=True)
    for fn in dated:
        txt = read_text(os.path.join(base, fn))
        if txt and txt.strip() and txt.strip() != new.strip():
            return txt, "dated:%s" % fn[:-4]

    rel = os.path.relpath(latest_path, root)
    try:
        r = subprocess.run(["git", "log", "--format=%H", "-%d" % (depth + 1), "--", rel],
                           capture_output=True, text=True, cwd=root, timeout=15)
        commits = [c for c in r.stdout.strip().split("\n") if c]
    except Exception:
        commits = []
    for sha in commits:
        txt = git_show(root, rel, sha)
        if txt and txt.strip() and txt.strip() != new.strip():
            return txt, "git:%s" % sha[:8]
    return None, "none"


def get_new_text(root, pid, key):
    return read_text(os.path.join(root, "site", "generated", "snapshots", pid, key, "latest.txt"))


def unified_diff(old, new, max_diff):
    import difflib
    d = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                 fromfile="旧版", tofile="新版", lineterm=""))
    if not d:
        return "（无文本差异）"
    if len(d) > max_diff:
        half = max_diff // 2
        d = d[:half] + ["...（省略 %d 行）..." % (len(d) - max_diff)] + d[-half:]
    return "\n".join(d)


def print_product(root, pid, keys, depth, max_diff, all_targets=False):
    pj = os.path.join(root, "site", "data", "policies", pid + ".json")
    policy_text = read_text(pj) or "（未找到政策数据文件）"
    status = load_status(root)
    prod = (status.get("products") or {}).get(pid) or {}

    print("=" * 70)
    print("产品：%s（%s）" % (pid, product_name(root, pid)))
    print("=" * 70)

    if all_targets:
        keys = list((prod.get("targets") or {}).keys())
    elif not keys:
        keys = [k for k, t in (prod.get("targets") or {}).items() if t.get("status") in FLAGGED]
    if not keys:
        keys = list((prod.get("targets") or {}).keys())

    for key in keys:
        tinfo = (prod.get("targets") or {}).get(key, {})
        print("\n--- 目标 %s（%s） ---" % (key, TARGET_LABELS.get(key, key)))
        print("URL: %s" % tinfo.get("url", "（无）"))
        print("监测状态: %s" % tinfo.get("status", "（无记录）"))
        old, src = get_old_text(root, pid, key, depth)
        new = get_new_text(root, pid, key)
        print("旧快照来源: %s" % src)
        if old is None or new is None:
            print("⚠️ 无法取得新旧快照对比（可能首次基线或旧版本已清理），请直接打开上方 URL 人工确认。")
            if new:
                print("\n[新快照全文]\n" + new)
        else:
            print("\n[旧 → 新 diff]\n" + unified_diff(old, new, max_diff))

    print("\n" + "-" * 70)
    print("[当前政策数据 site/data/policies/%s.json]\n" % pid)
    print(policy_text)


def main():
    ap = argparse.ArgumentParser(description="政策变更本地核实助手")
    ap.add_argument("product_id", nargs="?", help="产品 ID（对应 policies/{id}.json）")
    ap.add_argument("target", nargs="?", help="目标键 main/toc/tob/source_*（缺省取所有被标记目标）")
    ap.add_argument("--repo", default=None, help="仓库根目录（默认当前目录）")
    ap.add_argument("--list", action="store_true", help="列出待核实队列与所有被标记产品/目标")
    ap.add_argument("--all-targets", action="store_true", help="打印该产品全部目标")
    ap.add_argument("--depth", type=int, default=6, help="回溯 git 历史提交数（默认 6）")
    ap.add_argument("--max-diff", type=int, default=240, help="diff 最大行数（默认 240）")
    ap.add_argument("--resolve", metavar="PRODUCT_ID", default=None,
                    help="核实完成并更新数据后，从待核实队列移除该产品（可配合 target 只移一项）")
    args = ap.parse_args()

    root = repo_root(args.repo)
    if args.resolve and not ID_PATTERN.match(args.resolve):
        print("[错误] 非法产品 ID", file=sys.stderr)
        raise SystemExit(2)
    if args.product_id and not ID_PATTERN.match(args.product_id):
        print("[错误] 非法产品 ID", file=sys.stderr)
        raise SystemExit(2)
    if args.target and not TARGET_PATTERN.match(args.target):
        print("[错误] 非法目标键", file=sys.stderr)
        raise SystemExit(2)

    if args.resolve:
        resolve_pending(root, args.resolve, args.target)
        clear_page_alert(root, args.resolve, args.target)
        return

    status = load_status(root)
    pending = load_pending(root)

    if args.list or not args.product_id:
        if pending is not None:
            list_pending(pending)
        list_flagged(root, status)
        if not args.product_id:
            return

    keys = None
    if args.target:
        keys = [args.target]
    print_product(root, args.product_id, keys, args.depth, args.max_diff, args.all_targets)


if __name__ == "__main__":
    main()
