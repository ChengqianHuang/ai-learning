"""不经过 SDK，直接看 A2A 的协议层：HTTP + JSON-RPC 2.0。

三个步骤分别对应 A2A 的三个最小事实：
1. 能力先发布在 well-known 路径，客户端不需要私有约定就能发现。
2. 一次 SendMessage 就产生一个带 ID 的 Task，结果以 Artifact 承载。
3. Task 可以用 ID 跨请求取回，进程重启前的进度不依赖客户端连接。
"""
import json
import uuid

import httpx

BASE_URL = "http://127.0.0.1:9999"


def show(title: str, payload) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:1800])


def rpc(http: httpx.Client, method: str, params: dict, call_id: str = "1") -> dict:
    body = {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params}
    response = http.post(BASE_URL + "/", json=body, headers={"A2A-Version": "1.0"})
    response.raise_for_status()
    return response.json()


def main() -> None:
    with httpx.Client(timeout=30) as http:
        card = http.get(BASE_URL + "/.well-known/agent-card.json").json()
        show("1. GET /.well-known/agent-card.json", {
            "name": card["name"],
            "supportedInterfaces": card["supportedInterfaces"],
            "capabilities": card["capabilities"],
            "skills": [{"id": s["id"], "name": s["name"]} for s in card["skills"]],
        })

        reply = rpc(http, "SendMessage", {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"text": "统计这段文字：协议层只有 HTTP 和 JSON-RPC。"}],
            }
        })
        task = reply["result"]["task"]
        show("2. SendMessage 返回 Task", {
            "id": task["id"],
            "contextId": task["contextId"],
            "state": task["status"]["state"],
            "artifacts": [
                {"name": a.get("name"), "parts": a["parts"]} for a in task.get("artifacts", [])
            ],
        })

        fetched = rpc(http, "GetTask", {"id": task["id"]}, call_id="2")
        show("3. GetTask 用同一个 ID 取回", {
            "id": fetched["result"]["id"],
            "state": fetched["result"]["status"]["state"],
            "artifactId": fetched["result"].get("artifacts", [{}])[0].get("artifactId"),
        })

        error = rpc(http, "SendMessage", {"message": {"role": "ROLE_USER"}}, call_id="3")
        show("4. 缺必填字段时的错误形状", error)

        # v0.3 的方法名是小写带斜杠。v1.0 改成 PascalCase，旧名字不再响应。
        legacy = http.post(
            BASE_URL + "/",
            json={
                "jsonrpc": "2.0",
                "id": "4",
                "method": "message/send",
                "params": {"message": {"messageId": str(uuid.uuid4()),
                                       "role": "ROLE_USER", "parts": [{"text": "hi"}]}},
            },
        ).json()
        show("5. 用 v0.3 的 message/send", legacy)


if __name__ == "__main__":
    main()
