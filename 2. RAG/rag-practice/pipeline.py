"""编排单文档解析、切分、向量建库、检索与答案生成流程。"""
import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="解析 → Token 切分 → 向量建库 → 检索 → 生成答案")
    parser.add_argument("--config", type=Path, default=ROOT / "pipeline.json")
    parser.add_argument("--from-index", metavar="DOCUMENT_ID", help="复用已有索引，仅执行检索和生成")
    args = parser.parse_args()
    args.config = args.config.resolve()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    max_tokens = config["max_tokens"]
    if not isinstance(config["match"], str) or not isinstance(config["question"], str):
        parser.error("match 和 question 必须是字符串")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 512:
        parser.error("max_tokens 必须是 1—512 的整数")
    if type(config.get("offline", True)) is not bool:
        parser.error("offline 必须是 true 或 false")
    for key, default in (("batch_size", 8), ("top_k", 5)):
        if type(config.get(key, default)) is not int or config.get(key, default) < 1:
            parser.error(f"{key} 必须是正整数")
    if not config["question"].strip():
        parser.error("question 不能为空")

    missing = [name for name in ("markdown_it", "mdit_py_plugins", "numpy", "transformers", "sentence_transformers", "anthropic", "dotenv")
               if importlib.util.find_spec(name) is None]
    if missing:
        parser.error("当前虚拟环境缺少依赖：" + ", ".join(missing))

    from generate import load_api_key, load_generation_config
    try:
        load_generation_config(config)
        load_api_key()  # 提前检查，避免建库全部完成后才发现缺少密钥。
    except ValueError as error:
        parser.error(str(error))

    logs = ROOT / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    log_path = logs / f"pipeline-{stamp}.log"
    report_path = logs / f"pipeline-{stamp}.json"
    report = {"status": "running", "config": config, "from_index": args.from_index,
              "log_path": str(log_path), "steps": []}
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if config.get("offline", True):
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"

    with log_path.open("w", encoding="utf-8") as log:
        def emit(message):
            print(message, flush=True)
            log.write(message + "\n")
            log.flush()

        def run(name, script, *arguments):
            emit(f"\n=== {name} ===")
            step = {"name": name, "status": "running"}
            report["steps"].append(step)
            started = time.monotonic()
            try:
                # 使用参数列表调用，无 Shell 拼接；同一虚拟环境、固定工作目录。
                with subprocess.Popen(
                    [sys.executable, "-u", str(ROOT / script), *arguments],
                    cwd=ROOT, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                ) as process:
                    assert process.stdout is not None
                    for line in process.stdout:
                        emit(line.rstrip("\n"))
                    code = process.wait()
                if code:
                    raise RuntimeError(f"{name}失败，退出码 {code}；后续步骤未执行")
                step["status"] = "success"
            except BaseException:
                step["status"] = "failed"
                raise
            finally:
                step["seconds"] = round(time.monotonic() - started, 2)

        try:
            emit(f"项目：{ROOT}\n配置：{args.config}\n离线模型缓存：{config.get('offline', True)}")
            if args.from_index:
                document_id = args.from_index
                emit(f"复用已有索引：{document_id}")
            else:
                run("1/6 解析 Markdown", "ingest.py", "--match", config["match"], "--limit", "1")
                ingest_report = json.loads((ROOT / "data/parsed/ingest_report.json").read_text(encoding="utf-8"))
                if len(ingest_report) != 1 or ingest_report[0]["status"] != "success":
                    raise RuntimeError("解析报告不符合预期，停止执行")
                document_id = ingest_report[0]["document_id"]
                emit(f"自动选中文档：{ingest_report[0]['path']}\n文档 ID：{document_id}")
                run("2/6 按 Token 切分", "build_chunks.py", "--document-id", document_id,
                    "--max-tokens", str(max_tokens))
                run("3/6 Embedding 检查", "inspect_embeddings.py", "--document-id", document_id,
                    "--question", config["question"])
                run("4/6 批量向量化并保存", "build_vectors.py", "--document-id", document_id,
                    "--batch-size", str(config.get("batch_size", 8)))
            report["document_id"] = document_id
            run("5/6 Top-K 检索", "search.py", "--document-id", document_id,
                "--question", config["question"], "--top-k", str(config.get("top_k", 5)))
            run("6/6 根据检索资料生成答案", "generate.py", "--config", str(args.config),
                "--document-id", document_id, "--question", config["question"])
            report["status"] = "success"
            emit("\n流程完成：检索与答案生成完成，答案及来源已保存到 data/reports/。")
        except (Exception, KeyboardInterrupt) as error:
            report["status"] = "failed"
            report["error"] = str(error) or "运行被中断"
            emit("\n流程停止：" + report["error"])
        finally:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            emit(f"日志：{log_path}\n运行报告：{report_path}")

    if report["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
