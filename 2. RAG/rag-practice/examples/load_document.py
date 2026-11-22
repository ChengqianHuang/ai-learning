from pathlib import Path

# examples 的上一级是 rag-practice 项目目录
project_dir = Path(__file__).resolve().parents[1]

# 原始资料目录，与 rag-practice 位于同一级目录下
corpus_dir = project_dir.parent / "Java面经知识库" / "corpus"

# 找出 JavaGuide 中的 Markdown 文件，排序后选第一篇
files = sorted((corpus_dir / "JavaGuide").rglob("*.md"))

if not files:
    raise FileNotFoundError(f"没有找到 Markdown 文件：{corpus_dir}")

file_path = files[0]

# 按 UTF-8 编码读取，结果是一个字符串
text = file_path.read_text(encoding="utf-8-sig")

print(f"文件名：{file_path.name}")
print(f"字符数：{len(text)}")
print("\n正文前 500 个字符：\n")
print(text[:500])