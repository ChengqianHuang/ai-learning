"""保存可续跑的全库索引，通过 LangChain Retriever 检索。"""

from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
import numpy as np
from pypdfium2 import PdfiumError

from corpus import Source, make_splitter, split_sections


DIMENSION = 384


def fingerprints(sources: list[Source]) -> dict[str, str]:
    return {
        source.id: hashlib.sha256(json.dumps(asdict(source), sort_keys=True).encode()).hexdigest()
        for source in sources
    }


def corpus_version(expected: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


def is_complete(path: Path, expected: dict[str, str]) -> bool:
    if not path.is_file():
        return False
    with closing(connect_readonly(path)) as db:
        row = db.execute("SELECT value FROM metadata WHERE key = 'corpus_version'").fetchone()
        return row == (corpus_version(expected),)


def print_status(path: Path, sources: list[Source], expected: dict[str, str]) -> None:
    print(f"语料清单：{len(sources)} 份")
    if not path.is_file():
        print("已入库：0 份")
        return
    with closing(connect_readonly(path)) as db:
        for fmt, files, chunks, empty, includes in db.execute("""
            SELECT format, COUNT(*), SUM(chunk_count), SUM(empty_pages), SUM(unexpanded_includes)
            FROM sources GROUP BY format ORDER BY format
        """):
            print(f"{fmt:4}  {files:3} 份，{chunks:6} 个片段，空页 {empty}，未展开 include {includes}")
        ready = db.execute("SELECT value FROM metadata WHERE key = 'corpus_version'").fetchone()
        print("索引完整" if ready == (corpus_version(expected),) else "索引尚未完成或语料清单已更新")


def build_index(
    path: Path,
    root: Path,
    sources: list[Source],
    expected: dict[str, str],
    count_passage_tokens: Callable[[str], int],
    embed_passages: Callable[[list[str]], np.ndarray],
    *,
    rebuild: bool,
) -> None:
    missing = [source.path for source in sources if not (root / source.path).is_file()]
    if missing:
        raise ValueError(f"缺少 {len(missing)} 份语料，例如 {missing[0]}。恢复步骤见 README.md。")
    path.parent.mkdir(parents=True, exist_ok=True)
    splitter = make_splitter(count_passage_tokens)
    failures = []
    with closing(sqlite3.connect(path, timeout=30)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, format TEXT NOT NULL,
                chunk_count INTEGER NOT NULL, empty_pages INTEGER NOT NULL, unexpanded_includes INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                text TEXT NOT NULL, metadata TEXT NOT NULL, vector BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chunks_source_id ON chunks(source_id);
        """)
        with db:
            db.execute("DELETE FROM metadata WHERE key = 'corpus_version'")
            if rebuild:
                db.execute("DELETE FROM sources")
        saved = dict(db.execute("SELECT id, fingerprint FROM sources"))
        reused = 0
        for count, source in enumerate(sources, start=1):
            fingerprint = expected[source.id]
            if saved.get(source.id) == fingerprint:
                reused += 1
                continue
            try:
                chunks, empty, includes = split_sections(source, root, splitter, count_passage_tokens)
                vectors = embed_passages([chunk.page_content for chunk in chunks])
                with db:
                    db.execute("DELETE FROM sources WHERE id = ?", (source.id,))
                    db.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
                               (source.id, fingerprint, source.format, len(chunks), empty, includes))
                    db.executemany(
                        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?)",
                        ((chunk.id, source.id, chunk.page_content, json.dumps(chunk.metadata, ensure_ascii=False),
                          vector.astype("<f4", copy=False).tobytes())
                         for chunk, vector in zip(chunks, vectors, strict=True)),
                    )
            except (OSError, ValueError, PdfiumError) as exc:
                failures.append(source.path)
                print(f"[{count}/{len(sources)}] 失败 {source.path}：{exc}", flush=True)
                continue
            print(f"[{count}/{len(sources)}] {source.format} {source.title} · {len(chunks)} 个片段", flush=True)
        print(f"复用上次已提交的文档：{reused} 份")
        if failures:
            raise ValueError(f"有 {len(failures)} 份文档未入库。修复上方错误后用 --build-only 续跑。")
        with db:
            db.executemany("DELETE FROM sources WHERE id = ?", ((i,) for i in saved.keys() - expected.keys()))
            if dict(db.execute("SELECT id, fingerprint FROM sources")) != expected:
                raise ValueError("索引来源与当前清单不一致")
            db.execute("INSERT INTO metadata VALUES ('corpus_version', ?)", (corpus_version(expected),))


class CorpusRetriever(BaseRetriever):
    """从持久化向量中精确计算 Top-K，只载入命中的片段正文。"""

    index_path: Path
    embeddings: Embeddings
    version: str
    k: int = 5

    def _get_relevant_documents(self, query: str) -> list[Document]:
        query_vector = np.asarray(self.embeddings.embed_query(query), dtype=np.float32)
        with closing(connect_readonly(self.index_path)) as db:
            db.execute("BEGIN")
            if db.execute("SELECT value FROM metadata WHERE key = 'corpus_version'").fetchone() != (self.version,):
                raise ValueError("全库索引未完成，请用 --build-only 续跑")
            rows = db.execute("SELECT rowid, vector FROM chunks ORDER BY rowid").fetchall()
            vectors = np.frombuffer(b"".join(vector for _, vector in rows), dtype="<f4").reshape(-1, DIMENSION)
            scores = vectors @ query_vector
            ranks = np.argsort(-scores, kind="stable")[:self.k]
            hits = []
            for rank in ranks:
                text, metadata, chunk_id = db.execute(
                    "SELECT text, metadata, id FROM chunks WHERE rowid = ?", (rows[rank][0],),
                ).fetchone()
                info = json.loads(metadata)
                info["score"] = float(scores[rank])
                hits.append(Document(page_content=text, metadata=info, id=chunk_id))
        return hits
