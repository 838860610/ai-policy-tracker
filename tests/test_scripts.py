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
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
DATA_DIR = os.path.join(BASE_DIR, "data")
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
            path = os.path.join(BASE_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                refs.update(self.DOC_LINK.findall(f.read()))
        self.assertTrue(refs, "未在站点文件中找到任何 docs 引用，测试本身可能失效")
        for ref in refs:
            self.assertTrue(os.path.exists(os.path.join(BASE_DIR, ref)),
                            f"{ref} 被站点引用但文件不存在（线上会 404）")

    def test_internal_docs_not_referenced(self):
        """docs/internal/ 已被 .gitignore 忽略，站点不得引用其中的文件。"""
        for name in self.REFERENCING_FILES:
            path = os.path.join(BASE_DIR, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("docs/internal/", f.read(),
                                 f"{name} 引用了被忽略的 docs/internal/ 内容")

    def test_gitignore_does_not_ignore_published_docs(self):
        with open(os.path.join(BASE_DIR, ".gitignore"), encoding="utf-8") as f:
            gitignore = f.read()
        self.assertNotIn("docs/*", gitignore, "docs/* 会整体忽略发布页面，导致线上死链")
        self.assertIn("docs/internal/", gitignore)


if __name__ == "__main__":
    unittest.main(verbosity=2)
