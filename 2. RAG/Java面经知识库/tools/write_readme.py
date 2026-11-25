#!/usr/bin/env python3
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
s=json.loads((ROOT/'metadata/verification.json').read_text())
records=[json.loads(line) for line in (ROOT/'metadata/manifest.jsonl').read_text().splitlines()]
books=[r for r in records if r['format']=='pdf']
whole_books=sum(r['document_type']=='complete_book' for r in books)
monographs=sum(r['document_type']=='research_monograph' for r in books)
pdf_report={r['path']:r for r in json.loads((ROOT/'metadata/pdf_verification.json').read_text())}
booklines=['# 后端书籍目录','',f'共 {len(books)} 份完整 PDF：{whole_books} 本书籍、{monographs} 部研究专著。按整份 PDF 计数，保留原版字节。','',
           '中文名称为方便检索添加的译名，不代表文件是中文译本；语言以表格为准。','',
           '| 书籍 | 主题 | 语言 | 页数 | 原始来源 | 许可/使用条款 |','| --- | --- | --- | ---: | --- | --- |']
for r in sorted(books,key=lambda r:(r.get('subject','Java与数据结构'),r['title'])):
    page=r.get('pages',pdf_report.get(r['path'],{}).get('pages',''))
    booklines.append(f"| {r.get('title_zh',r['title'])} | {r.get('subject','Java与数据结构')} | {'中文' if r['language']=='zh' else '英文'} | {page} | [官方页面](<{r['source_url']}>) | {r['license']} |")
(ROOT/'书籍目录.md').write_text('\n'.join(booklines)+'\n')
source_rows='\n'.join(f'| {name} | {count} |' for name,count in s['by_source'].items())
topic_rows='\n'.join(f'| {name} | {count} |' for name,count in s['by_topic'].items())
text=f'''# Java 与后端知识库

本知识库用于学习 Java 面试与后端基础专题 RAG。收集日期：2026-11-13。

公开目录链接到上游文档和图书发布页。本地语料保存于 `corpus/`，文件路径、来源和校验值列在[来源清单](metadata/manifest.jsonl)中。下列统计来自完整的本地语料快照。

## 已交付内容

`corpus/` 内共 **{s['total_files']} 个实际正文文件**，包括 **{whole_books} 本完整书籍、{monographs} 部研究专著**（均为整份 PDF）和 **498 篇上游独立文章或参考文档**。
原有 500 份资料保留，本轮在其基础上新增 {sum(r['source']=='BackendBooks' for r in books)} 份书籍或专著 PDF。书籍区累计 {sum(r.get('pages',0) for r in books):,} 页，以英文原版为主，《Pro Git》为简体中文版。文章主要是 Java 面试题解、技术知识总结与 Spring 官方参考资料，另外有面试准备和实习经验内容。
书籍按整本、文章按原始文件计数；链接清单、元数据、许可证和脚本不算正文数量。

正文总大小：{s['total_bytes']:,} 字节（{s['total_bytes']/1024/1024:.2f} MiB）。

| 来源 | 文件数 |
| --- | ---: |
{source_rows}

## 怎么查看

- [可点击的完整目录](目录.md)：按来源列出全部正文文件。
- [书籍专用目录](书籍目录.md)：书名、主题、语言、页数、官方来源和许可信息。
- [CSV 文件清单](metadata/文件清单.csv)：文件名、主题、来源、语言、许可、路径、链接和校验值。
- [RAG 来源清单](metadata/manifest.jsonl)：一行对应一个正文文件，适合作为后续加载入口。
- [核验报告](metadata/verification.json)：实际数量、大小、格式、语言和去重检查。
- `licenses/` 保存上游许可证和书籍授权来源信息。上游 README、发布页快照和版权页摘录留在本地。

## 主题覆盖

主题由文件路径自动标注，属于初步分类；后续可按正文进一步细化。

| 主题 | 文件数 |
| --- | ---: |
{topic_rows}

## 来源与授权

- [JavaGuide](https://github.com/Snailclimb/JavaGuide)：Apache-2.0。
- [Advanced Java](https://github.com/doocs/advanced-java)：CC-BY-SA-4.0。
- [JavaCore](https://github.com/dunwu/javacore)：CC-BY-SA-4.0。
- [JVM](https://github.com/doocs/jvm)：CC-BY-SA-4.0。
- [Spring Framework](https://github.com/spring-projects/spring-framework)：Apache-2.0。
- [Think Java 2e](https://greenteapress.com/wp/think-java-2e/)，Allen B. Downey、Chris Mayfield：CC-BY-NC-SA-4.0。
- [Think Data Structures](https://greenteapress.com/wp/think-data-structures/)，Allen B. Downey：CC-BY-NC-SA-3.0，许可版本见书内版权页。

- 本轮新增书籍的作者、官方来源、权利声明见 [书籍目录](书籍目录.md) 和 `licenses/BooksExpansion/`。

各来源保留各自许可，不给整个混合语料重新授予统一许可。部分书籍有非商业、禁止改作等限制，少数是作者或出版社公开提供阅读的版权保留版本，不能视为通用开放授权。
GitHub 文档按固定 commit 获取；来源清单保留不可变版本链接。PDF 保留作者、项目、出版社或教育资源平台的原始文件与 SHA-256。
正文保持下载字节不变，来源和分类等信息单独存储。

## 已完成的核验

- 正文目录文件数与 manifest 一一对应，共 {s['total_files']} 个。
- 所有文件非空，逐个核对文件大小和 SHA-256。
- 498 份文章逐个与上游固定提交的 Git blob SHA-1 比对，通过后才交付。
- 文本文档可以按 UTF-8 解码，至少 1,800 字节且去空白后至少 500 字符。
- 字节级重复：0；去空白后的全文重复：0。没有把它当作语义去重结果，跨来源仍可能存在相近内容。
- 排除了 README、目录页和推荐书单；正文没有人工拆分。
- PDF 已做结构解析、文本提取和正文抽样渲染检查，逐本结果见 `metadata/pdf_verification.json`。

## 后续建立 RAG 时需要处理的事项

1. 用 `metadata/manifest.jsonl` 加载 `corpus/`，不要把许可证、清单和脚本也送进索引。
2. Markdown 按标题切分；AsciiDoc 需要支持 `.adoc` 的加载或先转为纯文本；PDF 需按页提取文字。
3. 本阶段保留原始文件，Markdown 中的外链图片未批量下载。{s['documents_with_external_images']} 份文档含图片语法，图示内容后续需单独处理。
4. {s['documents_with_unexpanded_asciidoc_includes']} 份 Spring 文档含 `include::` 外部代码引用，尚未展开。正文可读，引用的代码示例不保证完整；正式索引前应从固定 commit 补齐。
5. 旧技术与不同 Java/Spring 版本会共存。尤其 Spring 来源是固定提交的上游主分支快照，不能把所有结论都当作同一个稳定版本。
6. 切分后为每个 chunk 保留 `id`、`title`、`source_url`、`path`、`commit`、`license`；PDF 加上页码。
7. 后续再做语义去重、检索评估与嵌入；当前没有调用模型，也没有生成向量索引。
8. Java / Spring Notes for Professionals 是 2018 年的参考手册，部分 API 和做法已过时；入库时应添加版本标签。图形复杂的 PDF 可使用 PDFium 或 pdfplumber 作为备用文字提取器。

## 检查与扩充

在本目录中运行：

```bash
python3 tools/verify.py
python3 tools/write_readme.py
```

扩充书籍使用 `tools/add_books.py`，需要安装 pypdf 的 Python 环境。全文核验使用 `tools/check_books.py`，另需 pypdfium2 和 pdftoppm。`collect.py` 与 `curate.py` 为初始 500 份语料的采集脚本；扩充后采集器会阻止覆盖清单。
原始 500 份来源清单另存于 `metadata/manifest.initial-500.jsonl`。采集器默认复用已下载文件与固定版本树。
'''
(ROOT/'README.md').write_text(text)
print('README generated')
