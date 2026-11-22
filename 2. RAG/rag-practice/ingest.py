import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from parsers.markdown import parse_markdown


PROJECT_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = PROJECT_DIR.parent / "Java面经知识库"
MANIFEST_PATH = KNOWLEDGE_DIR / "metadata" / "manifest.jsonl"
OUTPUT_DIR = PROJECT_DIR / "data" / "parsed"


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "--match",
        default="",
        help="按来源文件路径筛选",
    )
    argument_parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="处理文件数量，0 表示全部",
    )
    args = argument_parser.parse_args()

    if args.limit < 0:
        argument_parser.error("--limit 不能小于 0")

    records = [
        json.loads(line)
        for line in MANIFEST_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    selected = [
        record
        for record in records
        if record["format"] == "md"
        and args.match.casefold() in record["path"].casefold()
    ]

    if args.limit:
        selected = selected[:args.limit]

    if not selected:
        raise ValueError("没有匹配的 Markdown 文档")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = []

    for record in selected:
        try:
            file_path = KNOWLEDGE_DIR / record["path"]
            text = file_path.read_text(encoding="utf-8-sig")

            blocks = parse_markdown(text, record["id"])

            if not blocks:
                raise ValueError("文档没有解析出正文 Block")

            # 验证每个 Block 都能通过行号找回原文。
            lines = text.splitlines(keepends=True)

            for block in blocks:
                start = block.location["line_start"] - 1
                end = block.location["line_end"]
                original = "".join(lines[start:end]).strip("\r\n")

                if original != block.text:
                    raise ValueError(
                        f"来源行号校验失败：{block.block_id}"
                    )

            output_path = OUTPUT_DIR / (
                f"{record['id']}.blocks.jsonl"
            )

            output_path.write_text(
                "".join(
                    json.dumps(asdict(block), ensure_ascii=False)
                    + "\n"
                    for block in blocks
                ),
                encoding="utf-8",
            )

            # 文档级元数据独立保存，避免在每个 Block 中重复。
            source_path = OUTPUT_DIR / (
                f"{record['id']}.source.json"
            )
            source_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            counts = dict(Counter(block.kind for block in blocks))

            report.append(
                {
                    "document_id": record["id"],
                    "path": record["path"],
                    "status": "success",
                    "block_count": len(blocks),
                    "block_types": counts,
                }
            )

            print(f"\n文件：{record['path']}")
            print(f"Block 数量：{len(blocks)}")
            print(f"类型分布：{counts}")
            print(f"输出：{output_path}")

            for block in blocks[:3]:
                print(
                    f"  {block.kind} | "
                    f"{' > '.join(block.heading_path)} | "
                    f"行 {block.location['line_start']}"
                    f"—{block.location['line_end']}"
                )

        except Exception as error:
            report.append(
                {
                    "document_id": record["id"],
                    "path": record["path"],
                    "status": "failed",
                    "error": str(error),
                }
            )
            print(f"\n失败：{record['path']}：{error}")

    report_path = OUTPUT_DIR / "ingest_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    failures = sum(item["status"] == "failed" for item in report)
    print(f"\n处理 {len(report)} 份，失败 {failures} 份")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()