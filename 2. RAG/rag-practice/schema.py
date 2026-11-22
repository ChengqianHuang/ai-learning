from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Block:
    document_id: str
    block_id: str
    heading_path: tuple[str, ...]
    kind: Literal["paragraph", "list", "code", "table"]
    text: str
    location: dict


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    heading_path: tuple[str, ...]
    content: str
    embedding_text: str
    length: int
    references: list[dict]