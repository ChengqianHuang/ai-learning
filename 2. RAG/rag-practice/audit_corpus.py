"""全量 Markdown 预检：解析、来源回溯及完整 Block 的 Token 预算。"""
import argparse
from collections import Counter
import json

from transformers import AutoTokenizer

from ingest import KNOWLEDGE_DIR, MANIFEST_PATH, PROJECT_DIR
from parsers.markdown import parse_markdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-tokens", type=int, default=480)
    args = parser.parse_args()
    if not 1 <= args.max_tokens <= 512:
        parser.error("max-tokens 必须在 1—512 之间")
    tokenizer = AutoTokenizer.from_pretrained(
        "intfloat/multilingual-e5-small", local_files_only=True,
    )
    records = [json.loads(line) for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    documents = []
    unsupported = []
    for source in records:
        if source["format"] != "md":
            unsupported.append({"document_id": source["id"], "path": source["path"],
                                "format": source["format"]})
            continue
        result = {"document_id": source["id"], "path": source["path"]}
        try:
            text = (KNOWLEDGE_DIR / source["path"]).read_text(encoding="utf-8-sig")
            blocks = parse_markdown(text, source["id"])
            if not blocks:
                raise ValueError("正文 Block 为空")
            lines = text.splitlines(keepends=True)
            oversized = []
            for block in blocks:
                location = block.location
                original = "".join(lines[location["line_start"] - 1:location["line_end"]]).strip("\r\n")
                if original != block.text:
                    raise ValueError(f"来源回溯校验失败：{block.block_id}")
                heading = " > ".join(block.heading_path)
                full_text = f"{heading}\n\n{block.text}" if heading else block.text
                length = len(tokenizer.encode("passage: " + full_text, add_special_tokens=True,
                                              truncation=False, verbose=False))
                if length > args.max_tokens:
                    oversized.append({"block_id": block.block_id, "kind": block.kind,
                                      "tokens_with_heading": length,
                                      "heading_path": list(block.heading_path),
                                      "location": location})
            result.update(status="success", block_count=len(blocks),
                          block_types=dict(Counter(b.kind for b in blocks)), oversized=oversized)
        except Exception as error:
            result.update(status="failed", error=str(error))
        documents.append(result)
        if len(documents) % 25 == 0:
            print(f"已预检 {len(documents)} 份 Markdown", flush=True)

    parsed = [doc for doc in documents if doc["status"] == "success"]
    oversized = [block for doc in parsed for block in doc["oversized"]]
    blockers = [block for block in oversized if block["kind"] in {"code", "table"}]
    summary = {
        "corpus_documents": len(records), "markdown_documents": len(documents),
        "parsed_success": len(parsed), "parsed_failed": len(documents) - len(parsed),
        "total_blocks": sum(doc["block_count"] for doc in parsed),
        "oversized_block_types": dict(Counter(block["kind"] for block in oversized)),
        "code_table_blockers": len(blockers),
        "documents_with_code_table_blockers": sum(
            any(b["kind"] in {"code", "table"} for b in doc["oversized"]) for doc in parsed),
        "unsupported_formats": dict(Counter(doc["format"] for doc in unsupported)),
    }
    output = PROJECT_DIR / "data/reports/corpus_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "summary": summary,
        "settings": {"max_tokens": args.max_tokens, "model": "intfloat/multilingual-e5-small",
                     "passage_prefix": "passage: ", "add_special_tokens": True},
        "documents": documents, "unsupported_documents": unsupported,
        "scope": "解析及单 Block 长度预检；未执行 Chunk 打包、向量化或生成 API。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告：{output}")
    if summary["parsed_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
