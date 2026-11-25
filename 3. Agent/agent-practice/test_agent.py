"""覆盖模型返回边界，包括无法归到本次检索证据的引用。"""

import unittest

from agent import format_answer


class AnswerTests(unittest.TestCase):
    evidence = {"S1": {"source": "笔记.md", "heading": "重试"}}

    def test_malformed_text_blocks(self):
        for block in ({"type": "text"}, {"type": "text", "text": None}):
            with self.subTest(block=block), self.assertRaisesRegex(ValueError, "字符串格式"):
                format_answer([block], self.evidence)

    def test_unknown_or_missing_citation(self):
        for text in ("结论", "结论 [S1] [S2]"):
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, "引用"):
                format_answer([{"type": "text", "text": text}], self.evidence)

    def test_citations_across_blocks_share_one_source_entry(self):
        blocks = [{"type": "text", "text": "第一段 [S1]"}, {"type": "text", "text": "第二段 [S1]"}]
        self.assertEqual(
            format_answer(blocks, self.evidence),
            "第一段 [S1]\n第二段 [S1]\n\n来源\n[S1] 笔记.md · 重试",
        )
