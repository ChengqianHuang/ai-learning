"""为选中文档的全部 Chunk 生成并保存向量。"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import re
import tempfile

from huggingface_hub import hf_hub_download
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent
MODEL_NAME = "intfloat/multilingual-e5-small"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes):
    """单文件原子替换；索引元数据最后写入，查询时核对哈希。"""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size 必须大于 0")

    path = ROOT / "data/chunks" / f"{args.document_id}.chunks.jsonl"
    chunk_bytes = path.read_bytes()
    records = [json.loads(line) for line in chunk_bytes.decode("utf-8").splitlines() if line.strip()]
    if not records:
        raise ValueError("Chunk 文件为空")
    if any(r["document_id"] != args.document_id for r in records):
        raise ValueError("文档 ID 不一致")
    ids = [r["chunk_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Chunk ID 重复")

    # 从 Hub 缓存的 snapshots/<commit>/config.json 获取明确版本，
    # 不依赖 Transformers 配置对象的私有字段。
    config_path = Path(hf_hub_download(repo_id=MODEL_NAME, filename="config.json"))
    revision = config_path.parent.name
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"无法从配置缓存路径确认模型提交版本：{config_path}")
    model = SentenceTransformer(MODEL_NAME, revision=revision, device="cpu")
    limit = model.max_seq_length
    if limit is None or limit <= 0:
        raise ValueError("模型未提供有效输入上限")

    texts = ["passage: " + r["embedding_text"] for r in records]
    lengths = [len(model.tokenizer.encode(t, add_special_tokens=True, truncation=False, verbose=False))
               for t in texts]
    oversized = [(r["chunk_id"], n) for r, n in zip(records, lengths) if n > limit]
    if oversized:
        raise ValueError(f"存在超长 Chunk，禁止截断入库：{oversized}")

    # 第 i 行向量始终对应 records[i]，保持同样的顺序保存。
    vectors = model.encode(
        texts, batch_size=args.batch_size, prompt="",
        normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=True,
    ).astype(np.float32)
    dimension = model.get_embedding_dimension()
    if vectors.shape != (len(records), dimension):
        raise ValueError(f"向量形状异常：{vectors.shape}")
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5):
        raise ValueError("向量包含非有限值或未正确归一化")

    buffer = io.BytesIO()
    np.save(buffer, vectors, allow_pickle=False)
    vector_bytes = buffer.getvalue()
    index_dir = ROOT / "data/indexes" / args.document_id
    index_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 1,
        "document_id": args.document_id,
        "model": MODEL_NAME,
        "model_revision": revision,
        "dimension": int(vectors.shape[1]),
        "count": len(records),
        "dtype": str(vectors.dtype),
        "normalized": True,
        "passage_prefix": "passage: ",
        "query_prefix": "query: ",
        "max_seq_length": limit,
        "max_input_tokens": max(lengths),
        "chunks_sha256": digest(chunk_bytes),
        "vectors_sha256": digest(vector_bytes),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "libraries": {name: version(name) for name in ("sentence-transformers", "transformers", "torch", "numpy")},
    }
    atomic_write(index_dir / "vectors.npy", vector_bytes)
    atomic_write(index_dir / "chunks.jsonl", chunk_bytes)
    atomic_write(index_dir / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"\n批量向量化完成：{vectors.shape}，dtype={vectors.dtype}")
    print(f"模型版本：{revision}")
    print(f"保存目录：{index_dir}")


if __name__ == "__main__":
    main()
