"""读取保存的向量，以精确余弦相似度进行 Top-K 检索。"""
import argparse
import io
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from build_vectors import digest

ROOT = Path(__file__).resolve().parent


def load_index(index_dir: Path):
    meta = json.loads((index_dir / "metadata.json").read_text(encoding="utf-8"))
    chunk_bytes = (index_dir / "chunks.jsonl").read_bytes()
    vector_bytes = (index_dir / "vectors.npy").read_bytes()
    if digest(chunk_bytes) != meta["chunks_sha256"] or digest(vector_bytes) != meta["vectors_sha256"]:
        raise ValueError("索引文件校验失败，可能未写入完成或被修改，请重新建库")
    records = [json.loads(line) for line in chunk_bytes.decode("utf-8").splitlines() if line.strip()]
    vectors = np.load(io.BytesIO(vector_bytes), allow_pickle=False)
    if len(records) != meta["count"] or vectors.shape != (len(records), meta["dimension"]):
        raise ValueError("向量与 Chunk 数量/维度不一致")
    if not meta["normalized"] or not np.isfinite(vectors).all():
        raise ValueError("向量配置或数值无效")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5):
        raise ValueError("向量未归一化，不能直接使用点积作为余弦相似度")
    return meta, records, vectors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.top_k < 1 or not args.question.strip():
        parser.error("top-k 必须大于 0，问题不能为空")

    meta, records, vectors = load_index(ROOT / "data/indexes" / args.document_id)
    # 查询时使用建库时记录的同一模型提交版本及前缀。
    model = SentenceTransformer(meta["model"], revision=meta["model_revision"], device="cpu")
    if model.get_embedding_dimension() != meta["dimension"]:
        raise ValueError("查询模型维度与索引不一致")
    model.max_seq_length = meta["max_seq_length"]
    query = meta["query_prefix"] + args.question
    token_count = len(model.tokenizer.encode(query, add_special_tokens=True, truncation=False, verbose=False))
    if token_count > meta["max_seq_length"]:
        raise ValueError("问题超出模型 Token 上限")
    query_vector = model.encode([query], prompt="", normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)[0]
    scores = vectors @ query_vector
    indices = np.argsort(-scores, kind="stable")[:min(args.top_k, len(records))]

    results = []
    print(f"\n问题：{args.question}\n候选：{len(records)} 个 Chunk，返回 {len(indices)} 个")
    for rank, index in enumerate(indices, 1):
        record = records[int(index)]
        result = {"rank": rank, "score": float(scores[index]), "chunk": record}
        results.append(result)
        locations = [r["location"] for r in record["references"]]
        print(f"\n#{rank} 余弦相似度：{result['score']:.6f}")
        print(f"标题：{' > '.join(record['heading_path'])}")
        print(f"来源：{record['source']['path']}")
        print(f"原文位置：{json.dumps(locations, ensure_ascii=False)}")
        print(record["content"][:500])

    report_dir = ROOT / "data/reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{args.document_id}.search.json"
    path.write_text(json.dumps({"question": args.question, "index_model_revision": meta["model_revision"],
                               "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果：{path}")
    print("分数用于相关性排序，不代表答案正确率；本步骤仅检索，答案由后续生成步骤完成。")


if __name__ == "__main__":
    main()
