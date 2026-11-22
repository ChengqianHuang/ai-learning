# RAG 实践项目

当前单文档流程：**Markdown 解析 → 按模型 Token 预算切分 → Embedding 检查 → 全部 Chunk 向量化保存 → Top-K 检索 → 根据检索资料生成答案**。

## 运行

首次克隆后，在 `rag-practice` 目录用 Python 3.14 创建虚拟环境并安装依赖。当前依赖版本已在 macOS Apple Silicon、Python 3.14.7 上验证。

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
```

打开 `.env`，把 `MINIMAX_API_KEY` 的占位值替换成自己的密钥。也可以从同名环境变量读取，终端环境变量优先。

默认示例需要一篇 LinkedHashMap 原文。有现成的本地语料库即可直接运行。首次克隆时，可下载固定版本的 Markdown，并保存到 `rag-practice` 上一级的 `Java面经知识库/corpus/JavaGuide/docs/java/collection/linkedhashmap-source-code.md`。 [下载示例原文](https://raw.githubusercontent.com/Snailclimb/JavaGuide/992dae31eade2a34ba8dbbbcf5ed9de5511325ec/docs/java/collection/linkedhashmap-source-code.md)

首次运行时，如本机缺少 E5 模型缓存，先将 `pipeline.json` 的 `offline` 设为 `false` 以下载模型。随后在 Finder 中双击 `run.command`，或在当前目录运行：

```bash
bash run.command
```

入口使用 `.venv/bin/python`，无需手动激活环境。模型下载后可把 `offline` 改回 `true`。

建好索引后，可以复用已有向量，只执行检索和生成：

```bash
bash run.command --from-index 40e64a56b24583cd
```

生成阶段会把本次选中的原文片段发给 MiniMax API。HF 离线配置仅控制本地 Embedding 模型缓存，生成阶段仍需要联网。

## 配置

编辑 `pipeline.json`：

- `match`：按来源路径筛选，选择清单中第一个匹配的 Markdown 文档。
- `max_tokens`：切分上限，默认 480；包含标题、`passage: ` 前缀及特殊 Token。
- `question`：验证用的问题，应与选择的文档主题对应。
- `batch_size`：模型每批处理的 Chunk 数量，默认 8。
- `top_k`：查询返回的片段数量，默认 5。
- `offline`：默认 true，复用已经下载的模型缓存。首次下载或缺少缓存时改为 false，使用当前网络/代理配置访问模型站点。
- `generation`：API 地址、生成模型、思考深度 `effort`、输出上限 `max_tokens`、参考资料字符预算 `max_context_chars`、请求超时秒数。默认 MiniMax-M3.1-Flash / max / 4096。此处的输出上限与 Embedding 的 512 Token 输入上限无关。

`max_context_chars` 用于完整片段装包，不代表生成模型的 Token 数；预算包含资料中的标题、来源和位置。生成请求还包含系统提示和问题。API 返回实际 Token 用量供检查。

入口自动从解析报告取文档 ID，传递给后续步骤，不需要复制文件名。
遇到解析失败、超长代码/表格、超长 Chunk 或模型异常时，立即停止后续步骤。

## 产物

- `data/parsed/`：解析后的 Block、文档来源及解析报告。
- `data/chunks/`：按 Token 预算生成的 Chunk，重新运行会覆盖同文档的旧结果。
- `data/reports/<文档ID>.embedding_check.json`：长度及向量化验证结果。
- `data/indexes/<文档ID>/vectors.npy`：归一化 float32 向量矩阵；第 i 行对应 chunks.jsonl 第 i 条。
- `data/indexes/<文档ID>/chunks.jsonl`：与向量顺序一致的正文、Chunk ID 及来源快照。
- `data/indexes/<文档ID>/metadata.json`：模型、固定提交版本、输入前缀、维度、文件哈希和库版本。
- `data/reports/<文档ID>.search.json`：本次问题、排序分数及完整检索结果。
- `data/reports/<文档ID>.rag_request.json`：本次送入模型的系统提示、问题、原文资料及编号映射，不含密钥。
- `data/reports/<文档ID>.<运行时间>.answer.md`：可阅读的生成答案和文件来源、行号。
- `data/reports/<文档ID>.<运行时间>.answer.json`：答案、来源、模型、停止原因、Token 用量、索引版本。每次成功生成单独保存。
- `data/logs/`：每次运行的独立日志、阶段耗时及成功/失败报告。

第三步使用一条片段验证模型；第四步批量处理当前文档全部 Chunk；第五步加载已保存向量，以问题向量的点积计算精确余弦相似度并排序。
当前规模使用 NumPy 矩阵进行精确检索，尚未使用专门的向量数据库或近似最近邻索引。
重复执行会重新生成当前文档的向量。向量文件和正文分别原子替换，元数据最后写入；查询必须通过文件哈希、数量和维度校验，避免读取不一致的文件组合。
第六步把 Top-K 原文完整装包，调用 MiniMax 的 Anthropic 兼容接口，只使用返回内容中的 `text` 块作答。模型引用不存在的资料编号、输出截断或请求失败时会停止，不会保存为成功答案；无引用编号会显示核对提示。引用编号合法不代表结论一定被原文支持，仍需核对资料。

API 默认不自动重试；`stop_reason=max_tokens` 时请提高 `generation.max_tokens`，或降低 `effort` 后重试。已生成的历史答案不受失败请求影响。

**当前范围仍为一份选中文档，尚未扩展到全部 521 份语料。已于 2026-11-17 使用配置的密钥完成真实检索与答案生成，停止原因 end_turn；答案和报告保存在 data/reports/40e64a56b24583cd.20261117-201941-059239.answer.md / .json。**

首次答案抽查：LRU 核心机制及示例能对应检索资料；答案中“单线程、非并发场景”的适用条件未在引用 [2] 的原文中明确说明。这说明编号检查通过后，仍需要逐句检查结论是否得到所引片段支持。

单独查询已保存的数据，可执行：

```bash
python search.py --document-id 40e64a56b24583cd --question "LinkedHashMap 如何实现 LRU 缓存？" --top-k 5
```

单独查询不重新计算文档向量，仍需要加载同一个版本的模型来计算问题向量。

本地验证生成请求的协议、引用和错误处理，可以运行 `.venv/bin/python -m unittest discover -s tests -v`。测试使用模拟 HTTP 响应，无需配置密钥。
