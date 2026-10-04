"""报告页测试：自包含、数字来自输出文件、两次渲染逐字节相同。"""

from __future__ import annotations

import re
import unittest

from segmerge.page import generate_page
from .common import SAMPLES_ROOT, TempDirTestCase


class PageTest(TempDirTestCase):
    def render(self, name="page.html"):
        workdir = str(self.tmp / "var")
        out_html = self.tmp / name
        results = generate_page(str(SAMPLES_ROOT), str(out_html), workdir)
        return out_html.read_text(encoding="utf-8"), results

    def test_summary_and_sections(self):
        text, results = self.render()
        self.assertTrue(all(result.ok for result in results))
        self.assertIn("负载 15 份", text)
        self.assertIn("通过 15 份", text)
        self.assertIn("总步数 277", text)
        for name in ("01-overwrite", "05-scale", "15-churn"):
            self.assertIn(name, text)

    def test_self_contained_no_external_refs(self):
        text, _ = self.render()
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("<script", text.lower())
        self.assertNotIn("src=", text)
        self.assertIn("<style>", text)

    def test_contains_layout_rects_and_thresholds(self):
        text, _ = self.render()
        self.assertGreater(text.count("<rect"), 50)
        self.assertIn('stroke-dasharray="5 3"', text)
        self.assertIn("<polyline", text)
        self.assertIn("墓碑占比", text)

    def test_deterministic(self):
        first, _ = self.render("a.html")
        second, _ = self.render("b.html")
        self.assertEqual(first, second)

    def test_no_raw_bytes_shuffled(self):
        text, _ = self.render()
        self.assertTrue(text.startswith("<!DOCTYPE html>"))
        self.assertTrue(re.search(r"</html>\s*$", text))


if __name__ == "__main__":
    unittest.main()
