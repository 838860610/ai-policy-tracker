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
import json
import os
import re
import sys
import unittest
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

    def test_policy_url_is_http(self):
        for pid, data in self.policies.items():
            self.assertTrue(str(data["policy_url"]).startswith(("http://", "https://")),
                            f"{pid}.policy_url 应以 http(s):// 开头")

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
        self.assertIn("| A | 腾讯 | ✅ 是 | ✅ 支持 | ❌ 否 | 🔴 高 |", table)
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
        self.assertNotIn("data/bundle.json", app)

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

    def test_wrong_iso8859_declaration_is_repaired(self):
        resp = _FakeResponse("text/html; charset=ISO-8859-1", self.BODY)
        self.assertIn("用户协议", CHECK_UPDATES.response_text(resp))

    def test_hash_scheme_covers_extractor_variant(self):
        """哈希方案必须带提取器标识：bs4 与正则回退剥离的标签不同，
        若共用 scheme，一旦依赖缺失就会全库哈希漂移 → 批量误报。"""
        self.assertTrue(CHECK_UPDATES.HASH_SCHEME.startswith("text-v3-"))
        self.assertIn(CHECK_UPDATES.EXTRACTOR, CHECK_UPDATES.HASH_SCHEME)
        self.assertIn(CHECK_UPDATES.EXTRACTOR, ("bs4", "regex"))

    def test_min_body_chars_threshold_exists(self):
        """空壳正文（SPA 只返回标题）不能建基线，否则监控空转。"""
        self.assertIsInstance(CHECK_UPDATES.MIN_BODY_CHARS, int)
        self.assertGreaterEqual(CHECK_UPDATES.MIN_BODY_CHARS, 200)


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
