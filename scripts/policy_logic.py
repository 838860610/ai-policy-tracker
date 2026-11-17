#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政策数据的共享推导逻辑：训练状态推断、绿色标准核对、红色条件识别。

为什么存在：`infer_training_status` 曾在 gen_data_bundle.py 与 gen_readme_table.py
各复制一份（首页与 README 口径分叉风险，曾出过首页训练列全表"未明确"的事故），
绿色标准推导又在前端 riskDeriveCard 与 validate_data 各有一份。本模块是唯一权威实现：

  - gen_data_bundle / gen_readme_table：`infer_training_status`（首页/README 展示口径）
  - validate_data.py：`green_unmet` / `red_flags`（提交前一致性校验）
  - gen_api.py：criteria 汇总（机器可读输出）

前端 detail.js 的 trainingStatus / riskDeriveCard 保留 JS 兜底实现（浏览器无法
import Python），`training_status` / `criteria` 显式写回数据后不会走到推断分支；
两端口径互相引用注释，改动时必须同步。

scripts 不是包：使用方通过 `sys.path.insert(0, os.path.dirname(__file__))` 后
`import policy_logic`（见 gen_data_bundle.py）。
"""

import re

TRAINING_STATUSES = {
    "explicit_no", "default_off_opt_in", "default_on_opt_out",
    "explicit_yes", "unknown", "inferred",
}


def infer_training_status(version):
    """训练结论推断：显式 training_status 优先，否则按 used_for_training +
    说明文字的关键词启发式推断。口径与前端 detail.js trainingStatus() 一致。"""
    explicit = version.get("training_status")
    if explicit in TRAINING_STATUSES:
        return explicit
    note = str(version.get("training_note") or "")
    state = str(version.get("default_state") or "")
    opt_out = str(version.get("opt_out") or "")
    if version.get("used_for_training") is False:
        if any(term in state for term in ("未明示", "沉默", "待核", "待核实", "未明确")) \
                or state.startswith("—") \
                or any(term in note for term in ("对训练沉默", "保持沉默", "零命中", "未明示模型训练")):
            return "unknown"
        if any(term in note for term in ("加入式", "opt-in", "主动加入", "主动选择")):
            return "default_off_opt_in"
        return "explicit_no"
    if version.get("used_for_training") is True:
        if any(term in note for term in ("按实质口径", "推断", "直接涵盖模型", "未明示模型训练")):
            return "inferred"
        if any(term in opt_out for term in ("设置开关", "联系", "邮件", "撤回", "退出")):
            return "default_on_opt_out"
        return "explicit_yes"
    return "unknown"


def training_conclusion(version):
    """取该版本的训练结论：显式字段优先，缺失时推断。"""
    status = version.get("training_status")
    return status if status in TRAINING_STATUSES else infer_training_status(version)


def trains(version):
    """该版本是否实际把用户数据用于训练/模型优化（推断口径也算）。
    unknown = 条款对训练沉默，不能认定在训练。"""
    return training_conclusion(version) in ("explicit_yes", "default_on_opt_out", "inferred")


def opt_out_class(opt_out):
    """退出机制强度归类（自由文本 → 四类）。用于红色条件①的机械识别。

    setting  = 产品内/管理端可自行操作（含企业管理关闭、合同约定）
    contact  = 有退出渠道但需联系官方（邮件/客服）
    none     = 未明示退出机制（含"无需退出"——是否构成红色条件取决于是否训练）
    other    = 文本不在已知模式内，机械化判定不适用

    注意：contact 在本库的既有校准里**不是**稳定的红色信号——训练 + 联系式退出
    + 已去标识化的先例为黄色（keling-ai / tongyi-qianwen / xunfei-xinghuo / qoder-cn），
    而 codebuddy:toc 同为联系式却标红（依据另有其他红色条件）。故红色条件①只对
    none 机械命中，contact 留给人工判定。
    """
    text = str(opt_out or "").strip()
    if not text or text.startswith("未明示") or text.startswith("未明确") or text.startswith("无（"):
        return "none"
    if "无需退出" in text:
        return "none"
    if "设置开关" in text or "初始化时选择" in text or "企业管理" in text \
            or "管理员" in text or "合同约定" in text or "组织" in text:
        return "setting"
    if "邮件" in text or "联系" in text or "撤回" in text:
        return "contact"
    return "other"


def retention_clear_30(version):
    """绿色标准③：留存期限明确且 ≤30 天。

    `criteria.retention_clear_30` 显式值优先（迁移后为唯一口径）；
    未填时按 data_retention 文本启发式（与前端 riskDeriveCard 的
    retentionClear30 同一正则）。False 含"明确超 30 天"与"无法确认"两种情形——
    绿色标准要求"明确且 ≤30"，两者都不满足。
    """
    criteria = version.get("criteria")
    if isinstance(criteria, dict) and "retention_clear_30" in criteria:
        value = criteria.get("retention_clear_30")
        return value if isinstance(value, bool) else False
    ret = str(version.get("data_retention") or "")
    if not ret:
        return False
    if re.search(r"未明确|待核实|待核|未载明|未说明", ret):
        return False
    return bool(re.search(r"30\s*天|≤\s*30|30日", ret))


def copyright_user(version):
    """绿色标准④：版权归属用户。
    `criteria.copyright_user` 显式值优先；未填时按 copyright 文本启发式
    （含"用户"且不含"待核实"）。"""
    criteria = version.get("criteria")
    if isinstance(criteria, dict) and "copyright_user" in criteria:
        value = criteria.get("copyright_user")
        return value if isinstance(value, bool) else False
    cp = str(version.get("copyright") or "")
    return bool(cp) and "用户" in cp and "待核实" not in cp


def green_unmet(version):
    """绿色四条的未满足项（方法论 §风险等级评定标准）。
    返回 reason 字符串列表；空列表 = 四项全部满足。"""
    reasons = []
    no_training = (
        version.get("used_for_training") is False
        and training_conclusion(version) not in ("unknown", "inferred")
    )
    if not no_training:
        reasons.append("训练判定非'默认不训练'")
    if version.get("deidentified") is not True:
        reasons.append("未载明去标识化")
    if not retention_clear_30(version):
        reasons.append("留存期限不明确或超30天")
    if not copyright_user(version):
        reasons.append("版权归属未明确归用户")
    return reasons


def red_flags(version):
    """可客观识别的红色条件命中项（方法论红色①③，2026-09-19 修订口径）。

    - ① 训练且未明示退出机制（联系式退出不算——既有校准里黄/红先例并存，见 opt_out_class）；
    - ③ 训练场景下未进行去标识化处理（条款明示不训练时不因未去标识化升红）。
    标准②（长期留存无删除机制）与④（政策模糊）需结合条款证据人工判断，
    不在此机械化——推导只覆盖可从结构化字段客观判定的部分。
    """
    flags = []
    if trains(version):
        if opt_out_class(version.get("opt_out")) == "none":
            flags.append("训练且未明示退出机制")
        if version.get("deidentified") is False:
            flags.append("训练场景下未进行去标识化处理")
    return flags
