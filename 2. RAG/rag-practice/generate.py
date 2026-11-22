"""使用 MiniMax Anthropic 兼容接口，根据检索资料生成带引用的答案。"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

import anthropic
from dotenv import load_dotenv

from prepare_rag import ROOT, prepare_request


def load_generation_config(config: dict) -> dict:
    generation = config.get("generation", {})
    if not isinstance(generation, dict):
        raise ValueError("generation 必须是配置对象")
    settings = {
        "base_url": "https://api.minimax.cn/anthropic",
        "model": "MiniMax-M3.1-Flash",
        "effort": "max",
        "max_tokens": 4096,
        "max_context_chars": 16000,
        "timeout_seconds": 120,
    }
    unknown = set(generation) - set(settings)
    if unknown:
        raise ValueError("未知 generation 配置项：" + ", ".join(sorted(unknown)))
    settings.update(generation)
    for key in ("base_url", "model", "effort"):
        if not isinstance(settings[key], str) or not settings[key].strip():
            raise ValueError(f"generation.{key} 必须是非空字符串")
    url = urlparse(settings["base_url"])
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("base_url 必须是 HTTPS 地址，不能包含凭据、查询参数或片段")
    if settings["effort"] not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("effort 必须是 low / medium / high / xhigh / max")
    for key in ("max_tokens", "max_context_chars", "timeout_seconds"):
        if type(settings[key]) is not int or settings[key] < 1:
            raise ValueError(f"generation.{key} 必须是正整数")
    return settings


def load_api_key() -> str:
    # 不覆盖调用终端已有的环境变量；Finder 启动也可读取项目本地 .env。
    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key or key == "replace-with-your-new-key":
        raise ValueError("请在项目 .env 或环境变量中设置 MINIMAX_API_KEY；不要将密钥发到聊天中")
    return key


def request_answer(client, request: dict, settings: dict) -> dict:
    system = "\n".join(m["content"] for m in request["messages"] if m["role"] == "system")
    messages = [m for m in request["messages"] if m["role"] != "system"]
    try:
        message = client.messages.create(
            model=settings["model"], max_tokens=settings["max_tokens"],
            system=system, messages=messages,
            extra_body={"output_config": {"effort": settings["effort"]}},
        )
    except anthropic.APIStatusError as error:
        # 不打印原始错误体、请求头和异常字符串，避免供应商响应回显凭据。
        hint = {
            401: "检查密钥是否正确", 402: "账户余额或可用额度不足，请在 MiniMax 控制台检查",
            403: "检查密钥的模型权限与账户状态",
            429: "检查额度或请求频率，稍后重试",
        }.get(error.status_code, "检查模型、参数及服务状态")
        raise RuntimeError(f"生成 API 返回 HTTP {error.status_code}；{hint}") from None
    except anthropic.APITimeoutError:
        raise RuntimeError("生成 API 请求超时；未自动重试，可检查控制台后再运行") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("无法连接生成 API，请检查网络和当前代理配置") from None
    text = "\n\n".join(block.text for block in message.content if block.type == "text").strip()
    if message.stop_reason != "end_turn":
        raise RuntimeError(
            f"答案未完整结束（stop_reason={message.stop_reason}）；"
            "若为 max_tokens，请提高 generation.max_tokens 或降低 effort 后重试"
        )
    if not text:
        raise RuntimeError("模型未返回可显示的 text 答案")
    # 排除代码围栏中的数组下标；只检查引用编号，不能证明结论被原文支持。
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    used = set(re.findall(r"\[([1-9]\d*)\]", prose))
    allowed = {item["citation"][1:-1] for item in request["citations"]}
    if used - allowed:
        raise RuntimeError("答案引用了不存在的资料编号，未保存为有效答案")
    return {
        "answer": text,
        "used_citations": [item["citation"] for item in request["citations"]
                           if item["citation"][1:-1] in used],
        "warnings": [] if used else ["答案没有引用编号，需要人工核对是否有资料支持"],
        "response_id": message.id,
        "response_model": message.model,
        "stop_reason": message.stop_reason,
        "usage": message.usage.model_dump(mode="json"),
    }


def render_markdown(report: dict) -> str:
    lines = [f"# {report['question']}", "", report["answer"], "", "## 本次参考资料", ""]
    for citation in report["citations"]:
        ranges = []
        for reference in citation["locations"]:
            location = reference.get("location", {})
            if "line_start" in location:
                ranges.append(f"{location['line_start']}—{location.get('line_end', location['line_start'])}")
        location_text = "；原文行 " + ", ".join(dict.fromkeys(ranges)) if ranges else ""
        lines.append(f"- {citation['citation']} `{citation['source_path']}` — {citation['title']}{location_text}")
    if report["warnings"]:
        lines.extend(["", *[f"> {warning}" for warning in report["warnings"]]])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "pipeline.json")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--question", required=True)
    args = parser.parse_args()
    try:
        settings = load_generation_config(json.loads(args.config.read_text(encoding="utf-8")))
        api_key = load_api_key()
        request = prepare_request(args.document_id, args.question, settings["max_context_chars"])
        reports = ROOT / "data/reports"
        reports.mkdir(parents=True, exist_ok=True)
        request_path = reports / f"{args.document_id}.rag_request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"生成模型：{settings['model']}；资料 {len(request['citations'])} 条；正在请求 API…", flush=True)
        with anthropic.Anthropic(
            api_key=api_key, base_url=settings["base_url"],
            timeout=settings["timeout_seconds"], max_retries=0,
        ) as client:
            result = request_answer(client, request, settings)
        report = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "document_id": args.document_id, "question": args.question,
            "generation": settings, **result, "citations": request["citations"],
            "index_chunks_sha256": request["index_chunks_sha256"],
            "index_model_revision": request["index_model_revision"],
        }
        # 各次答案独立保存，失败时不会把旧答案误标为本次结果。
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        prefix = reports / f"{args.document_id}.{stamp}.answer"
        json_path = Path(str(prefix) + ".json")
        markdown_path = Path(str(prefix) + ".md")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
        print("\n" + result["answer"])
        for warning in result["warnings"]:
            print("需核对：" + warning)
        print(f"\nToken 用量：{result['usage']}\n答案：{markdown_path}\n完整报告：{json_path}")
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f"生成停止：{error}\n")


if __name__ == "__main__":
    main()
