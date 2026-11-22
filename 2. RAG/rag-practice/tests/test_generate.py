"""不访问网络：用真实 SDK 和模拟 HTTP 响应检查协议及失败分支。"""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import anthropic
import httpx2

from generate import load_generation_config, render_markdown, request_answer
from prepare_rag import prepare_request


class GenerationTest(unittest.TestCase):
    def setUp(self):
        self.settings = load_generation_config({})
        self.request = {
            "messages": [{"role": "system", "content": "只根据资料回答"},
                         {"role": "user", "content": "问题和资料"}],
            "citations": [{"citation": "[1]"}],
        }

    def call(self, text="开启访问顺序。[1]", stop="end_turn", status=200):
        def handler(request):
            self.assertEqual(str(request.url), "https://api.minimax.cn/anthropic/v1/messages")
            body = json.loads(request.content)
            self.assertEqual(body["output_config"], {"effort": "max"})
            self.assertEqual(body["system"], "只根据资料回答")
            self.assertEqual(body["messages"], [self.request["messages"][1]])
            self.assertEqual(body["model"], "MiniMax-M3.1-Flash")
            self.assertEqual(body["max_tokens"], 4096)
            if status != 200:
                return httpx2.Response(status, json={"type": "error", "error": {
                    "type": "authentication_error", "message": "SECRET-IN-ERROR"}})
            return httpx2.Response(200, json={
                "id": "msg_mock", "type": "message", "role": "assistant",
                "model": "MiniMax-M3.1-Flash", "stop_reason": stop, "stop_sequence": None,
                "content": [{"type": "thinking", "thinking": "not an answer", "signature": "test"},
                            {"type": "text", "text": text}],
                "usage": {"input_tokens": 120, "output_tokens": 40},
            })
        with anthropic.Anthropic(
            api_key="test-only", base_url=self.settings["base_url"], max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        ) as client:
            return request_answer(client, self.request, self.settings)

    def test_request_and_text_extraction(self):
        result = self.call()
        self.assertEqual(result["answer"], "开启访问顺序。[1]")
        self.assertEqual(result["used_citations"], ["[1]"])
        self.assertEqual(result["usage"]["input_tokens"], 120)

    def test_truncated_answer_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "max_tokens"):
            self.call(stop="max_tokens")

    def test_unknown_citation_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "不存在"):
            self.call(text="结论。[9]")

    def test_no_citation_warns(self):
        self.assertTrue(self.call(text="资料不足，无法确定。")["warnings"])

    def test_empty_answer_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "text"):
            self.call(text="")

    def test_api_error_does_not_echo_body(self):
        with self.assertRaises(RuntimeError) as caught:
            self.call(status=401)
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("SECRET-IN-ERROR", str(caught.exception))

    def test_payment_error_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError, "余额或可用额度不足"):
            self.call(status=402)

    def test_context_and_source_rendering(self):
        question = "LinkedHashMap 如何实现 LRU 缓存？"
        chunk = {
            "document_id": "demo", "chunk_id": "lru", "content": "开启访问顺序。",
            "heading_path": ["LRU 缓存"],
            "source": {"path": "linkedhashmap-source-code.md"},
            "references": [{"location": {"line_start": 633, "line_end": 633}}],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            index_dir = root / "data/indexes/demo"
            report_dir = root / "data/reports"
            index_dir.mkdir(parents=True)
            report_dir.mkdir(parents=True)
            body = (json.dumps(chunk, ensure_ascii=False) + "\n").encode("utf-8")
            (index_dir / "chunks.jsonl").write_bytes(body)
            (index_dir / "metadata.json").write_text(json.dumps({
                "chunks_sha256": hashlib.sha256(body).hexdigest(), "model_revision": "demo-revision",
            }), encoding="utf-8")
            (report_dir / "demo.search.json").write_text(json.dumps({
                "question": question, "index_model_revision": "demo-revision",
                "results": [{"score": 0.95, "chunk": chunk}],
            }, ensure_ascii=False), encoding="utf-8")
            with patch("prepare_rag.ROOT", root):
                request = prepare_request("demo", question)

        self.assertEqual([c["citation"] for c in request["citations"]], ["[1]"])
        self.assertIn(chunk["content"], request["messages"][1]["content"])
        rendered = render_markdown({**request, "answer": "示例答案。[1]", "warnings": []})
        self.assertIn("linkedhashmap-source-code.md", rendered)
        self.assertIn("633", rendered)


if __name__ == "__main__":
    unittest.main()
