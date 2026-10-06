from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from segmerge import checker, page

from .common import SAMPLES, make_tempdir


class PageTest(unittest.TestCase):
    def render(self, tmp):
        outcomes = checker.check_all(SAMPLES, Path(tmp) / "var")
        return page.render(SAMPLES, outcomes, Path(tmp) / "var"), outcomes

    def test_render_content(self):
        with make_tempdir() as tmp:
            html_text, outcomes = self.render(tmp)
            self.assertIn("负载 15 份", html_text)
            for outcome in outcomes:
                self.assertIn(outcome.name, html_text)
            self.assertIn("段布局", html_text)
            self.assertIn("指标走势", html_text)
            self.assertIn("reclaim_min", html_text)
            for svg in re.findall(r"<svg.*?</svg>", html_text, flags=re.S):
                ET.fromstring(svg)

    def test_self_contained(self):
        with make_tempdir() as tmp:
            html_text, _ = self.render(tmp)
            self.assertNotIn("http://", html_text)
            self.assertNotIn("https://", html_text)
            self.assertNotIn("<script", html_text)
            self.assertNotIn("<link", html_text)
            self.assertNotIn("<img", html_text)

    def test_deterministic(self):
        with make_tempdir() as tmp_a, make_tempdir() as tmp_b:
            html_a, _ = self.render(tmp_a)
            html_b, _ = self.render(tmp_b)
            self.assertEqual(html_a, html_b)


if __name__ == "__main__":
    unittest.main()
