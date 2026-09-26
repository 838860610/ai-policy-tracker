#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据校验脚本

检查 site/data/products.json（ID 索引）与 site/data/policies/*.json 的结构完整性，
在提交 PR 前运行，防止字段缺失、ID 不一致等问题进入主分支。

用法：
  python3 scripts/validate_data.py

退出码：0 = 通过（可以有警告），1 = 存在错误
"""

import datetime
import ipaddress
import json
import os
import re
import sys
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "site", "data")
INDEX_FILE = os.path.join(DATA_DIR, "products.json")
POLICIES_DIR = os.path.join(DATA_DIR, "policies")

ID_PATTERN = re.compile(r"^[a-z0-9-]+$")

# 训练结论佐证的宽匹配词（key_clauses 引文含任一即视为有佐证）
TRAINING_SYNONYMS = ["训练", "优化", "改进", "提升", "机器学习", "train", "training", "improve"]
# 来源标注：key_clauses 每条应以（来源）结尾
SOURCE_ANNOTATION = re.compile(r"）\s*。?\s*$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def safe_policy_url(value):
    try:
        parsed = urlparse(str(value))
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 443):
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".local"):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False

VERSION_REQUIRED = [
    "used_for_training", "default_state", "opt_out", "opt_out_method",
    "deidentified", "data_retention", "copyright", "risk_level", "key_clauses",
]
VERSION_OPTIONAL = [
    "training_note", "other_uses", "policy_link", "last_verified", "label",
]
TRAINING_STATUSES = {
    "explicit_no", "default_off_opt_in", "default_on_opt_out",
    "explicit_yes", "unknown", "inferred",
}
TOP_REQUIRED = [
    "id", "name", "company", "region", "description", "policy_url",
    "last_verified", "versions", "analysis_summary", "key_findings", "recommendations",
]
RISK_LEVELS = {"green", "yellow", "red"}

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


FETCH_METHODS = ("requests", "browser")
FETCH_FIELDS = ("fetch_method", "content_selector", "wait_for_selector", "min_body_chars")
# 目标级载体里允许与抓取配置共存的业务字段（sources[] 条目）
FETCH_CARRIER_EXTRA = ("id", "role", "url", "monitored", "title", "note")


def check_fetch_config(where, cfg, strict_unknown=False):
    """校验一处抓取配置（产品级 / targets.main / versions.* / sources[] 四个载体共用）。

    抓取配错不会让数据校验失败，但会让监控静默降级（正文抓不到却看不出是配置问题），
    所以这里按错误处理。

    strict_unknown=True 时额外检查拼写错误——只对"纯配置载体"（targets.main）开启：
    产品级和 versions.* 里混着大量业务字段，对它们做未知键检查只会噪声。
    """
    if not isinstance(cfg, dict):
        return
    if "fetch_method" in cfg and cfg["fetch_method"] not in FETCH_METHODS:
        err(f"{where}: fetch_method 必须是 {' 或 '.join(FETCH_METHODS)}，"
            f"当前为 {cfg['fetch_method']!r}")
    for key in ("content_selector", "wait_for_selector"):
        if key in cfg and not isinstance(cfg[key], str):
            err(f"{where}: {key} 必须是 CSS 选择器字符串，当前为 {type(cfg[key]).__name__}")
    if "min_body_chars" in cfg:
        value = cfg["min_body_chars"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            err(f"{where}: min_body_chars 必须是非负整数，当前为 {value!r}")
    if strict_unknown:
        unknown = set(cfg) - set(FETCH_FIELDS)
        if unknown:
            err(f"{where}: 存在无法识别的字段 {sorted(unknown)}；"
                f"抓取配置只支持 {list(FETCH_FIELDS)}")


def check_version(where, v):
    for key in VERSION_REQUIRED:
        if key not in v:
            err(f"{where}: 缺少必填字段 {key}")
    for key in VERSION_OPTIONAL:
        if key not in v:
            warn(f"{where}: 缺少可选字段 {key}")
    version_date = v.get("last_verified")
    if version_date is not None:
        if not isinstance(version_date, str) or not DATE_PATTERN.match(version_date):
            err(f"{where}: last_verified 格式应为 YYYY-MM-DD，当前为 {version_date!r}")
        else:
            try:
                if datetime.date.fromisoformat(version_date) > datetime.date.today():
                    err(f"{where}: last_verified={version_date} 晚于今天")
            except ValueError:
                err(f"{where}: last_verified={version_date!r} 不是有效日期")
    if "used_for_training" in v and not isinstance(v["used_for_training"], bool):
        err(f"{where}: used_for_training 必须是布尔值，当前为 {v['used_for_training']!r}")
    if "training_status" in v and v["training_status"] not in TRAINING_STATUSES:
        err(f"{where}: training_status 必须是 {sorted(TRAINING_STATUSES)} 之一，"
            f"当前为 {v['training_status']!r}")
    if "training_status" in v and "used_for_training" in v:
        if v["training_status"] in ("explicit_yes", "default_on_opt_out", "inferred") \
                and v["used_for_training"] is not True:
            err(f"{where}: training_status={v['training_status']!r} 与 used_for_training=false 矛盾")
        if v["training_status"] in ("explicit_no", "default_off_opt_in") \
                and v["used_for_training"] is not False:
            err(f"{where}: training_status={v['training_status']!r} 与 used_for_training=true 矛盾")
    if "deidentified" in v and not isinstance(v["deidentified"], bool):
        err(f"{where}: deidentified 必须是布尔值，当前为 {v['deidentified']!r}")
    if "risk_level" in v and v["risk_level"] not in RISK_LEVELS:
        err(f"{where}: risk_level 必须是 {sorted(RISK_LEVELS)} 之一，当前为 {v['risk_level']!r}")
    link = v.get("policy_link")
    if link is not None and not safe_policy_url(link):
        err(f"{where}: policy_link 必须是公网 HTTPS URL，当前为 {link!r}")

    clauses = v.get("key_clauses")
    if clauses is not None:
        if not isinstance(clauses, list) or not clauses:
            err(f"{where}: key_clauses 必须是非空数组")
        else:
            for i, c in enumerate(clauses):
                if not isinstance(c, str) or not c.strip():
                    err(f"{where}: key_clauses[{i}] 不能为空")
                elif c.strip() in ("待核实", "待核实具体条款。", "待核实具体条款，需进一步查阅。"):
                    warn(f"{where}: key_clauses[{i}] 仍是占位文字，需要补充真实条款摘录")
                elif not SOURCE_ANNOTATION.search(c.strip()):
                    warn(f"{where}: key_clauses[{i}] 缺少来源标注（建议以（来源条款号/文档名）结尾）")
    if v.get("data_retention") == "待核实":
        warn(f"{where}: data_retention 仍是占位文字")
    # 风险等级推导（A1-d）：标为绿的版本必须满足方法论四项绿色标准
    def retention_clear_30(ret):
        if not ret:
            return False
        if re.search(r"未明确|待核实|待核|未载明|未说明", ret):
            return False
        return bool(re.search(r"30\s*天|≤\s*30|30日", ret))

    if v.get("risk_level") == "green":
        reasons = []
        training_status = v.get("training_status")
        no_training = (
            v.get("used_for_training") is False
            and training_status not in ("unknown", "inferred")
        )
        if not no_training:
            reasons.append("训练判定非'默认不训练'")
        if v.get("deidentified") is not True:
            reasons.append("未载明去标识化")
        if not retention_clear_30(v.get("data_retention", "")):
            reasons.append("留存期限不明确或超30天")
        cp = v.get("copyright", "")
        if "用户" not in cp or "待核实" in cp:
            reasons.append("版权归属未明确归用户")
        if reasons:
            warn(f"{where}: 标为绿但未满足全部绿色标准：{'；'.join(reasons)}（方法论：绿需四项全部满足；如判定有据可忽略本提示）")

    tn = (v.get("training_note") or "")
    silent_note = any(m in tn for m in ("沉默", "零命中", "未明示"))
    xref = "适用" in tn and "协议" in tn or "详见" in tn
    if not silent_note and not xref and "训练" in tn and isinstance(clauses, list) and clauses:
        joined = " ".join(c for c in clauses if isinstance(c, str))
        if not any(syn in joined for syn in TRAINING_SYNONYMS):
            warn(f"{where}: training_note 声称训练，但 key_clauses 无训练相关原文佐证（标准同义词组：{'/'.join(TRAINING_SYNONYMS)}）")

    # Qoder 教训：条款含训练/优化授权表述却标 used_for_training=false，
    # 必须有加入式（opt-in）或明示不训练的依据，否则判定矛盾
    if v.get("used_for_training") is False and isinstance(clauses, list) and clauses:
        joined = " ".join(c for c in clauses if isinstance(c, str))
        if any(s in joined for s in ("训练", "优化", "改进", "提升", "机器学习")):
            optin = any(m in joined for m in ("加入", "除非", "自愿"))
            negative = any(m in joined for m in ("不会", "不用于", "不使用"))
            silent = any(m in tn for m in ("沉默", "零命中", "未明示"))
            if not (optin or negative or silent):
                warn(f"{where}: key_clauses 含训练/优化授权表述但 used_for_training=false——"
                     f"若为加入式请补充'加入/除非'依据，若为明示不训练请补充否定条款，否则应改为 true")


def validate_policy(pid, path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        err(f"{pid}: 政策数据必须是对象")
        return

    if data.get("id") != pid:
        err(f"{os.path.basename(path)}: 文件内 id={data.get('id')!r} 与文件名 {pid!r} 不一致")
    for key in TOP_REQUIRED:
        if key not in data:
            err(f"{pid}: 缺少必填字段 {key}")
        elif data[key] is None:
            # 旧版只检查"键是否存在"，null 会一路放行并在前端显示空白
            err(f"{pid}: 必填字段 {key} 不能为 null")
    for key in ("icon", "product_url"):
        if key not in data:
            warn(f"{pid}: 缺少可选字段 {key}")
    check_fetch_config(f"{pid}", data)
    if "monitor" in data and not isinstance(data["monitor"], bool):
        err(f"{pid}: monitor 必须是布尔值")

    region = data.get("region")
    if region is not None and region not in ("中国", "美国", "全球"):
        warn(f"{pid}: region={region!r} 不是预期取值（中国/美国/全球），"
             f"会导致首页「国内/海外」筛选与 README 分组错位")

    lv = data.get("last_verified")
    if lv is not None and not (isinstance(lv, str) and DATE_PATTERN.match(lv)):
        err(f"{pid}: last_verified 格式应为 YYYY-MM-DD，当前为 {lv!r}")
    elif isinstance(lv, str) and DATE_PATTERN.match(lv):
        try:
            d = datetime.date.fromisoformat(lv)
            if d < datetime.date(2025, 1, 1):
                warn(f"{pid}: last_verified={lv} 距今较久，建议重新核实")
            elif d > datetime.date.today():
                err(f"{pid}: last_verified={lv} 晚于今天")
        except ValueError:
            err(f"{pid}: last_verified={lv!r} 不是有效日期")

    url = data.get("policy_url")
    if url is not None and not safe_policy_url(url):
        err(f"{pid}: policy_url 必须是公网 HTTPS URL，当前为 {url!r}")

    sources = data.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            err(f"{pid}: sources 必须是数组")
        else:
            source_ids = set()
            for i, source in enumerate(sources):
                if not isinstance(source, dict):
                    err(f"{pid}: sources[{i}] 必须是对象")
                    continue
                source_id = source.get("id")
                if not isinstance(source_id, str) or not re.match(r"^[A-Za-z0-9_-]+$", source_id):
                    err(f"{pid}: sources[{i}].id 必须使用字母、数字、下划线或连字符")
                elif source_id in source_ids:
                    err(f"{pid}: sources.id={source_id!r} 重复")
                else:
                    source_ids.add(source_id)
                source_url = source.get("url")
                if not safe_policy_url(source_url):
                    err(f"{pid}: sources[{i}].url 必须是公网 HTTPS URL")
                if "monitored" in source and not isinstance(source["monitored"], bool):
                    err(f"{pid}: sources[{i}].monitored 必须是布尔值")
                check_fetch_config(f"{pid}.sources[{i}]", source)

    # targets.main：顶层 policy_url 对应 main 目标的抓取配置载体。
    # toc/tob 用 versions.*、补充来源用 sources[]，不在此处重复定义，避免两处配置歧义。
    targets_cfg = data.get("targets")
    if targets_cfg is not None:
        if not isinstance(targets_cfg, dict):
            err(f"{pid}: targets 必须是对象（当前为 %s），"
                "toc/tob 请写进 versions.*，补充来源请写进 sources[] 条目"
                % type(targets_cfg).__name__)
        else:
            for key in targets_cfg:
                if key != "main":
                    err(f"{pid}: targets 只支持 main 键（当前为 {key!r}）；"
                        "toc/tob 请写进 versions.*，补充来源请写进 sources[] 条目")
            if "main" in targets_cfg:
                main_cfg = targets_cfg["main"]
                if not isinstance(main_cfg, dict):
                    err(f"{pid}: targets.main 必须是对象")
                else:
                    check_fetch_config(f"{pid}.targets.main", main_cfg, strict_unknown=True)

    versions = data.get("versions")
    if versions is not None and not isinstance(versions, dict):
        # 旧版把非 dict 静默置空，versions: [] / "abc" 都能通过校验
        err(f"{pid}: versions 必须是对象，当前为 {type(versions).__name__}")
        versions = {}
    if not isinstance(versions, dict):
        versions = {}

    def check_version_block(tier, note_field):
        if tier in versions:
            block = versions[tier]
            if isinstance(block, dict):
                check_version(f"{pid}.versions.{tier}", block)
                check_fetch_config(f"{pid}.versions.{tier}", block)
            else:
                err(f"{pid}: versions.{tier} 必须是对象，当前为 {type(block).__name__!r}")
        elif data.get(note_field):
            pass  # 有书面说明（如纯开发者产品 / 无企业版），视为合规
        else:
            fallback = "如为纯开发者产品，请添加 toc_note 说明原因" if tier == "toc" \
                else "如确无企业版，请在数据中添加 tob_note 说明原因"
            warn(f"{pid}: 没有 {tier} 版本数据（详情页会隐藏对应标签）；{fallback}")

    check_version_block("toc", "toc_note")
    check_version_block("tob", "tob_note")
    top_verified = data.get("last_verified")
    if isinstance(top_verified, str):
        for tier, block in versions.items():
            if isinstance(block, dict) and isinstance(block.get("last_verified"), str):
                if block["last_verified"] > top_verified:
                    warn(f"{pid}.versions.{tier}.last_verified={block['last_verified']} "
                         f"晚于顶层 last_verified={top_verified}")

    timeline = data.get("timeline")
    if timeline is not None:
        if not isinstance(timeline, list):
            err(f"{pid}: timeline 必须是数组")
        else:
            for i, item in enumerate(timeline):
                if not isinstance(item, dict) or "date" not in item or "event" not in item:
                    err(f"{pid}: timeline[{i}] 必须包含 date 和 event 字段")
                    continue
                if not re.match(r"^\d{4}-\d{2}(-\d{2})?$", str(item.get("date", ""))):
                    warn(f"{pid}: timeline[{i}].date={item.get('date')!r} "
                         f"建议为 YYYY-MM 或 YYYY-MM-DD（约定见 CONTRIBUTING）")
                if not str(item.get("event", "")).strip():
                    err(f"{pid}: timeline[{i}].event 不能为空")

    for key in ("key_findings", "recommendations"):
        v = data.get(key)
        if v is not None and (not isinstance(v, list) or not v):
            err(f"{pid}: {key} 必须是非空数组")


def main():
    if not os.path.exists(INDEX_FILE):
        err(f"索引文件不存在：{INDEX_FILE}")
        report()
        return 1

    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    if not isinstance(index, dict):
        err("products.json 必须是对象")
        report()
        return 1

    ids = index.get("products")
    if not isinstance(ids, list) or not ids:
        err("products.json 的 products 必须是非空 ID 数组")
        report()
        return 1

    valid_ids = [pid for pid in ids if isinstance(pid, str) and ID_PATTERN.match(pid)]
    if len(valid_ids) != len(set(valid_ids)):
        err("products.json 的 products 存在重复 ID")
    if len(valid_ids) != len(ids):
        err("products.json 的 products 包含非法 ID")

    meta = index.get("meta")
    if not isinstance(meta, dict):
        err("products.json: meta 必须是对象")
        meta = {}
    if "schema_version" not in meta:
        warn("products.json: meta 缺少 schema_version（建议标注整数版本号，便于将来数据结构迁移时追踪兼容性）")
    elif not isinstance(meta["schema_version"], int) or isinstance(meta["schema_version"], bool):
        err(f"products.json: meta.schema_version 必须是整数，当前为 {meta['schema_version']!r}")
    last_updated = meta.get("last_updated")
    if last_updated is not None:
        if not isinstance(last_updated, str) or not DATE_PATTERN.match(last_updated):
            err(f"products.json: meta.last_updated 格式应为 YYYY-MM-DD，当前为 {last_updated!r}")
        else:
            try:
                if datetime.date.fromisoformat(last_updated) > datetime.date.today():
                    err(f"products.json: meta.last_updated={last_updated} 晚于今天")
            except ValueError:
                err(f"products.json: meta.last_updated={last_updated!r} 不是有效日期")

    policy_files = {f[:-5] for f in os.listdir(POLICIES_DIR) if f.endswith(".json")}
    for pid in valid_ids:
        path = os.path.join(POLICIES_DIR, pid + ".json")
        if not os.path.exists(path):
            err(f"索引中的产品 {pid} 缺少数据文件 policies/{pid}.json")
            continue
        try:
            validate_policy(pid, path)
        except json.JSONDecodeError as e:
            err(f"policies/{pid}.json 不是合法 JSON：{e}")

    orphan = policy_files - set(valid_ids)
    if orphan:
        err(f"以下 policy 文件未被索引收录（请加入 products.json 或删除）：{sorted(orphan)}")

    report()
    return 1 if errors else 0


def report():
    for w in warnings:
        print(f"  [警告] {w}")
    for e in errors:
        print(f"  [错误] {e}")
    print()
    if errors:
        print(f"校验失败：{len(errors)} 个错误，{len(warnings)} 个警告")
    else:
        print(f"校验通过：0 个错误，{len(warnings)} 个警告")


if __name__ == "__main__":
    sys.exit(main())
