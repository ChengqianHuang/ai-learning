import argparse
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_NAME = "intfloat/multilingual-e5-small"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", default="40e64a56b24583cd")
    parser.add_argument("--question", default="LinkedHashMap 如何保持元素的遍历顺序？")
    args = parser.parse_args()
    chunks_path = PROJECT_DIR / "data" / "chunks" / f"{args.document_id}.chunks.jsonl"
    records = [
        json.loads(line)
        for line in chunks_path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    if not records:
        raise ValueError("Chunk 文件为空")

    print("加载 Embedding 模型……")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    tokenizer = model.tokenizer
    limit = model.max_seq_length

    if limit is None:
        raise ValueError("模型未声明输入长度上限，需要确认模型配置")

    if limit <= 0:
        raise ValueError(f"模型输入长度上限无效：{limit}")

    print(f"模型：{MODEL_NAME}")
    print(f"向量维度：{model.get_embedding_dimension()}")
    print(f"输入 Token 上限：{limit}")

    # 先检查全部 Chunk，包含 passage 前缀和特殊 Token。
    lengths = []

    for record in records:
        passage = "passage: " + record["embedding_text"]

        token_ids = tokenizer.encode(
            passage,
            add_special_tokens=True,
            truncation=False,
            verbose=False,
        )

        lengths.append(len(token_ids))

    oversized = [
        {
            "chunk_id": record["chunk_id"],
            "tokens": length,
            "heading_path": record["heading_path"],
        }
        for record, length in zip(records, lengths)
        if length > limit
    ]

    print(f"\n总 Chunk 数：{len(records)}")
    print(f"Token 数范围：{min(lengths)}—{max(lengths)}")
    print(f"超长 Chunk 数：{len(oversized)}")

    for item in oversized:
        print(
            f"  {item['chunk_id']} | "
            f"{item['tokens']} tokens | "
            f"{' > '.join(item['heading_path'])}"
        )

    if oversized:
        raise ValueError("存在超长 Chunk，请先修正切分；本次 Embedding 检查未通过")

    # 本次选择一条能够完整输入模型的真实 Chunk。
    selected = next(
        (
            record
            for record, length in zip(records, lengths)
            if length <= limit
        ),
        None,
    )

    if selected is None:
        raise ValueError("所有 Chunk 都超长，需要先重新切分")

    passage = "passage: " + selected["embedding_text"]
    question = args.question
    query = "query: " + question

    query_length = len(
        tokenizer.encode(
            query,
            add_special_tokens=True,
            truncation=False,
        )
    )
    if query_length > limit:
        raise ValueError("问题超过模型输入上限")

    # prompt=""：前缀已手动添加，不再额外添加提示前缀。
    vectors = model.encode(
        [passage, query],
        prompt="",
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    passage_vector = vectors[0]
    query_vector = vectors[1]

    # 已归一化的向量，其点积等于余弦相似度。
    similarity = float(passage_vector @ query_vector)

    print(f"\n选中的 Chunk：{selected['chunk_id']}")
    print(f"标题：{' > '.join(selected['heading_path'])}")
    print(f"正文预览：\n{selected['content'][:300]}")

    print(f"\n向量矩阵形状：{vectors.shape}")
    print(f"文档向量前 8 维：{passage_vector[:8]}")
    print(f"问题向量前 8 维：{query_vector[:8]}")
    print(f"文档向量的长度：{np.linalg.norm(passage_vector):.6f}")
    print(f"余弦相似度：{similarity:.6f}")

    report_dir = PROJECT_DIR / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "document_id": args.document_id,
        "model": MODEL_NAME,
        "chunk_count": len(records),
        "min_tokens": min(lengths),
        "max_tokens": max(lengths),
        "oversized_count": len(oversized),
        "probe_chunk_id": selected["chunk_id"],
        "question": question,
        "vector_shape": list(vectors.shape),
        "similarity": similarity,
        "scope": "All chunks length-checked; one passage and one question embedded. No vector index built.",
    }
    (report_dir / f"{args.document_id}.embedding_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
