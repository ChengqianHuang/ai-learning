from hashlib import sha256
from typing import Callable

from schema import Block, Chunk

def make_chunks(
    blocks: list[Block],
    measure: Callable[[str], int],
    max_length: int,
) -> list[Chunk]:
    """
    measure: 长度计算函数，例如 tokenizer 的 token 计数。
    max_length: 包含标题前缀在内的长度上限。

    blocks 必须按照文档中的阅读顺序传入。
    """
    if max_length <= 0:
        raise ValueError("max_length 必须大于 0")

    results = []
    pending = []  # (Block, 文本片段, 在原 Block 中的起点, 终点)

    def render(parts):
        content = "\n\n".join(part[1] for part in parts)
        heading = " > ".join(parts[0][0].heading_path)
        embedding_text = f"{heading}\n\n{content}" if heading else content
        return content, embedding_text

    def fits(parts):
        return measure(render(parts)[1]) <= max_length

    def flush():
        if not pending:
            return

        first = pending[0][0]
        content, embedding_text = render(pending)

        references = [
            {
                "block_id": block.block_id,
                "location": block.location,
                "char_start": start,
                "char_end": end,  # 左闭右开，在原 Block.text 中的位置
            }
            for block, _, start, end in pending
        ]

        # 内容和出处共同决定 ID，重复运行可得到相同结果。
        identity = (
            first.document_id,
            first.heading_path,
            tuple(
                (block.block_id, start, end)
                for block, _, start, end in pending
            ),
            embedding_text,
        )
        chunk_id = sha256(repr(identity).encode("utf-8")).hexdigest()[:24]

        results.append(
            Chunk(
                chunk_id=chunk_id,
                document_id=first.document_id,
                heading_path=first.heading_path,
                content=content,
                embedding_text=embedding_text,
                length=measure(embedding_text),
                references=references,
            )
        )
        pending.clear()

    for block in blocks:
        if not block.text.strip():
            continue

        # 文档或标题发生变化，结束当前 Chunk。
        if pending:
            previous = pending[0][0]
            if (
                block.document_id != previous.document_id
                or block.heading_path != previous.heading_path
            ):
                flush()

        whole = (block, block.text, 0, len(block.text))

        # 当前 Chunk 还放得下，就直接追加。
        if fits(pending + [whole]):
            pending.append(whole)
            continue

        flush()

        # 整个 Block 单独放得下。
        if fits([whole]):
            pending.append(whole)
            continue

        # 代码和表格需要专门的拆分规则。
        if block.kind in {"code", "table"}:
            raise ValueError(
                f"超长 {block.kind}，需要专门处理："
                f"{block.document_id}/{block.block_id}"
            )

        # 超长文本：查找预算内的前缀，并优先在段落或句末结束。
        start = 0

        while start < len(block.text):
            remaining = block.text[start:]
            low, high = 1, len(remaining)
            best = 0

            while low <= high:
                middle = (low + high) // 2
                candidate = (
                    block,
                    remaining[:middle],
                    start,
                    start + middle,
                )

                if fits([candidate]):
                    best = middle
                    low = middle + 1
                else:
                    high = middle - 1

            if best == 0:
                raise ValueError(
                    f"标题加单个字符已超过预算：{block.block_id}"
                )

            # 避免在片段很靠前的位置切开；优先选后半段的自然边界。
            if best < len(remaining):
                prefix = remaining[:best]
                boundaries = [
                    i + 1
                    for i, char in enumerate(prefix)
                    if char in "\n。！？；"
                    or (
                        char in ".!?"
                        and i + 1 < len(remaining)
                        and remaining[i + 1].isspace()
                    )
                ]

                for end in reversed(boundaries):
                    candidate = (
                        block, remaining[:end], start, start + end
                    )
                    if end >= best // 2 and fits([candidate]):
                        best = end
                        break

            end = start + best
            pending.append((block, block.text[start:end], start, end))
            flush()
            start = end

    flush()
    return results