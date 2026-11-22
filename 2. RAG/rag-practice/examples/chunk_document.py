from pathlib import Path

def split_text(text, chunk_size=800, overlap=100):
    """按字符切分文本，相邻片段保留部分重叠。"""
    if not 0 <= overlap < chunk_size:
        raise ValueError("必须满足：0 <= overlap < chunk_size")

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])

        # 已经读到结尾，就结束切分
        if end == len(text):
            break

        # 下一段从上一段结束前的 overlap 个字符处开始
        start = end - overlap

    return chunks


project_dir = Path(__file__).resolve().parents[1]
corpus_dir = project_dir.parent / "Java面经知识库" / "corpus"

files = sorted((corpus_dir / "JavaGuide").rglob("*.md"))
if not files:
    raise FileNotFoundError("没有找到 Markdown 文件")

file_path = files[0]
text = file_path.read_text(encoding="utf-8-sig")

# 把文本片段与来源信息放在一起
chunks = [
    {
        "chunk_index": index,
        "source": file_path.relative_to(corpus_dir).as_posix(),
        "text": piece,
    }
    for index, piece in enumerate(split_text(text))
]

print(f"文件名：{file_path.name}")
print(f"原文字符数：{len(text)}")
print(f"片段数量：{len(chunks)}")

for chunk in chunks[:2]:
    print(f"\n--- 片段 {chunk['chunk_index']} ---")
    print(f"来源：{chunk['source']}")
    print(f"字符数：{len(chunk['text'])}")
    print(chunk["text"])

# 检查前两个片段的重叠部分
if len(chunks) >= 2:
    same = chunks[0]["text"][-100:] == chunks[1]["text"][:100]
    print(f"\n相邻片段重叠是否正确：{same}")