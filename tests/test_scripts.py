#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础回归测试：覆盖数据完整性、README 汇总表生成逻辑与线上文档链接有效性。

使用标准库 unittest，无需安装任何第三方依赖：

  python3 -m unittest discover -s tests -v
  python3 tests/test_scripts.py          # 等价写法
  pytest tests/                          # 如已安装 pytest 亦可运行
"""

import importlib.util
import io
import contextlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 站点根目录：index.html / css / js / data / generated / docs 都在其下，
# 部署工作流发布的正是这个目录，因此路径断言都应以它为基准
SITE_DIR = os.path.join(BASE_DIR, "site")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
DATA_DIR = os.path.join(SITE_DIR, "data")
POLICIES_DIR = os.path.join(DATA_DIR, "policies")


def load_script(name):
    """按文件路径加载 scripts/ 下的脚本模块（scripts 不是包，无法直接 import）。"""
    path = os.path.join(SCRIPTS_DIR, name + ".py")
    spec = importlib.util.spec_from_file_location("script_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestDataIntegrity(unittest.TestCase):
    """数据与索引的一致性（与 validate_data.py 互补，这里只断言最关键的硬约束）。"""

    @classmethod
    def setUpClass(cls):
        cls.index = load_json(os.path.join(DATA_DIR, "products.json"))
        cls.ids = cls.index["products"]
        cls.policies = {}
        for pid in cls.ids:
            cls.policies[pid] = load_json(os.path.join(POLICIES_DIR, pid + ".json"))

    def test_index_ids_unique(self):
        self.assertEqual(len(self.ids), len(set(self.ids)), "products.json 存在重复 ID")

    def test_every_indexed_product_has_policy_file(self):
        missing = [pid for pid in self.ids
                   if not os.path.exists(os.path.join(POLICIES_DIR, pid + ".json"))]
        self.assertEqual(missing, [], f"索引中的产品缺少数据文件：{missing}")

    def test_no_orphan_policy_files(self):
        files = {f[:-5] for f in os.listdir(POLICIES_DIR) if f.endswith(".json")}
        self.assertEqual(files - set(self.ids), set(), "存在未被索引收录的 policy 文件")

    def test_id_matches_filename(self):
        for pid, data in self.policies.items():
            self.assertEqual(data.get("id"), pid, f"{pid}.json 的 id 字段与文件名不一致")

    def test_required_fields_present(self):
        required = ["id", "name", "company", "region", "description", "policy_url",
                    "last_verified", "versions", "analysis_summary",
                    "key_findings", "recommendations"]
        for pid, data in self.policies.items():
            for key in required:
                self.assertIn(key, data, f"{pid} 缺少必填字段 {key}")

    def test_last_verified_format(self):
        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for pid, data in self.policies.items():
            lv = data["last_verified"]
            self.assertRegex(lv, pattern, f"{pid}.last_verified 格式应为 YYYY-MM-DD")
            self.assertLessEqual(date.fromisoformat(lv), date.today(),
                                 f"{pid}.last_verified 晚于今天")

    def test_policy_url_is_https(self):
        for pid, data in self.policies.items():
            self.assertTrue(str(data["policy_url"]).startswith("https://"),
                            f"{pid}.policy_url 应以 https:// 开头")

    def test_version_fields(self):
        version_required = ["used_for_training", "default_state", "opt_out",
                            "opt_out_method", "deidentified", "data_retention",
                            "copyright", "risk_level", "key_clauses"]
        for pid, data in self.policies.items():
            for tier in ("toc", "tob"):
                version = data.get("versions", {}).get(tier)
                if not version:
                    continue
                for key in version_required:
                    self.assertIn(key, version, f"{pid}.versions.{tier} 缺少字段 {key}")
                self.assertIsInstance(version["used_for_training"], bool)
                self.assertIsInstance(version["deidentified"], bool)
                self.assertIn(version["risk_level"], {"green", "yellow", "red"})
                self.assertTrue(version["key_clauses"], f"{pid}.versions.{tier}.key_clauses 不能为空")

    def test_validate_script_reports_no_error(self):
        """validate_data.py 在 CI 中被直接调用，这里确保它当前返回 0（无 error）。"""
        module = load_script("validate_data")
        self.assertEqual(module.main(), 0, "validate_data.py 报告了错误，请运行该脚本查看")


class TestReadmeTable(unittest.TestCase):
    """gen_readme_table.py 的纯函数与 README 一致性（不落盘，只读校验）。"""

    @classmethod
    def setUpClass(cls):
        cls.m = load_script("gen_readme_table")

    def test_vendor_of(self):
        self.assertEqual(self.m.vendor_of("火山引擎（字节跳动）"), "字节跳动")
        self.assertEqual(self.m.vendor_of("腾讯云计算（北京）"), "腾讯")
        self.assertEqual(self.m.vendor_of("某不知名厂商"), "某不知名厂商")

    def test_training_cell(self):
        self.assertEqual(self.m.training_cell(True), "✅ 是")
        self.assertEqual(self.m.training_cell(False), "❌ 否")
        self.assertEqual(self.m.training_cell(None), "—")

    def test_training_status_distinguishes_conditional_and_unknown(self):
        opt_in = {"used_for_training": False, "training_note": "加入式优化计划，默认关闭"}
        unknown = {"used_for_training": False, "default_state": "未明示", "training_note": "协议沉默"}
        inferred = {"used_for_training": True, "training_note": "按实质口径涵盖模型优化"}
        self.assertEqual(self.m.training_cell(opt_in), "❌ 默认否")
        self.assertEqual(self.m.training_cell(unknown), "❓ 未明确")
        self.assertEqual(self.m.training_cell(inferred), "⚠️ 疑似是")

    def test_opt_out_cell(self):
        self.assertEqual(self.m.opt_out_cell("设置开关"), "✅ 支持")
        self.assertEqual(self.m.opt_out_cell("邮件申请"), "⚠️ 需邮件申请")
        self.assertEqual(self.m.opt_out_cell("无需退出"), "—")
        self.assertEqual(self.m.opt_out_cell(None), "—")

    def test_build_stats(self):
        products = [
            {"id": "a", "versions": {"toc": {"risk_level": "red"}}},
            {"id": "b", "versions": {"toc": {"risk_level": "green"}}},
            {"id": "c", "versions": {}},  # 无 toc 块 → 未评定
        ]
        stats = self.m.build_stats(products)
        self.assertIn("共 3 款", stats)
        self.assertIn("🔴 高风险 1 款", stats)
        self.assertIn("🟢 低风险 1 款", stats)
        self.assertIn("未评定 1 款", stats)

    def test_build_table_row(self):
        product = {
            "id": "a", "name": "A", "company": "腾讯",
            "versions": {
                "toc": {"risk_level": "red", "used_for_training": True, "opt_out": "设置开关"},
                "tob": {"used_for_training": False},
            },
        }
        table = self.m.build_table([product])
        self.assertIn("| A | 腾讯 | ✅ 是（可退出） | ✅ 支持 | ❌ 否 | 🔴 高 |", table)
        self.assertTrue(table.startswith("| 产品 |"))

    def test_readme_table_is_up_to_date(self):
        """等价于 gen_readme_table.py --check，但不修改 README。"""
        argv = sys.argv
        sys.argv = ["gen_readme_table.py", "--check"]
        try:
            self.assertEqual(self.m.main(), 0, "README 汇总表与数据不一致，请重新生成")
        finally:
            sys.argv = argv


class TestPublishedDocs(unittest.TestCase):
    """防止出现线上死链：站点引用的 docs/ 页面必须真实存在且未被 .gitignore 忽略。"""

    REFERENCING_FILES = ["index.html", "detail.html", "sitemap.xml"]
    DOC_LINK = re.compile(r"docs/[\w./-]+\.html?")

    def test_referenced_docs_exist(self):
        refs = set()
        for name in self.REFERENCING_FILES:
            path = os.path.join(SITE_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                refs.update(self.DOC_LINK.findall(f.read()))
        self.assertTrue(refs, "未在站点文件中找到任何 docs 引用，测试本身可能失效")
        for ref in refs:
            self.assertTrue(os.path.exists(os.path.join(SITE_DIR, ref)),
                            f"{ref} 被站点引用但文件不存在（线上会 404）")

    def test_internal_docs_not_referenced(self):
        """site/docs/internal/ 已被 .gitignore 忽略，站点不得引用其中的文件。"""
        for name in self.REFERENCING_FILES:
            path = os.path.join(SITE_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("site/docs/internal/", f.read(),
                                 f"{name} 引用了被忽略的 site/docs/internal/ 内容")

    def test_gitignore_does_not_ignore_published_docs(self):
        with open(os.path.join(BASE_DIR, ".gitignore"), encoding="utf-8") as f:
            gitignore = f.read()
        self.assertNotIn("docs/*", gitignore, "docs/* 会整体忽略发布页面，导致线上死链")
        self.assertIn("site/docs/internal/", gitignore)


class TestLayout(unittest.TestCase):
    """目录分层约定：data/ 只放源数据，site/generated/ 只放生成物。"""

    def test_data_dir_only_contains_source(self):
        entries = set(os.listdir(DATA_DIR))
        self.assertEqual(entries, {"products.json", "policies"},
                         f"data/ 应只含源数据，实际：{sorted(entries)}")

    def test_no_artifact_left_in_data_or_assets(self):
        for stale in ["bundle.json", "update_status.json", "snapshots", "change_reports"]:
            self.assertFalse(os.path.exists(os.path.join(DATA_DIR, stale)),
                             f"site/data/{stale} 已迁至 site/generated/，不应残留")
        self.assertFalse(os.path.exists(os.path.join(BASE_DIR, "assets")),
                         "assets/ 已合并进 site/generated/，不应残留")

    def test_app_js_reads_from_generated(self):
        """app.js 里的路径是相对站点根的，即 site/generated/... """
        with open(os.path.join(SITE_DIR, "js", "app.js"), encoding="utf-8") as f:
            app = f.read()
        self.assertIn("generated/bundle.json", app)
        self.assertIn("generated/update_status.json", app)
        self.assertIn("generated/monitor_health.json", app)
        self.assertNotIn("data/bundle.json", app)

    def test_monitor_health_queue_is_tracked_and_consistent(self):
        """健康队列必须入库（首页直接读取），且与 update_status.json 里的 health 对得上。"""
        health_path = os.path.join(SITE_DIR, "generated", "monitor_health.json")
        self.assertTrue(os.path.exists(health_path), "缺少 site/generated/monitor_health.json")
        with open(os.path.join(BASE_DIR, ".gitignore"), encoding="utf-8") as f:
            self.assertNotIn("monitor_health.json", f.read())
        health = load_json(health_path)
        self.assertIsInstance(health.get("items"), dict)

        status = load_json(os.path.join(SITE_DIR, "generated", "update_status.json"))
        expected = set()
        for pid, info in (status.get("products") or {}).items():
            for key, target in (info.get("targets") or {}).items():
                if target.get("health") in ("degraded", "no_baseline", "blocked"):
                    expected.add(f"{pid}:{key}")
        self.assertEqual(set(health["items"]), expected,
                         "健康队列与 update_status.json 的 health 字段不一致")
        for pk, item in health["items"].items():
            self.assertIn(item.get("health"), ("degraded", "no_baseline", "blocked"))
            self.assertTrue(item.get("next_action"), f"{pk} 缺少处置建议")
            self.assertIn("first_seen", item)
            self.assertIn("consecutive_runs", item)


    def test_health_details_are_rendered_and_escaped(self):
        """抓取降级明细必须真的渲染出来（而不是只读文件不展示），
        且所有插入 HTML 的字段都要走转义/URL 白名单。"""
        with open(os.path.join(SITE_DIR, "js", "app.js"), encoding="utf-8") as f:
            app = f.read()
        for needle in ("monitor-health", "healthItems", "last_good_at",
                       "next_action", "PT.safeUrl", "PT.escapeHtml"):
            self.assertIn(needle, app, f"app.js 缺少健康明细相关代码：{needle}")
        with open(os.path.join(SITE_DIR, "css", "style.css"), encoding="utf-8") as f:
            css = f.read()
        self.assertIn(".monitor-health", css)
        self.assertIn(".health-tag", css)

    def test_generated_docs_remove_raw_script_and_unsafe_links(self):
        module = load_script("gen_docs")
        rendered = module.render_markdown(
            "<script>window.bad=1</script>\n\n"
            "[bad](javascript:alert(1))\n\n正文"
        )
        self.assertNotIn("<script", rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertIn("正文", rendered)

    def test_site_dir_is_the_publish_root(self):
        """部署工作流发布 site/，站点根文件必须都在其下，URL 才不会变。"""
        for required in ["index.html", "detail.html", "404.html", "robots.txt",
                         "sitemap.xml", ".nojekyll", "css", "js", "data", "generated"]:
            self.assertTrue(os.path.exists(os.path.join(SITE_DIR, required)),
                            f"site/{required} 缺失——部署后对应 URL 会 404")


class _FakeResponse:
    """模仿 requests.Response 的最小实现：只需 headers / encoding / apparent_encoding / text。"""

    def __init__(self, content_type, body_bytes, encoding="ISO-8859-1", apparent="utf-8"):
        self.headers = {"Content-Type": content_type}
        self.content = body_bytes
        self.encoding = encoding
        self.apparent_encoding = apparent

    @property
    def text(self):
        return self.content.decode(self.encoding, errors="replace")


try:
    CHECK_UPDATES = load_script("check_updates")
except ModuleNotFoundError:  # 未安装 requests（CI 会装）
    CHECK_UPDATES = None

POLICY_VERIFY_PATH = os.path.join(
    BASE_DIR, "skills", "policy-change-verify", "scripts", "policy_verify.py"
)
_policy_verify_spec = importlib.util.spec_from_file_location("policy_verify", POLICY_VERIFY_PATH)
POLICY_VERIFY = importlib.util.module_from_spec(_policy_verify_spec)
_policy_verify_spec.loader.exec_module(POLICY_VERIFY)


@unittest.skipIf(CHECK_UPDATES is None, "需要 requests 才能加载 check_updates.py")
class TestResponseDecoding(unittest.TestCase):
    """中文页面不能被解成 mojibake——否则快照不可读、AI 变更分析失效。"""

    BODY = "用户协议 隐私政策".encode("utf-8")

    def test_no_charset_uses_apparent_encoding(self):
        resp = _FakeResponse("text/html", self.BODY)  # 未声明 charset，默认 latin-1
        self.assertIn("用户协议", CHECK_UPDATES.response_text(resp))
        self.assertNotIn("ç¨", CHECK_UPDATES.response_text(resp))

    def test_declared_utf8_is_left_alone(self):
        resp = _FakeResponse("text/html; charset=utf-8", self.BODY, encoding="utf-8")
        self.assertEqual(CHECK_UPDATES.response_text(resp), "用户协议 隐私政策")

    def test_pdf_snapshot_is_treated_as_missing_text_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "demo", "main")
            os.makedirs(path)
            with open(os.path.join(path, "latest.txt"), "w", encoding="utf-8") as f:
                f.write("%PDF-1.7\nnot extracted")
            with mock.patch.object(CHECK_UPDATES, "SNAPSHOTS_DIR", directory):
                self.assertIsNone(CHECK_UPDATES.load_baseline_text("demo", "main"))

    def test_invalid_utf8_snapshot_is_treated_as_missing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "demo", "main")
            os.makedirs(path)
            with open(os.path.join(path, "latest.txt"), "wb") as f:
                f.write(b"\xff\xfe\x00")
            with mock.patch.object(CHECK_UPDATES, "SNAPSHOTS_DIR", directory):
                self.assertIsNone(CHECK_UPDATES.load_baseline_text("demo", "main"))

    def test_pdf_content_is_not_written_as_decoded_binary(self):
        resp = _FakeResponse("application/pdf", b"%PDF-1.7\ninvalid")
        with mock.patch.object(CHECK_UPDATES, "extract_pdf_text", return_value=""):
            self.assertEqual(CHECK_UPDATES.response_text(resp), "")

    def test_wrong_iso8859_declaration_is_repaired(self):
        resp = _FakeResponse("text/html; charset=ISO-8859-1", self.BODY)
        self.assertIn("用户协议", CHECK_UPDATES.response_text(resp))

    def test_main_content_is_preferred_over_navigation(self):
        raw = ("<html><body><nav>导航首页帮助</nav><main><p>用户内容用于训练的条款。</p>"
               "</main><footer>版权所有</footer></body></html>")
        text = CHECK_UPDATES.extract_text(raw)
        self.assertIn("用户内容用于训练的条款", text)
        self.assertNotIn("导航首页帮助", text)

    def test_long_number_in_policy_body_is_not_globally_removed(self):
        raw = "<html><body><main><p>政策编号 123456789012345678 的约定继续有效。</p></main></body></html>"
        text = CHECK_UPDATES.extract_text(raw)
        self.assertIn("123456789012345678", text)

    def test_anchor_early_in_body_does_not_truncate_legal_text(self):
        raw = ("<html><body><main><p>版权所有仍归用户。</p><p>训练和退出机制条款继续有效。</p>"
               "</main></body></html>")
        text = CHECK_UPDATES.extract_text(raw)
        self.assertIn("训练和退出机制条款继续有效", text)

    def test_language_dropdown_state_does_not_change_hash(self):
        """回归：chatgpt/tob 的语言下拉列表展开与否导致 15147 ↔ 15752 字波动，
        条款正文零差异。正文起始标记（Updated: YYYY年）之前的头部 UI 应被切掉。"""
        body = ("Updated: 2025年12月1日 生效日期：2026 年 1 月 1 日 "
                + "本协议约定了服务内容与数据使用。" * 400)
        collapsed = f"<html><body><main>OpenAI 服务协议 | OpenAI 输入语言 … {body}</main></body></html>"
        expanded = ("<html><body><main>OpenAI 服务协议 | OpenAI 输入语言 "
                    "English (United States) العربية ไทย 日本語 한국어 Português "
                    f"{body}</main></body></html>")
        text_collapsed = CHECK_UPDATES.extract_text(collapsed)
        text_expanded = CHECK_UPDATES.extract_text(expanded)
        self.assertNotEqual(collapsed, expanded, "两个样本应确实不同")
        self.assertEqual(
            CHECK_UPDATES.compute_text_hash(text_collapsed),
            CHECK_UPDATES.compute_text_hash(text_expanded))
        self.assertIn("本协议约定了服务内容", text_expanded)

    def test_lead_in_marker_keeps_chinese_title_and_update_date(self):
        """回归：曾把中文"生效日期："也当正文起始标记，导致腾讯系协议页开头的
        「文档标题 + 更新日期」被切掉（tencent-yuanbao 少 26 字符、ima 少 62、
        yuanqi 少 28）——这些字段是政策版本标识，必须保留。"""
        raw = ("<html><body><main>元宝用户服务协议 更新日期： 2025-12-06 "
               "生效日期： 2025-12-13 导言 1.关于本服务 2.账号注册与管理"
               + "本协议条款内容。" * 200 + "</main></body></html>")
        text = CHECK_UPDATES.extract_text(raw)
        self.assertIn("元宝用户服务协议", text)
        self.assertIn("更新日期： 2025-12-06", text)
        self.assertIn("导言", text)

    def test_guided_tour_overlay_does_not_change_hash(self):
        """回归：火山方舟文档站的新手引导浮层（我知道了 不再提醒）显示与否
        导致 doubao-api 11564 ↔ 11593 字波动。"""
        body = "火山方舟模型服务协议。" * 300
        with_overlay = f"<html><body><main>我知道了 不再提醒 {body}</main></body></html>"
        without = f"<html><body><main>{body}</main></body></html>"
        self.assertEqual(
            CHECK_UPDATES.compute_text_hash(CHECK_UPDATES.extract_text(with_overlay)),
            CHECK_UPDATES.compute_text_hash(CHECK_UPDATES.extract_text(without)))

    def test_lead_in_marker_guard_still_protects_late_mentions(self):
        """位置护栏：正文深处才出现"生效日期"时不得截断其前内容。"""
        body = "训练与数据使用条款继续有效。" * 100
        raw = f"<html><body><main>{body} 生效日期：2026 年 1 月 1 日</main></body></html>"
        text = CHECK_UPDATES.extract_text(raw)
        self.assertIn("训练与数据使用条款继续有效", text[:200])

    def test_hash_scheme_covers_extractor_variant(self):
        """哈希方案必须带提取器标识：bs4 与正则回退剥离的标签不同，
        若共用 scheme，一旦依赖缺失就会全库哈希漂移 → 批量误报。"""
        self.assertTrue(CHECK_UPDATES.HASH_SCHEME.startswith("text-v4-"))
        self.assertIn(CHECK_UPDATES.EXTRACTOR, CHECK_UPDATES.HASH_SCHEME)
        self.assertIn(CHECK_UPDATES.EXTRACTOR, ("bs4", "regex"))

    def test_min_body_chars_threshold_exists(self):
        """空壳正文（SPA 只返回标题）不能建基线，否则监控空转。"""
        self.assertIsInstance(CHECK_UPDATES.MIN_BODY_CHARS, int)
        self.assertGreaterEqual(CHECK_UPDATES.MIN_BODY_CHARS, 200)

    def test_304_without_baseline_is_not_accepted(self):
        response = _FakeResponse("text/html; charset=utf-8", b"unused", encoding="utf-8")
        previous = {
            "url": "https://example.com/policy",
            "hash_scheme": CHECK_UPDATES.HASH_SCHEME,
            "current_hash": "old",
            "content_etag": "old-etag",
        }
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=None):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry", return_value=(response, True)):
                result = CHECK_UPDATES.check_target(
                    "demo", "Demo", "main", "https://example.com/policy", previous, 1
                )
        self.assertEqual(result["status"], "suspicious")
        self.assertIsNone(result["current_hash"])

    def test_missing_baseline_disables_conditional_headers(self):
        body = ("<html><body><main>" + "政策正文用于测试训练、退出和留存。" * 40 +
                "</main></body></html>").encode("utf-8")
        response = _FakeResponse("text/html; charset=utf-8", body, encoding="utf-8")
        seen = {}

        def fake_fetch(url, etag, last_modified, timeout):
            seen["etag"] = etag
            seen["last_modified"] = last_modified
            return response, False

        previous = {
            "url": "https://example.com/policy",
            "hash_scheme": CHECK_UPDATES.HASH_SCHEME,
            "current_hash": "old",
            "content_etag": "old-etag",
        }
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=None):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry", side_effect=fake_fetch):
                with mock.patch.object(CHECK_UPDATES, "save_snapshot") as save:
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/policy", previous, 1
                    )
        self.assertIsNone(seen["etag"])
        self.assertIsNone(seen["last_modified"])
        self.assertEqual(result["status"], "suspicious")
        save.assert_called_once()

    def test_url_change_is_flagged_without_reusing_validators(self):
        body = ("<html><body><main>" + "新来源正文用于测试政策变化。" * 40 +
                "</main></body></html>").encode("utf-8")
        response = _FakeResponse("text/html; charset=utf-8", body, encoding="utf-8")
        seen = {}

        def fake_fetch(url, etag, last_modified, timeout):
            seen["etag"] = etag
            return response, False

        previous = {
            "url": "https://old.example.com/policy",
            "hash_scheme": CHECK_UPDATES.HASH_SCHEME,
            "current_hash": "old",
            "content_etag": "old-etag",
        }
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value="旧正文"):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry", side_effect=fake_fetch):
                with mock.patch.object(CHECK_UPDATES, "save_snapshot"):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://new.example.com/policy", previous, 1
                    )
        self.assertIsNone(seen["etag"])
        self.assertEqual(result["status"], "changed")

    def test_hash_scheme_change_rebuilds_snapshot_without_false_change(self):
        body = ("<html><body><main>" + "新提取器正文用于测试训练、退出和留存。" * 40 +
                "</main></body></html>").encode("utf-8")
        response = _FakeResponse("text/html; charset=utf-8", body, encoding="utf-8")
        previous = {
            "url": "https://example.com/policy",
            "hash_scheme": "old-scheme",
            "current_hash": "old",
            "content_etag": "old-etag",
        }
        baseline = CHECK_UPDATES.normalize_text(CHECK_UPDATES.extract_text(body.decode("utf-8")))
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=baseline):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry", return_value=(response, False)):
                with mock.patch.object(CHECK_UPDATES, "save_snapshot") as save:
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/policy", previous, 1
                    )
        self.assertEqual(result["status"], "ok")
        save.assert_called_once_with("demo", "main", mock.ANY, archived=False)


class TestMonitorState(unittest.TestCase):
    def test_fetch_url_rejects_non_https_and_private_targets(self):
        self.assertFalse(CHECK_UPDATES.safe_fetch_url("http://example.com/policy"))
        self.assertFalse(CHECK_UPDATES.safe_fetch_url("file:///etc/passwd"))
        self.assertFalse(CHECK_UPDATES.safe_fetch_url("https://127.0.0.1/policy"))
        self.assertFalse(CHECK_UPDATES.safe_fetch_url("https://169.254.169.254/latest/meta-data/"))
        self.assertTrue(CHECK_UPDATES.safe_fetch_url("https://8.8.8.8/policy"))

    def test_source_registry_adds_deduplicated_monitor_targets(self):
        policy = {
            "policy_url": "https://example.com/main",
            "versions": {"toc": {"policy_link": "https://example.com/terms"}},
            "sources": [
                {"id": "faq", "url": "https://example.com/faq"},
                {"id": "duplicate", "url": "https://example.com/faq"},
                {"id": "disabled", "url": "https://example.com/private", "monitored": False},
            ],
        }
        targets = CHECK_UPDATES.collect_targets(policy)
        self.assertEqual([key for key, _ in targets], ["main", "toc", "source_faq"])
        self.assertEqual(targets[-1][1], "https://example.com/faq")

    def test_pending_alert_is_reapplied_when_target_returns_ok(self):
        products = {
            "demo": {
                "status": "ok",
                "targets": {"main": {"status": "ok", "message": "内容未变化"}},
            }
        }
        pending = {
            "demo:main": {"pid": "demo", "key": "main"},
        }
        restored = CHECK_UPDATES.reapply_pending_alerts(products, pending)
        self.assertEqual(restored, 1)
        self.assertEqual(products["demo"]["targets"]["main"]["status"], "changed")
        self.assertEqual(products["demo"]["status"], "changed")

    def test_orphan_snapshot_directories_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            active = os.path.join(directory, "demo", "main")
            orphan = os.path.join(directory, "demo", "old")
            os.makedirs(active)
            os.makedirs(orphan)
            with open(os.path.join(orphan, "latest.txt"), "w", encoding="utf-8") as f:
                f.write("old")
            # 按配置判定：demo 只监控 main，old 已从配置里移除
            policies = {"demo": {"policy_url": "https://example.com/main"}}
            with mock.patch.object(CHECK_UPDATES, "SNAPSHOTS_DIR", directory):
                removed = CHECK_UPDATES.prune_orphan_snapshots(policies)
            self.assertEqual(removed, 1)
            self.assertTrue(os.path.isdir(active))
            self.assertFalse(os.path.exists(orphan))

    def test_prune_keeps_snapshots_of_targets_skipped_this_run(self):
        """回归：曾按"本轮状态里的 targets"判定活跃目标，导致本轮被跳过
        （--no-browser / monitor=false）的产品快照被当成孤儿删掉——
        快照是检测→核实回路唯一的持久历史，删掉等于让历史无法 diff。"""
        with tempfile.TemporaryDirectory() as directory:
            browser_dir = os.path.join(directory, "chatgpt", "main")
            off_dir = os.path.join(directory, "zread", "main")
            os.makedirs(browser_dir)
            os.makedirs(off_dir)
            for path in (browser_dir, off_dir):
                with open(os.path.join(path, "latest.txt"), "w", encoding="utf-8") as f:
                    f.write("x")
            policies = {
                # 本轮被 --no-browser 跳过，状态里没有 targets，但配置里仍是活跃目标
                "chatgpt": {"policy_url": "https://chatgpt.com/policy",
                            "fetch_method": "browser"},
                # monitor=false：明确不监控，快照应被清理
                "zread": {"policy_url": "https://zread.ai/policy", "monitor": False},
            }
            with mock.patch.object(CHECK_UPDATES, "SNAPSHOTS_DIR", directory):
                removed = CHECK_UPDATES.prune_orphan_snapshots(policies)
            self.assertEqual(removed, 1)
            self.assertTrue(os.path.isdir(browser_dir), "被跳过的浏览器目标快照被误删")
            self.assertFalse(os.path.exists(off_dir))

    def test_pending_queue_drops_targets_no_longer_monitored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "pending_verification.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"items": {
                    "demo:main": {"pid": "demo", "key": "main", "first_seen": "old"},
                    "removed:main": {"pid": "removed", "key": "main", "first_seen": "old"},
                }}, f)
            status = {"demo": {"name": "Demo", "targets": {"main": {"url": "https://e.com"}}}}
            with mock.patch.object(CHECK_UPDATES, "PENDING_FILE", path):
                items = CHECK_UPDATES.update_pending_verification(status)
            self.assertEqual(set(items), {"demo:main"})

    def test_pending_queue_uses_flat_products_mapping(self):
        """回归：入参是 {pid: info} 映射。若误传 {"products": {...}}，
        队列会被当成空状态重建，历史待核实项每轮被静默清空。"""
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "pending_verification.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"items": {
                    "other:main": {"pid": "other", "key": "main", "first_seen": "old"},
                }}, f)
            products = {"other": {"name": "Other", "status": "ok",
                                  "targets": {"main": {"status": "ok", "url": "https://e.com"}}}}
            with mock.patch.object(CHECK_UPDATES, "PENDING_FILE", path):
                items = CHECK_UPDATES.update_pending_verification(products)
            self.assertEqual(set(items), {"other:main"})
            self.assertEqual(items["other:main"]["url"], "https://e.com")

    def test_pending_queue_collects_changed_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "pending_verification.json")
            products = {"demo": {"name": "Demo", "status": "changed", "targets": {
                "main": {"status": "changed", "url": "https://e.com/p"},
                "tob": {"status": "ok", "url": "https://e.com/t"},
            }}}
            with mock.patch.object(CHECK_UPDATES, "PENDING_FILE", path):
                items = CHECK_UPDATES.update_pending_verification(products)
            self.assertEqual(set(items), {"demo:main"})
            self.assertEqual(items["demo:main"]["label"], "主监控页")

    def test_invalid_pending_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "site", "generated", "pending_verification.json")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json")
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as context:
                    POLICY_VERIFY.load_pending(directory)
            self.assertEqual(context.exception.code, 2)

    def test_all_targets_includes_normal_targets(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            POLICY_VERIFY.print_product(BASE_DIR, "trae", None, 1, 1, True)
        self.assertIn("目标 main", output.getvalue())
        self.assertIn("目标 tob", output.getvalue())


@unittest.skipIf(CHECK_UPDATES is None, "需要 requests 才能加载 check_updates.py")
class TestFetchHealth(unittest.TestCase):
    """抓取健康状态必须与"政策是否变化"分开：抓取坏了不能伪装成"未变化"。"""

    def _html(self, body, length=600):
        filler = "训练与退出机制条款。" * (length // 12)
        return f"<html><body><main><p>{body}</p><p>{filler}</p></main></body></html>"

    def _response(self, html):
        return _FakeResponse("text/html; charset=utf-8", html.encode("utf-8"),
                             encoding="utf-8")

    def test_first_baseline_is_initialized_not_suspicious(self):
        """首次建基线不是异常：标 initialized + status ok，避免首页长期误报可疑。"""
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=None):
            with mock.patch.object(CHECK_UPDATES, "save_snapshot"):
                with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                       return_value=(self._response(self._html("首次抓取。")), False)):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/p", {}, 1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["health"], "initialized")
        self.assertIsNotNone(result["last_good_at"])

    def test_empty_body_without_baseline_is_no_baseline(self):
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=None):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                   return_value=(self._response("<html><body>hi</body></html>"), False)):
                result = CHECK_UPDATES.check_target(
                    "demo", "Demo", "main", "https://example.com/p", {}, 1)
        self.assertEqual(result["status"], "suspicious")
        self.assertEqual(result["health"], "no_baseline")
        self.assertEqual(result["health_reason"], "empty_body")

    def test_empty_body_with_baseline_is_degraded_and_keeps_snapshot(self):
        baseline = "历史有效正文。" * 60
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=baseline):
            with mock.patch.object(CHECK_UPDATES, "save_snapshot") as save:
                with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                       return_value=(self._response("<html><body>hi</body></html>"), False)):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/p",
                        {"url": "https://example.com/p",
                         "hash_scheme": CHECK_UPDATES.HASH_SCHEME}, 1)
        self.assertEqual(result["status"], "suspicious")
        self.assertEqual(result["health"], "degraded")
        save.assert_not_called()  # 降级不覆盖上次有效快照
        self.assertIn("已保留上次有效快照", result["message"])

    def test_last_good_at_falls_back_to_snapshot_mtime(self):
        """旧状态文件没有 last_good_at：有基线的目标应回填快照保存时间，
        否则"已保留上次快照"却显示"从未成功抓取"，前后矛盾。"""
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "demo", "main")
            os.makedirs(target)
            with open(os.path.join(target, "latest.txt"), "w", encoding="utf-8") as f:
                f.write("历史有效正文。" * 60)
            with mock.patch.object(CHECK_UPDATES, "SNAPSHOTS_DIR", directory):
                saved = CHECK_UPDATES.baseline_saved_at("demo", "main")
                self.assertIsNotNone(saved)
                with mock.patch.object(
                        CHECK_UPDATES, "fetch_with_retry",
                        return_value=(self._response("<html><body>hi</body></html>"), False)):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/p",
                        {"url": "https://example.com/p",
                         "hash_scheme": CHECK_UPDATES.HASH_SCHEME}, 1)
        self.assertEqual(result["status"], "suspicious")
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["last_good_at"], saved)

    def test_http_403_is_blocked(self):
        error = CHECK_UPDATES.requests.exceptions.HTTPError("403 Forbidden")
        error.response = _FakeResponse("text/html", b"")
        error.response.status_code = 403
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value="历史正文。" * 80):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry", side_effect=error):
                result = CHECK_UPDATES.check_target(
                    "demo", "Demo", "main", "https://example.com/p",
                    {"url": "https://example.com/p",
                     "hash_scheme": CHECK_UPDATES.HASH_SCHEME}, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["health"], "blocked")
        self.assertEqual(result["health_reason"], "blocked")

    def test_network_failure_degrades_instead_of_claiming_unchanged(self):
        error = CHECK_UPDATES.requests.exceptions.ConnectTimeout("timed out")
        previous = {"url": "https://example.com/p",
                    "hash_scheme": CHECK_UPDATES.HASH_SCHEME,
                    "last_good_at": "2026-01-01T00:00:00"}
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value="历史正文。" * 80):
            with mock.patch.object(CHECK_UPDATES, "fetch_with_retry", side_effect=error):
                result = CHECK_UPDATES.check_target(
                    "demo", "Demo", "main", "https://example.com/p", previous, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["last_good_at"], "2026-01-01T00:00:00")

    def test_content_change_stays_healthy(self):
        """正文变化是内容事件，不应被记为抓取故障（避免污染健康队列）。"""
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value="旧正文。" * 80):
            with mock.patch.object(CHECK_UPDATES, "save_snapshot"):
                with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                       return_value=(self._response(self._html("全新条款。")), False)):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/p",
                        {"url": "https://example.com/p",
                         "hash_scheme": CHECK_UPDATES.HASH_SCHEME}, 1)
        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["health"], "ok")

    def test_content_selector_overrides_main_heuristic(self):
        raw = ("<html><body><main>导航壳子内容</main>"
               "<div class='policy-doc'>真正的政策正文在这里。</div></body></html>")
        text = CHECK_UPDATES.extract_text(raw, content_selector=".policy-doc")
        self.assertIn("真正的政策正文", text)
        self.assertNotIn("导航壳子内容", text)

    def _fixture(self, name):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", name)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_real_empty_shell_fixture_is_classified_empty_body(self):
        """真实 JS 空壳样本：去噪后可见正文为 0，必须判 empty_body 且不覆盖基线。"""
        raw = self._fixture("empty_shell.html")
        text = CHECK_UPDATES.normalize_text(CHECK_UPDATES.extract_text(raw))
        self.assertLess(len(text), 50, f"样本应几乎无正文，实际 {len(text)} 字符")
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text",
                               return_value="历史有效正文。" * 80):
            with mock.patch.object(CHECK_UPDATES, "save_snapshot") as save:
                with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                       return_value=(self._response(raw), False)):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/doc",
                        {"url": "https://example.com/doc",
                         "hash_scheme": CHECK_UPDATES.HASH_SCHEME}, 1)
        self.assertEqual(result["status"], "suspicious")
        self.assertEqual(result["health"], "degraded")
        self.assertEqual(result["health_reason"], "empty_body")
        save.assert_not_called()

    def test_real_challenge_shell_fixture_is_classified_render_required(self):
        """真实挑战页样本：有少量文案但远低于下限，判 render_required 而非 empty_body。"""
        raw = self._fixture("render_required_shell.html")
        text = CHECK_UPDATES.normalize_text(CHECK_UPDATES.extract_text(raw))
        self.assertGreaterEqual(len(text), 50)
        self.assertLess(len(text), CHECK_UPDATES.MIN_BODY_CHARS)
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=None):
            with mock.patch.object(CHECK_UPDATES, "save_snapshot"):
                with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                       return_value=(self._response(raw), False)):
                    result = CHECK_UPDATES.check_target(
                        "demo", "Demo", "main", "https://example.com/verify", {}, 1)
        self.assertEqual(result["health_reason"], "render_required")
        self.assertEqual(result["health"], "no_baseline")

    def test_content_selector_recovers_body_from_real_shell_fixture(self):
        """目标级 content_selector 的真实用途：正文容器已知时能从空壳里取到正文。"""
        raw = self._fixture("empty_shell.html").replace(
            '<div class="doc-loading">正在加载文档…</div>',
            '<div class="doc-body">一、我们收集的信息。二、我们如何使用数据。'
            '三、模型训练与优化。四、您的权利。</div>')
        text = CHECK_UPDATES.normalize_text(
            CHECK_UPDATES.extract_text(raw, content_selector=".doc-body"))
        self.assertIn("我们如何使用数据", text)
        self.assertNotIn("京公网安备", text)

    def test_unknown_selector_falls_back_instead_of_empty(self):
        raw = "<html><body><main><p>兜底正文仍然可用。</p></main></body></html>"
        text = CHECK_UPDATES.extract_text(raw, content_selector=".not-exists")
        self.assertIn("兜底正文仍然可用", text)

    def test_target_level_fetch_config_overrides_product_level(self):
        policy = {"policy_url": "https://example.com/main", "fetch_method": "requests",
                  "sources": [{"id": "faq", "url": "https://example.com/faq",
                               "fetch_method": "browser", "wait_for_selector": ".doc",
                               "min_body_chars": 1200}]}
        specs = {spec["key"]: spec for spec in CHECK_UPDATES.collect_target_specs(policy)}
        self.assertEqual(specs["main"]["method"], "requests")
        self.assertEqual(specs["source_faq"]["method"], "browser")
        self.assertEqual(specs["source_faq"]["wait_for_selector"], ".doc")
        self.assertEqual(specs["source_faq"]["min_body_chars"], 1200)

    def test_main_target_has_its_own_config_carrier(self):
        """main 的 URL(policy_url) 在顶层，天然没有内层对象可挂配置。
        targets.main 补上这个唯一缺失的载体，使"每个目标都能独立配置"没有例外。"""
        policy = {"policy_url": "https://example.com/main", "fetch_method": "requests",
                  "versions": {"toc": {"policy_link": "https://example.com/toc"}},
                  "targets": {"main": {"fetch_method": "browser",
                                       "content_selector": ".legal-doc"}}}
        specs = {spec["key"]: spec for spec in CHECK_UPDATES.collect_target_specs(policy)}
        self.assertEqual(specs["main"]["method"], "browser")
        self.assertEqual(specs["main"]["content_selector"], ".legal-doc")
        # 顶层 fetch_method 仍对其他目标生效（向后兼容）
        self.assertEqual(specs["toc"]["method"], "requests")

    def test_main_target_still_accepts_top_level_config(self):
        """既有数据文件的顶层 fetch_method 必须继续生效，不能因新增载体而失效。"""
        policy = {"policy_url": "https://example.com/main", "fetch_method": "browser"}
        specs = {spec["key"]: spec for spec in CHECK_UPDATES.collect_target_specs(policy)}
        self.assertEqual(specs["main"]["method"], "browser")

    def test_main_carrier_does_not_leak_into_other_targets(self):
        """main 需要 browser、toc 是静态页时，两者必须能独立配置。"""
        policy = {"policy_url": "https://example.com/main",
                  "versions": {"toc": {"policy_link": "https://example.com/toc"}},
                  "targets": {"main": {"fetch_method": "browser"}}}
        specs = {spec["key"]: spec for spec in CHECK_UPDATES.collect_target_specs(policy)}
        self.assertEqual(specs["main"]["method"], "browser")
        self.assertEqual(specs["toc"]["method"], "requests")

    def test_malformed_main_carrier_falls_back_to_top_level(self):
        """targets 结构异常时不崩溃，退回顶层配置（validate_data 会另行报错）。"""
        for broken in ([], {"main": "browser"}, {"toc": {"fetch_method": "browser"}}, "x"):
            policy = {"policy_url": "https://example.com/main",
                      "fetch_method": "requests", "targets": broken}
            specs = {spec["key"]: spec for spec in CHECK_UPDATES.collect_target_specs(policy)}
            self.assertEqual(specs["main"]["method"], "requests", f"targets={broken!r}")

    def test_no_browser_only_skips_browser_targets(self):
        policy = {"policy_url": "https://example.com/main",
                  "sources": [{"id": "faq", "url": "https://example.com/faq",
                               "fetch_method": "browser"}]}
        html = self._html("可抓取正文。")
        with mock.patch.object(CHECK_UPDATES, "load_baseline_text", return_value=None):
            with mock.patch.object(CHECK_UPDATES, "save_snapshot"):
                with mock.patch.object(CHECK_UPDATES, "fetch_with_retry",
                                       return_value=(self._response(html), False)):
                    result = CHECK_UPDATES.check_product(
                        "demo", policy, {}, 1, 0, no_browser=True)
        self.assertEqual(sorted(result["targets"]), ["main"])
        self.assertEqual(result["status"], "ok")

    def test_no_browser_keeps_previous_results_of_browser_only_product(self):
        """回归：整产品都需浏览器时若直接清空 targets，本地无 playwright 的一次运行
        会把 CI 建立的监控覆盖从状态文件里抹掉（total_targets 缩水、覆盖被低估）。"""
        policy = {"policy_url": "https://example.com/main", "fetch_method": "browser"}
        prev = {"targets": {"main": {"url": "https://example.com/main", "status": "ok",
                                     "health": "ok", "current_hash": "abc",
                                     "last_good_at": "2026-01-01T00:00:00"}}}
        with contextlib.redirect_stdout(io.StringIO()):
            result = CHECK_UPDATES.check_product(
                "demo", policy, prev, 1, 0, no_browser=True)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["targets"]["main"]["current_hash"], "abc")
        self.assertTrue(result["targets"]["main"]["skipped_this_run"])
        self.assertEqual(result["targets"]["main"]["last_good_at"], "2026-01-01T00:00:00")
        # 沿用的目标不算"本轮抓取降级"，不应凭空进健康队列
        self.assertEqual(result["health"], "ok")
        self.assertEqual(result["health_issues"], 0)


@unittest.skipIf(CHECK_UPDATES is None, "需要 requests 才能加载 check_updates.py")
class TestMonitorHealthQueue(unittest.TestCase):
    """健康队列：抓取坏了但政策没变时，必须有独立于待核实队列的可见信号。"""

    def _status(self, health, status="suspicious", message="抓取正文过短"):
        return {"demo": {"name": "Demo", "targets": {
            "main": {"url": "https://example.com/p", "health": health,
                     "status": status, "message": message,
                     "last_checked": "2026-01-02T00:00:00",
                     "last_good_at": "2026-01-01T00:00:00"}}}}

    def test_degraded_target_enters_health_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "monitor_health.json")
            with mock.patch.object(CHECK_UPDATES, "HEALTH_FILE", path):
                items = CHECK_UPDATES.update_monitor_health(self._status("degraded"))
            self.assertEqual(list(items), ["demo:main"])
            item = items["demo:main"]
            self.assertEqual(item["health"], "degraded")
            self.assertEqual(item["consecutive_runs"], 1)
            self.assertEqual(item["last_good_at"], "2026-01-01T00:00:00")
            self.assertTrue(item["next_action"])

    def test_healthy_target_is_not_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "monitor_health.json")
            with mock.patch.object(CHECK_UPDATES, "HEALTH_FILE", path):
                items = CHECK_UPDATES.update_monitor_health(self._status("ok", status="ok"))
            self.assertEqual(items, {})

    def test_initialized_and_rebaselined_are_not_queued(self):
        for health in ("initialized", "rebaselined"):
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, "monitor_health.json")
                with mock.patch.object(CHECK_UPDATES, "HEALTH_FILE", path):
                    items = CHECK_UPDATES.update_monitor_health(self._status(health, status="ok"))
                self.assertEqual(items, {}, f"{health} 不应进入健康队列")

    def test_recovered_target_leaves_queue_and_resets_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "monitor_health.json")
            with mock.patch.object(CHECK_UPDATES, "HEALTH_FILE", path):
                CHECK_UPDATES.update_monitor_health(self._status("degraded"))
                # 第二轮仍坏：连续计数累加
                items = CHECK_UPDATES.update_monitor_health(self._status("degraded"))
                self.assertEqual(items["demo:main"]["consecutive_runs"], 2)
                # 恢复：条目应消失
                items = CHECK_UPDATES.update_monitor_health(self._status("ok", status="ok"))
                self.assertEqual(items, {})
                # 再坏：重新从 1 开始
                items = CHECK_UPDATES.update_monitor_health(self._status("no_baseline"))
                self.assertEqual(items["demo:main"]["consecutive_runs"], 1)

    def test_corrupt_health_file_is_rebuilt_not_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "monitor_health.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json")
            with mock.patch.object(CHECK_UPDATES, "HEALTH_FILE", path):
                with contextlib.redirect_stdout(io.StringIO()):
                    items = CHECK_UPDATES.update_monitor_health(self._status("blocked"))
            self.assertEqual(list(items), ["demo:main"])


class TestPartialRetry(unittest.TestCase):
    """局部重试：只重跑一个目标，不能把其他目标的历史结果冲掉。"""

    def test_merge_partial_product_keeps_untouched_targets(self):
        previous = {
            "name": "Demo", "status": "failed", "url": "https://example.com/main",
            "message": "旧", "last_checked": "2026-01-01T00:00:00",
            "targets": {
                "main": {"status": "ok", "health": "ok", "message": "内容未变化"},
                "tob": {"status": "failed", "health": "no_baseline", "message": "失败"},
            },
        }
        new = {"name": "Demo", "url": "https://example.com/main",
               "last_checked": "2026-01-02T00:00:00",
               "targets": {"tob": {"status": "ok", "health": "ok", "message": "内容未变化"}}}
        merged = CHECK_UPDATES.merge_partial_product(previous, new)
        self.assertEqual(sorted(merged["targets"]), ["main", "tob"])
        self.assertEqual(merged["status"], "ok")
        self.assertEqual(merged["message"], "内容未变化")
        # 原始入参不应被就地改写
        self.assertEqual(previous["status"], "failed")

    def test_merge_partial_product_keeps_health_issue_of_other_target(self):
        previous = {"name": "Demo", "targets": {
            "main": {"status": "suspicious", "health": "no_baseline", "message": "空壳"},
            "tob": {"status": "failed", "health": "degraded", "message": "超时"}}}
        new = {"name": "Demo", "targets": {
            "tob": {"status": "ok", "health": "ok", "message": "内容未变化"}}}
        merged = CHECK_UPDATES.merge_partial_product(previous, new)
        self.assertEqual(merged["status"], "suspicious")
        self.assertEqual(merged["health"], "no_baseline")
        self.assertEqual(merged["health_issues"], 1)

    def test_aggregate_reports_health_issue_count(self):
        targets = {
            "main": {"status": "ok", "health": "ok"},
            "tob": {"status": "suspicious", "health": "degraded"},
        }
        status, summary, unhealthy = CHECK_UPDATES.aggregate_targets(targets)
        self.assertEqual(status, "suspicious")
        self.assertEqual(unhealthy, 1)
        self.assertIn("抓取降级", summary)
        self.assertEqual(CHECK_UPDATES.aggregate_health(targets), "degraded")

    def test_aggregate_health_prefers_most_severe(self):
        targets = {
            "main": {"status": "failed", "health": "degraded"},
            "tob": {"status": "failed", "health": "blocked"},
        }
        self.assertEqual(CHECK_UPDATES.aggregate_health(targets), "blocked")

    def test_only_filter_keeps_requested_targets(self):
        policy = {"policy_url": "https://example.com/main",
                  "versions": {"toc": {"policy_link": "https://example.com/toc"}}}
        result = CHECK_UPDATES.check_product("demo", policy, {}, 1, 0, only_keys=["toc"])
        self.assertEqual(list(result["targets"]), ["toc"])

    def test_unsupported_fetch_method_is_blocked_health(self):
        policy = {"policy_url": "https://example.com/main", "fetch_method": "selenium"}
        result = CHECK_UPDATES.check_product("demo", policy, {}, 1, 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["health"], "blocked")

    def _run_main(self, argv, prev_products, policies, checked):
        """以受控替身运行 main()，返回 (退出码, 写出的 status 数据)。"""
        with tempfile.TemporaryDirectory() as directory:
            status_path = os.path.join(directory, "update_status.json")
            pending_path = os.path.join(directory, "pending_verification.json")
            health_path = os.path.join(directory, "monitor_health.json")

            def fake_check_product(pid, policy, prev, timeout, delay,
                                   no_browser=False, only_keys=None):
                checked.append((pid, only_keys))
                return {"name": pid, "status": "ok", "health": "ok", "health_issues": 0,
                        "url": policy.get("policy_url", ""), "message": "内容未变化",
                        "last_checked": "2026-01-02T00:00:00",
                        "targets": {"main": {"url": policy.get("policy_url", ""),
                                             "status": "ok", "health": "ok"}}}

            with mock.patch.object(CHECK_UPDATES, "STATUS_FILE", status_path), \
                 mock.patch.object(CHECK_UPDATES, "PENDING_FILE", pending_path), \
                 mock.patch.object(CHECK_UPDATES, "HEALTH_FILE", health_path), \
                 mock.patch.object(CHECK_UPDATES, "load_product_ids",
                                   return_value=list(policies)), \
                 mock.patch.object(CHECK_UPDATES, "load_previous_status",
                                   return_value={"products": prev_products}), \
                 mock.patch.object(CHECK_UPDATES, "load_policy",
                                   side_effect=lambda pid: policies[pid]), \
                 mock.patch.object(CHECK_UPDATES, "check_product", fake_check_product), \
                 mock.patch.object(CHECK_UPDATES, "prune_orphan_snapshots", return_value=0), \
                 mock.patch.object(sys, "argv", ["check_updates.py"] + argv):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = CHECK_UPDATES.main()
            if not os.path.exists(status_path):
                return code, {}
            with open(status_path, encoding="utf-8") as f:
                return code, json.load(f)

    def test_only_rechecks_single_target_and_keeps_other_products(self):
        prev = {
            "alpha": {"name": "A", "status": "failed", "url": "https://a.com",
                      "targets": {"main": {"status": "failed", "health": "degraded",
                                           "url": "https://a.com"}}},
            "beta": {"name": "B", "status": "ok", "url": "https://b.com",
                     "targets": {"main": {"status": "ok", "health": "ok",
                                          "url": "https://b.com"}}},
        }
        policies = {"alpha": {"policy_url": "https://a.com"},
                    "beta": {"policy_url": "https://b.com"}}
        checked = []
        code, data = self._run_main(["--only", "alpha:main"], prev, policies, checked)
        self.assertEqual(checked, [("alpha", {"main"})])  # 只检查了 alpha 的 main
        self.assertTrue(data["meta"]["partial_run"])
        self.assertEqual(data["products"]["alpha"]["status"], "ok")
        # 未检查的产品保持原样，且不被清空
        self.assertEqual(data["products"]["beta"]["status"], "ok")
        self.assertEqual(data["meta"]["total_targets"], 2)

    def test_products_flag_does_not_prune_orphan_snapshots(self):
        policies = {"alpha": {"policy_url": "https://a.com"}}
        prev = {"alpha": {"name": "A", "status": "ok", "url": "https://a.com",
                          "targets": {"main": {"status": "ok", "health": "ok"}}}}
        with mock.patch.object(CHECK_UPDATES, "prune_orphan_snapshots") as prune:
            checked = []
            with tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(CHECK_UPDATES, "STATUS_FILE",
                                       os.path.join(directory, "s.json")), \
                     mock.patch.object(CHECK_UPDATES, "PENDING_FILE",
                                       os.path.join(directory, "p.json")), \
                     mock.patch.object(CHECK_UPDATES, "HEALTH_FILE",
                                       os.path.join(directory, "h.json")), \
                     mock.patch.object(CHECK_UPDATES, "load_product_ids",
                                       return_value=["alpha"]), \
                     mock.patch.object(CHECK_UPDATES, "load_previous_status",
                                       return_value={"products": prev}), \
                     mock.patch.object(CHECK_UPDATES, "load_policy",
                                       return_value=policies["alpha"]), \
                     mock.patch.object(CHECK_UPDATES, "check_product",
                                       side_effect=lambda pid, *a, **kw: {
                                           "name": "A", "status": "ok", "health": "ok",
                                           "health_issues": 0, "url": "https://a.com",
                                           "message": "内容未变化",
                                           "targets": {"main": {"status": "ok",
                                                                "health": "ok"}}}), \
                     mock.patch.object(sys, "argv", ["check_updates.py", "--products", "alpha"]):
                    with contextlib.redirect_stdout(io.StringIO()):
                        CHECK_UPDATES.main()
        prune.assert_not_called()

    def test_unknown_only_target_product_is_rejected(self):
        policies = {"alpha": {"policy_url": "https://a.com"}}
        code, _ = self._run_main(["--only", "nope:main"], {}, policies, [])
        self.assertEqual(code, 2)

    def test_only_requires_pid_key_format(self):
        policies = {"alpha": {"policy_url": "https://a.com"}}
        code, _ = self._run_main(["--only", "alpha"], {}, policies, [])
        self.assertEqual(code, 2)

    def test_browser_render_always_takes_all_attempts(self):
        """回归：曾用"正文超过固定阈值就提前退出"来省时间。
        各页面完整正文长度差异极大（实测同页 9500 / 56422 字符两种结果），
        固定阈值会把渲染未完成的中间态写进基线，之后每轮都误报 changed。"""
        self.assertGreaterEqual(CHECK_UPDATES.BROWSER_RENDER_ATTEMPTS, 3)
        source = open(CHECK_UPDATES.__file__, encoding="utf-8").read()
        fetch_browser_src = source.split("def fetch_browser(")[1].split("\ndef ")[0]
        self.assertNotIn("break", fetch_browser_src,
                         "fetch_browser 不应再按长度提前退出渲染重试")

    def test_browser_picks_longest_render(self):
        """三次渲染取正文最长的一次：残缺渲染不得污染基线。"""
        best, length = CHECK_UPDATES.pick_longest_render(
            [(100, "<p>壳</p>"), (56422, "<p>完整协议</p>"), (9500, "<p>半截</p>")])
        self.assertEqual(best, "<p>完整协议</p>")
        self.assertEqual(length, 56422)

    def test_browser_picks_longest_when_all_renders_are_shells(self):
        best, length = CHECK_UPDATES.pick_longest_render([(0, "<p></p>"), (12, "<p>x</p>")])
        self.assertEqual(best, "<p>x</p>")
        self.assertEqual(length, 12)

    def test_browser_picks_longest_with_empty_render_list(self):
        self.assertEqual(CHECK_UPDATES.pick_longest_render([]), (None, -1))

    def test_unreachable_host_stops_retrying_after_budget(self):
        """域名整体不可达时（受限网络下的境外政策站点）必须有墙钟预算，
        否则单个死目标的重试会吃掉整轮监控的时间预算。"""
        calls = []
        budget = CHECK_UPDATES.RETRY_BUDGET_SECONDS

        def always_timeout(url, etag, last_modified, timeout):
            calls.append(1)
            raise CHECK_UPDATES.requests.exceptions.ConnectTimeout("timed out")

        # 第一次 monotonic（记录起点）返回 0，第二次（检查预算）返回已超预算
        with mock.patch.object(CHECK_UPDATES, "fetch_url", always_timeout), \
             mock.patch.object(CHECK_UPDATES.time, "sleep", lambda s: None), \
             mock.patch.object(CHECK_UPDATES.time, "monotonic",
                               side_effect=[0.0, budget + 1]):
            with self.assertRaises(CHECK_UPDATES.requests.exceptions.ConnectTimeout):
                CHECK_UPDATES.fetch_with_retry("https://unreachable.example/p", None, None, 5)
        self.assertEqual(len(calls), 1, "超出预算后不应继续重试")

    def test_connect_timeout_is_capped(self):
        """requests 会按解析出的每个地址依次连接，必须单独收紧连接阶段超时。"""
        self.assertLessEqual(CHECK_UPDATES.CONNECT_TIMEOUT_CAP, 10)
        self.assertGreater(CHECK_UPDATES.CONNECT_TIMEOUT_CAP, 0)


class TestSiteConsistency(unittest.TestCase):
    """站点层面的跨文件一致性——这几项都是此前真实出过问题的地方。"""

    HTML_LINK = re.compile(r'(?:href|src)="([^"]+)"')
    VERSION = re.compile(r"\?v=(\d{8}-\d+)")

    def html_files(self):
        files = []
        for root, dirs, names in os.walk(SITE_DIR):
            dirs[:] = [d for d in dirs if d != "internal"]  # 内部底稿不发布
            files.extend(os.path.join(root, n) for n in names if n.endswith(".html"))
        return files

    def test_local_links_resolve(self):
        """docs 页曾引用 ../site/css/style.css，部署后是死链 → 页面无样式。"""
        broken = []
        for path in self.html_files():
            with open(path, encoding="utf-8") as f:
                content = f.read()
            for target in self.HTML_LINK.findall(content):
                if target.startswith(("http://", "https://", "data:", "mailto:", "#")):
                    continue
                resolved = os.path.normpath(
                    os.path.join(os.path.dirname(path), target.split("?")[0]))
                if not os.path.exists(resolved):
                    broken.append(f"{os.path.relpath(path, BASE_DIR)} -> {target}")
        self.assertEqual(broken, [], f"无法解析的资源引用：{broken}")

    def test_asset_version_is_consistent(self):
        """同一份 CSS/JS 不能有两个版本号：会重复下载，也可能命中旧缓存导致详情页报错。"""
        versions = set()
        for path in self.html_files():
            with open(path, encoding="utf-8") as f:
                versions.update(self.VERSION.findall(f.read()))
        self.assertEqual(len(versions), 1, f"资源版本号不统一：{sorted(versions)}")

    def test_sitemap_matches_products(self):
        with open(os.path.join(SITE_DIR, "sitemap.xml"), encoding="utf-8") as f:
            sitemap_ids = set(re.findall(r"detail\.html\?id=([a-z0-9-]+)", f.read()))
        with open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8") as f:
            data_ids = set(json.load(f)["products"])
        self.assertEqual(sitemap_ids, data_ids, "sitemap 与 products.json 产品 id 不一致")

    def test_public_product_counts_match_data(self):
        index = load_json(os.path.join(DATA_DIR, "products.json"))
        count = len(index["products"])
        version_count = sum(
            len((load_json(os.path.join(POLICIES_DIR, pid + ".json")).get("versions") or {}))
            for pid in index["products"]
        )
        for filename in ("README.md", "README.en.md", "site/index.html", "site/docs/methodology.md"):
            with open(os.path.join(BASE_DIR, filename), encoding="utf-8") as f:
                content = f.read()
            self.assertIn(str(count), content, f"{filename} 未同步产品数量")
        with open(os.path.join(BASE_DIR, "README.en.md"), encoding="utf-8") as f:
            self.assertIn(str(version_count), f.read())

    def test_deploy_workflow_names_match(self):
        """deploy.yml 的 workflow_run.workflows 必须与 ci/monitor 的 name 完全一致。"""
        wf_dir = os.path.join(BASE_DIR, ".github", "workflows")

        def name_of(filename):
            with open(os.path.join(wf_dir, filename), encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^name:\s*(.+?)\s*$", line)
                    if m:
                        return m.group(1)
            return None

        with open(os.path.join(wf_dir, "deploy.yml"), encoding="utf-8") as f:
            deploy = f.read()
        block = re.search(r"workflows:\s*\[([^\]]*)\]", deploy)
        self.assertIsNotNone(block, "deploy.yml 缺少 workflow_run.workflows")
        referenced = set(re.findall(r'"([^"]+)"', block.group(1)))
        expected = {name_of("ci.yml"), name_of("monitor.yml")}
        self.assertEqual(referenced, expected,
                         f"部署触发的工作流名不匹配：引用 {referenced}，实际 {expected}")

    def test_bundle_is_slim_and_complete(self):
        """bundle 只服务首页，不应携带长条款原文；但产品数必须与索引一致。"""
        with open(os.path.join(BASE_DIR, "site", "generated", "bundle.json"), encoding="utf-8") as f:
            bundle = json.load(f)
        with open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8") as f:
            ids = json.load(f)["products"]
        self.assertEqual([p["id"] for p in bundle["policies"]], ids)
        for policy in bundle["policies"]:
            for version in (policy.get("versions") or {}).values():
                self.assertNotIn("key_clauses", version, "bundle 不应包含长条款原文")
                self.assertIn("training_status", version)
                self.assertIn(version["training_status"], {
                    "explicit_no", "default_off_opt_in", "default_on_opt_out",
                    "explicit_yes", "unknown", "inferred",
                })

    def test_bundle_values_match_source_data(self):
        with open(os.path.join(BASE_DIR, "site", "generated", "bundle.json"), encoding="utf-8") as f:
            bundle = json.load(f)
        with open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8") as f:
            source_ids = json.load(f)["products"]
        source_by_id = {
            pid: load_json(os.path.join(POLICIES_DIR, pid + ".json")) for pid in source_ids
        }
        bundle_module = load_script("gen_data_bundle")
        top_fields = ("name", "company", "region", "icon", "toc_note", "tob_note")
        version_fields = ("label", "used_for_training", "training_status", "opt_out",
                          "deidentified", "data_retention", "risk_level")
        for slim in bundle["policies"]:
            source = source_by_id[slim["id"]]
            for field in top_fields:
                self.assertEqual(slim.get(field), source.get(field))
            for tier in ("toc", "tob"):
                source_version = (source.get("versions") or {}).get(tier) or {}
                slim_version = (slim.get("versions") or {}).get(tier) or {}
                if not source_version and not slim_version:
                    continue
                for field in version_fields:
                    expected = source_version.get(field)
                    if field == "training_status":
                        expected = bundle_module.infer_training_status(source_version)
                    self.assertEqual(slim_version.get(field), expected)

    def test_published_docs_have_no_stale_wording(self):
        """文档页须反映新流程：提及本地 skill，不得残留 analyze_changes/change_reports/未来功能。"""
        path = os.path.join(SITE_DIR, "docs", "update-monitoring.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("未来功能", content)
        self.assertNotIn("analyze_changes", content)
        self.assertNotIn("change_reports", content)
        self.assertIn("policy-change-verify", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
