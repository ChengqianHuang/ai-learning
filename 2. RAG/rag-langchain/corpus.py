"""按语料清单加载原文，切分为带行号或页码的 LangChain Document。"""

from bisect import bisect_left
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pypdfium2 as pdfium


KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "Java面经知识库"
CHUNK_TOKENS = 480


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    path: str
    url: str
    format: str
    sha256: str
    bytes: int


def load_manifest(root: Path) -> list[Source]:
    manifest = root / "metadata" / "manifest.jsonl"
    sources = []
    ids = set()
    with manifest.open(encoding="utf-8") as lines:
        for row in map(json.loads, filter(str.strip, lines)):
            path = Path(row["path"])
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "corpus":
                raise ValueError(f"语料路径不在 corpus/ 中：{path}")
            if row["format"] not in {"md", "adoc", "pdf"}:
                raise ValueError(f"不支持的格式：{path}")
            if row["id"] in ids:
                raise ValueError(f"清单包含重复文档 ID：{row['id']}")
            ids.add(row["id"])
            sources.append(Source(row["id"], row["title"], row["path"], row["source_url"],
                                  row["format"], row["sha256"], row["bytes"]))
    if not sources:
        raise ValueError("来源清单为空")
    return sorted(sources, key=lambda source: (source.bytes, source.id))


def read_sections(source: Source, root: Path) -> Iterator[tuple[int | None, str]]:
    data = (root / source.path).read_bytes()
    if hashlib.sha256(data).hexdigest() != source.sha256:
        raise ValueError("原文 SHA-256 与清单不符")
    if source.format != "pdf":
        yield None, data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        return

    with pdfium.PdfDocument(data) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            with closing(page), closing(page.get_textpage()) as text_page:
                text = text_page.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n")
            yield page_number, text


def make_splitter(count_passage_tokens: Callable[[str], int]) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_TOKENS, chunk_overlap=0, length_function=count_passage_tokens,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        add_start_index=True,
    )


def split_sections(
    source: Source,
    root: Path,
    splitter: RecursiveCharacterTextSplitter,
    count_passage_tokens: Callable[[str], int],
) -> tuple[list[Document], int, int]:
    documents = []
    empty_pages = 0
    includes = 0
    for page, original in read_sections(source, root):
        start_of_body = 0
        if source.format == "md":
            front_matter = re.match(r"\A---[ \t]*\n.*?^---[ \t]*\n", original, re.DOTALL | re.MULTILINE)
            if front_matter:
                start_of_body = front_matter.end()
        elif source.format == "adoc":
            includes += len(re.findall(r"^\s*include::", original, re.MULTILINE))

        body = original[start_of_body:]
        if not body.strip():
            empty_pages += int(page is not None)
            continue
        metadata = {"source": source.path, "source_url": source.url, "title": source.title,
                    "format": source.format}
        if page is not None:
            metadata["page"] = page
        newlines = [i for i, char in enumerate(original) if char == "\n"] if page is None else []
        for chunk in splitter.create_documents([body], metadatas=[metadata]):
            offset = chunk.metadata["start_index"]
            start = start_of_body + offset
            end = start + len(chunk.page_content)
            if offset < 0 or not original.startswith(chunk.page_content, start):
                raise ValueError("切分片段无法定位到原文")
            if count_passage_tokens(chunk.page_content) > CHUNK_TOKENS:
                raise ValueError("切分片段超出 Token 预算")
            chunk.id = f"{source.id}:{page or 0}:{start}"
            chunk.metadata["start_index"] = start
            if page is None:
                chunk.metadata["line_start"] = bisect_left(newlines, start) + 1
                chunk.metadata["line_end"] = bisect_left(newlines, end - 1) + 1
            documents.append(chunk)
    if not documents:
        raise ValueError("文档没有抽取出可索引的正文")
    return documents, empty_pages, includes
