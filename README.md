# AI Learning

我的 AI 学习笔记和动手实验。第一章讲通用的大模型基础与调用。第二章用 Java 面试资料作知识库，完成最小 RAG 实验。

- [大模型基础与调用](1.%20基础/笔记/1.%20基础概念.md)
- [最小 RAG 笔记](2.%20RAG/笔记/1.%20最小RAG.md)
- [RAG 实验与运行说明](2.%20RAG/rag-practice/README.md)
- [Java 与后端语料来源](2.%20RAG/Java面经知识库/README.md)

RAG 实验使用本地 E5 做 Embedding，并用 NumPy 检索。MiniMax 根据命中的原文片段生成带引用的答案。当前问答使用一篇 LinkedHashMap 文档，语料库提供后续扩展用的 Markdown、AsciiDoc 和 PDF 来源。

仓库保留语料来源清单和许可证。原始 Markdown、AsciiDoc 和 PDF 统一放在本地 `corpus/`，可按来源清单下载。虚拟环境、API 密钥和运行产物也由本地环境管理。
