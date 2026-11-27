# AI Learning

我的 AI 学习笔记和动手实验。第一章讲大模型基础与调用，第二章用 Java 面试资料作知识库完成最小 RAG 实验，第三章讲 Agent 与工具调用。第六章的 A2A 实践把能力发布成远程 agent，验证发现、任务状态与中断恢复；同章的可观测实践用 OpenTelemetry 追踪一次跨进程调用，验证 span 父子关系、上下文传播、错误定位与采样。

- [大模型基础与调用](1.%20基础/笔记/1.%20基础概念.md)
- [最小 RAG 笔记](2.%20RAG/笔记/1.%20最小RAG.md)
- [手写 RAG 实验与运行说明](2.%20RAG/rag-practice/README.md)
- [LangChain 全库 RAG 与运行说明](2.%20RAG/rag-langchain/README.md)
- [Java 与后端语料来源](2.%20RAG/Java面经知识库/README.md)
- [Agent 与工具调用](3.%20Agent/笔记/1.%20Agent%20与工具调用.md)
- [Agent 代码实践与运行说明](3.%20Agent/agent-practice/README.md)
- [A2A 与远程 agent](6.%20概念实践/笔记/A2A.md)
- [A2A 实践与运行说明](6.%20概念实践/a2a/README.md)
- [可观测与 OpenTelemetry](6.%20概念实践/笔记/可观测.md)
- [可观测实践与运行说明](6.%20概念实践/otel/README.md)

第一次运行可以从第三章开始。在仓库根目录用 Python 3.10 或以上版本执行下面的脚本。首次运行会下载 MCP SDK，默认的工具调用、状态恢复和 MCP 实验均在本地运行。

```sh
"./3. Agent/agent-practice/run.command"
```

RAG 提供手写单文档实验与 LangChain 全库实现。全库实现按来源清单处理 Java 与后端语料中的 Markdown、AsciiDoc 和 PDF，使用本地 E5 做跨文档检索，并可调用 MiniMax 生成带引用的答案。

仓库保留语料来源清单和许可证。原始 Markdown、AsciiDoc 和 PDF 统一放在本地 `corpus/`，可按来源清单下载。虚拟环境、API 密钥和运行产物也由本地环境管理。

本仓库公开供阅读和学习。原创笔记和示例代码目前尚未指定统一的开源许可证。第三方文章、图书和所引用的项目各有自己的授权条款，资料目录保留了相应的来源与许可说明。 [语料来源与授权](2.%20RAG/Java面经知识库/README.md#来源与授权)
