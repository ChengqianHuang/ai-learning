from hashlib import sha256

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

from schema import Block


parser = (
    MarkdownIt("commonmark")
    .enable("table")
    .use(front_matter_plugin)
)


def parse_markdown(text: str, document_id: str) -> list[Block]:
    tokens = parser.parse(text)
    lines = text.splitlines(keepends=True)

    blocks = []
    headings = []  # [(标题级别, 标题文本)]

    def emit(token, kind):
        if token.map is None:
            raise ValueError(f"缺少来源行号：{token.type}")

        start, end = token.map

        # 根据行号提取原文，保留代码围栏、列表和表格格式。
        content = "".join(lines[start:end]).strip("\r\n")

        if not content.strip():
            return

        identity = (
            f"{document_id}\0{kind}\0{start}\0{end}\0{content}"
        )
        block_id = sha256(identity.encode("utf-8")).hexdigest()[:24]

        blocks.append(
            Block(
                document_id=document_id,
                block_id=block_id,
                heading_path=tuple(title for _, title in headings),
                kind=kind,
                text=content,
                location={
                    "line_start": start + 1,
                    "line_end": end,
                },
            )
        )

    def skip_container(index):
        """跳过当前容器及其全部子 Token，防止正文重复输出。"""
        depth = 1
        cursor = index + 1

        while cursor < len(tokens):
            depth += tokens[cursor].nesting

            if depth == 0:
                return cursor + 1

            cursor += 1

        raise ValueError(f"容器未闭合：{tokens[index].type}")

    index = 0

    while index < len(tokens):
        token = tokens[index]

        # YAML 元数据不进入正文。
        # 文档标题、来源等信息仍由 manifest 提供。
        if token.type == "front_matter":
            index += 1
            continue

        if token.type == "heading_open":
            level = int(token.tag[1:])
            title = tokens[index + 1].content.strip()

            # 新标题替换同级标题，并清除旧的下级标题。
            while headings and headings[-1][0] >= level:
                headings.pop()

            if title:
                headings.append((level, title))

            # heading_open、inline、heading_close
            index += 3
            continue

        if token.type in {"bullet_list_open", "ordered_list_open"}:
            emit(token, "list")
            index = skip_container(index)
            continue

        if token.type == "table_open":
            emit(token, "table")
            index = skip_container(index)
            continue

        if token.type == "paragraph_open":
            emit(token, "paragraph")
            index = skip_container(index)
            continue

        if token.type in {"fence", "code_block"}:
            emit(token, "code")
            index += 1
            continue

        # 原始 HTML 暂时保留，后续清洗阶段再处理。
        if token.type == "html_block":
            emit(token, "paragraph")
            index += 1
            continue

        index += 1

    return blocks