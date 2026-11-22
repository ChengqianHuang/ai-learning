import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from schema import Block
from chunking.chunking import make_chunks

from transformers import AutoTokenizer

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_MAX_TOKENS = 512

PROJECT_DIR = Path(__file__).resolve().parent
PARSED_DIR = PROJECT_DIR / "data" / "parsed"
OUTPUT_DIR = PROJECT_DIR / "data" / "chunks"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--max-tokens", type=int, default=480)
    args = parser.parse_args()

    if not 0 < args.max_tokens <= MODEL_MAX_TOKENS:
        parser.error(f"--max-tokens 必须在 1—{MODEL_MAX_TOKENS} 之间")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(
            "passage: " + text,
            add_special_tokens=True,
            truncation=False,
            verbose=False,
        ))

    blocks_path = PARSED_DIR / f"{args.document_id}.blocks.jsonl"
    source_path = PARSED_DIR / f"{args.document_id}.source.json"

    source = json.loads(source_path.read_text(encoding="utf-8"))

    blocks = []
    for line in blocks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        record = json.loads(line)

        # JSON 数组恢复为 schema 中约定的 tuple。
        record["heading_path"] = tuple(record["heading_path"])
        blocks.append(Block(**record))

    if not blocks:
        raise ValueError("没有可切分的 Block")

    if any(block.document_id != args.document_id for block in blocks):
        raise ValueError("Block 的 document_id 与指定文档不一致")

    print(f"文档：{source['title']}")
    print(f"Block 数量：{len(blocks)}")
    print(f"类型分布：{dict(Counter(b.kind for b in blocks))}")

    # 预检查完整代码块和表格是否超出预算。
    # 标题也占用 embedding_text 的长度。
    oversized = []

    for block in blocks:
        heading = " > ".join(block.heading_path)
        embedding_text = (
            f"{heading}\n\n{block.text}" if heading else block.text
        )

        if (
            block.kind in {"code", "table"}
            and count_tokens(embedding_text) > args.max_tokens
        ):
            oversized.append(
                {
                    "block_id": block.block_id,
                    "kind": block.kind,
                    "tokens_with_heading": count_tokens(embedding_text),
                    "location": block.location,
                }
            )

    if oversized:
        print("\n发现超长代码块或表格：")
        print(json.dumps(oversized, ensure_ascii=False, indent=2))
        raise SystemExit(
            "本次未生成 Chunk。请先记录这些块，接下来为它们增加拆分策略。"
        )

    chunks = make_chunks(
        blocks=blocks,
        measure=count_tokens,
        max_length=args.max_tokens,
    )

    # 检查每个有效 Block 都被完整覆盖，且没有重复或缺口。
    for block in blocks:
        if not block.text.strip():
            continue

        references = [
            reference
            for chunk in chunks
            for reference in chunk.references
            if reference["block_id"] == block.block_id
        ]

        cursor = 0
        for reference in references:
            start = reference["char_start"]
            end = reference["char_end"]

            if start != cursor or not start < end <= len(block.text):
                raise ValueError(f"Block 覆盖异常：{block.block_id}")

            cursor = end

        if cursor != len(block.text):
            raise ValueError(f"Block 未完整覆盖：{block.block_id}")

    if any(chunk.length > args.max_tokens for chunk in chunks):
        raise ValueError("存在超出长度预算的 Chunk")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{args.document_id}.chunks.jsonl"

    records = []
    for chunk in chunks:
        record = asdict(chunk)
        record["source"] = source
        record["chunking_config"] = {
            "strategy": "heading_block_packing",
            "length_unit": "token",
            "tokenizer_model": MODEL_NAME,
            "passage_prefix": "passage: ",
            "add_special_tokens": True,
            "max_length": args.max_tokens,
            "overlap": 0,
        }
        records.append(record)

    output_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )

    lengths = sorted(chunk.length for chunk in chunks)

    print(f"\nChunk 数量：{len(chunks)}")
    print(
        f"长度：最小 {lengths[0]}，"
        f"平均 {sum(lengths) / len(lengths):.0f}，"
        f"最大 {lengths[-1]}"
    )
    print(f"输出：{output_path}")

    for chunk in chunks[:3]:
        print(f"\n--- {chunk.chunk_id} ---")
        print(f"标题：{' > '.join(chunk.heading_path)}")
        print(f"Token 数：{chunk.length}")
        print(chunk.content[:300])


if __name__ == "__main__":
    main()
