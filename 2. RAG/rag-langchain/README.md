# LangChain 全库 RAG

按 Java 与后端语料的来源清单构建一个索引，以同一个问题跨文件检索。当前清单包含 **521 份资料**，包括 404 份 Markdown、94 份 AsciiDoc 和 23 份 PDF。此实现和手写单文档实验并列。 [手写实验](../rag-practice/README.md) · [语料来源](../Java面经知识库/README.md)

## 本地建库和查询

从仓库根目录进入本实验目录。依赖在 Python 3.14 上验证。

```bash
cd "2. RAG/rag-langchain"
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

已有本地语料时直接建库。公开检出包含来源清单，可以用以下命令补齐原文。下载器复用现有文件，逐份核对 SHA-256，并列出内容变化或无法下载的上游文件。

```bash
python3.14 "../Java面经知识库/tools/restore_manifest.py"
```

```bash
./run.command --build-only
./run.command --status
./run.command "LinkedHashMap 怎样实现 LRU 缓存？" --top-k 5
./run.command "数据库索引怎样影响查询和写入？"
```

首次缺少 E5 模型缓存时使用 `./run.command --build-only --download-model`。编码默认在可用时选择 Apple MPS，也可以通过 `--device cpu` 明确指定 CPU。

构建时每完成一份文档就提交正文、向量和进度。中断后再次执行 `--build-only` 会复用已提交的文档。索引在 `data/corpus.e5-614241f6.v1.sqlite3`，`--status` 可查看入库数、片段数和源材料的空页。查询发现索引缺失或落后于清单时会先补建。需要明确重建全部文档时使用 `--build-only --rebuild`。

## 生成带来源的答案

在终端配置 `MINIMAX_API_KEY`，或将本目录的 `.env.example` 复制为 `.env` 后填写。默认模型为 `MiniMax-M3.1-Flash`，可用 `MINIMAX_MODEL` 指定。加 `--answer` 时，程序将问题和用于作答的原文片段发送给 MiniMax。 [MiniMax 接口文档](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)

```bash
./run.command "如何同时使用 Redis 和数据库保持数据一致？" --top-k 8 --answer
```

答案后会列出使用的证据编号及出处。Markdown 和 AsciiDoc 链接指向固定版本的原文行号，PDF 带来源链接和从 1 开始的 PDF 文件页码。

## 代码路径

| 环节 | 实现 |
|---|---|
| 原文读取 | 按清单校验文件。Markdown 略过 YAML 头部，AsciiDoc 按源文本读取，PDF 用 PDFium 分页抽取文字 |
| 切分 | `RecursiveCharacterTextSplitter` 按段落、换行和标点递归切分，按完整 E5 输入校验 480 Token 上限 |
| 向量构建 | 实现 LangChain 的 `Embeddings` 接口，使用固定提交的 multilingual-e5-small，分别给文档和查询加 E5 前缀 |
| 断点和存储 | SQLite 逐文档提交片段、归一化的 384 维向量和来源元数据 |
| 查询 | `CorpusRetriever` 实现 LangChain 的 `BaseRetriever`，扫描完整索引向量并按余弦相似度取 Top-K |
| 生成 | `ChatPromptTemplate \| ChatAnthropic` 组装证据、调用 MiniMax，随后校验引用 |

PDF 按现有文本层抽取，图片与纯扫描页需要另行 OCR。AsciiDoc 的外部 `include::` 保留为原文标记，`--status` 显示数量。SQLite 索引、虚拟环境和 API 密钥保存在本地。 [语料装载与切分](corpus.py) · [索引与检索器](index.py) · [运行入口](rag.py)
