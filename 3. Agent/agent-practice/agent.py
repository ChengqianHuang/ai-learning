"""观察一次 Tool Calling 循环里的决策、执行、回填和终止。"""

import argparse
import json
import re
import sys
from collections.abc import Callable
from functools import partial

from model_adapter import minimax_reply, replay_reply
from notes_tool import TOOL, search_notes


def execute(call: dict, queries: set[tuple[str, int]], evidence: dict[str, dict[str, str]]) -> dict:
    arguments = call.get("input")
    result = {"type": "tool_result", "tool_use_id": call["id"]}
    try:
        if call.get("name") != TOOL["name"]:
            raise ValueError(f"本轮可用工具为 {TOOL['name']}")
        if not isinstance(arguments, dict) or set(arguments) - {"query", "top_k"}:
            raise ValueError("参数应包含 query，可选 top_k")
        query, top_k = arguments.get("query"), arguments.get("top_k", 3)
        if not isinstance(query, str) or type(top_k) is not int:
            raise ValueError("query 必须是字符串，top_k 必须是整数")
        key = (query.strip().casefold(), top_k)
        if key in queries:
            raise ValueError("相同检索已执行，请使用已有结果作答或调整关键词")
        hits = search_notes(query, top_k)
        queries.add(key)
        records = []
        for hit in hits:
            ref = f"S{len(evidence) + 1}"
            evidence[ref] = hit
            records.append({"ref": ref, **hit})
        result["content"] = json.dumps(records, ensure_ascii=False)
        print(f"  tool_result {call['id']}  命中 {len(hits)} 段")
    except ValueError as error:
        result.update(is_error=True, content=str(error))
        print(f"  tool_result {call['id']}  is_error=true  {error}")
    return result


def format_answer(blocks: list[dict], evidence: dict[str, dict[str, str]]) -> str:
    paragraphs = []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ValueError("模型 text 块缺少字符串格式的正文")
            paragraphs.append(text)
    answer = "\n".join(paragraphs)
    refs = list(dict.fromkeys(re.findall(r"\[(S\d+)\]", answer)))
    if not refs or any(ref not in evidence for ref in refs):
        raise RuntimeError("答案缺少有效的笔记引用，请对照本轮检索结果")
    sources = [f"[{ref}] {evidence[ref]['source']} · {evidence[ref]['heading']}" for ref in refs]
    return answer + "\n\n来源\n" + "\n".join(sources)


def run(question: str, reply: Callable[[list[dict]], dict], max_turns: int) -> str:
    messages: list[dict] = [{"role": "user", "content": question}]
    evidence = {}
    queries = set()
    call_ids = set()
    for turn in range(1, max_turns + 1):
        response = reply(messages)
        if not isinstance(response, dict):
            raise ValueError("模型响应应为 Messages 对象")
        blocks = response.get("content")
        reason = response.get("stop_reason")
        print(f"第 {turn} 轮  stop_reason={reason}")
        if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
            raise ValueError("模型响应缺少有效的 content 块")
        calls = [block for block in blocks if block.get("type") == "tool_use"]
        if reason == "end_turn" and not calls:
            if not queries:
                raise RuntimeError("模型在取得检索结果前结束了任务")
            if not evidence:
                return "本次检索没有命中笔记。"
            return format_answer(blocks, evidence)
        if reason != "tool_use" or not calls:
            raise RuntimeError(f"模型响应未完整结束或未给出预期的调用，stop_reason={reason}")
        if len(call_ids) + len(calls) > 8:
            raise RuntimeError("已达到工具请求预算（8 次）")
        # 完整回传本轮 assistant 内容。provider 可能附带需要原样保留的内容块。
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for call in calls:
            call_id = call.get("id")
            if not isinstance(call_id, str) or not call_id or call_id in call_ids:
                raise RuntimeError("模型返回了空或重复的工具调用 ID")
            call_ids.add(call_id)
            print(f"  tool_use {call_id}  {call.get('name')} {json.dumps(call.get('input'), ensure_ascii=False)}")
            results.append(execute(call, queries, evidence))
        messages.append({"role": "user", "content": results})
    raise RuntimeError(f"已达到模型轮数上限 {max_turns}，尚未生成最终答案")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="幂等重试")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="通过 MiniMax 进行模型决策")
    mode.add_argument("--replay-invalid", action="store_true", help="回放一次越界参数被拒绝后修正的过程")
    parser.add_argument("--max-turns", type=int, default=5, help="允许的模型轮数（默认 5）")
    args = parser.parse_args()
    if not args.question.strip() or args.max_turns < 1:
        parser.error("问题不能为空，模型轮数须为正整数")
    print("真实模型模式（MiniMax）" if args.live else "离线回放模式（预设模型消息，实际检索本地笔记）")
    reply = minimax_reply if args.live else partial(replay_reply, invalid_first=args.replay_invalid)
    try:
        answer = run(args.question.strip(), reply, args.max_turns)
    except (ValueError, RuntimeError, OSError) as error:
        sys.stdout.flush()
        parser.exit(1, f"任务结束：{error}\n")
    print("\n" + answer)


if __name__ == "__main__":
    main()
