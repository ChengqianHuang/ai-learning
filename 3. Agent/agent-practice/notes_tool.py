"""供第三章实验复用的只读工具，返回仓库笔记里的原文和出处。"""

import re
from pathlib import Path


NOTES_DIR = Path(__file__).resolve().parents[1] / "笔记"
MAX_QUERY_LENGTH = 200
MAX_TOP_K = 5
TOOL = {
    "name": "search_notes",
    "description": "搜索本仓库第三章 Agent 笔记，返回相关段落、标题和文件名。可传中文关键词或问题。",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_LENGTH},
            "top_k": {"type": "integer", "minimum": 1, "maximum": MAX_TOP_K, "default": 3},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def query_terms(query: str) -> set[str]:
    query = re.sub(r"为什么|是什么|怎么样|如何|怎样|怎么|能否|是否|什么|请问", " ", query)
    terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
    for word in re.findall(r"[\u3400-\u9fff]+", query):
        terms.add(word)
        terms.update(word[i : i + 2] for i in range(len(word) - 1))
    return terms


def search_notes(query: str, top_k: int = 3) -> list[dict[str, str]]:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"query 需要 1 到 {MAX_QUERY_LENGTH} 个字符，并包含非空白内容")
    if type(top_k) is not int or not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k 需要 1 到 {MAX_TOP_K} 之间的整数")

    terms = query_terms(query)
    # 每节只保留最相关的段落，避免相邻几行占满返回结果。
    best: dict[tuple[str, str], tuple[int, str]] = {}
    for path in sorted(NOTES_DIR.glob("*.md")):
        heading = path.stem
        in_code = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not line.strip():
                continue
            if line.startswith("#"):
                heading = line.lstrip("# ").strip()
                continue
            paragraph = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line).replace("**", "").strip()
            body = paragraph.casefold()
            matches = [term for term in terms if term in body]
            if not matches:
                continue
            score = 3 * len(matches) + sum(term in heading.casefold() for term in matches)
            key = (path.name, heading)
            if key not in best or score > best[key][0]:
                best[key] = (score, paragraph)

    ranked = sorted(best, key=lambda key: -best[key][0])
    return [
        {"source": source, "heading": heading, "text": best[source, heading][1]}
        for source, heading in ranked[:top_k]
    ]
