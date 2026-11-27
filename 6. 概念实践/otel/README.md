# 可观测：用 OpenTelemetry 追踪一次跨进程调用

OpenTelemetry 是厂商中立的观测规范：SDK 在进程内产生 span，OTLP 协议把 span 发出去，后端负责存储和查询。本目录用三个脚本跑完这条链路，并把 OTLP 报文拆开看。

实现步骤、真实输出和踩到的坑在[笔记](../笔记/可观测.md)，这里只记运行方式和边界。

## 环境

Python 3.14.7，`opentelemetry-sdk` 1.45.2，`opentelemetry-proto` 1.45.2，protobuf 7.36.2。独立 `.venv`，不碰第 2 章的检索环境和第 6 章的 A2A 环境。

```bash
cd "6. 概念实践/otel"
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 运行

三个终端：

```bash
.venv/bin/python receiver.py        # OTLP/HTTP 接收端，127.0.0.1:4318
.venv/bin/python server.py          # 被观测服务，127.0.0.1:8000
.venv/bin/python client.py          # 发一次请求
```

## 四个场景

| 命令 | 实际看到 |
|---|---|
| `client.py` | 4 个 span：client 的 CLIENT、server 的 SERVER、两个 INTERNAL；跨进程父子关系正确 |
| `client.py --empty` | 服务端返回 400，三个 span 全部 ERROR，`parse_input` 带一条 exception 事件 |
| `client.py --repeat 20 --sample-ratio 0.5` | 实测 20 次里 10 条采样、10 条丢弃；采样到的每条都是完整 4 个 span，丢弃的一条都没写入 |
| `receiver.py --raw` | 先用 protobuf 文本格式打印请求，再看解析后的树 |

`--exporter console` 可以让 server 或 client 跳过网络，直接把 span 打到终端。

## 实测到的协议细节

- traceparent 头格式为 `00-<32 位十六进制 trace_id>-<16 位十六进制 span_id>-<flags>`。采样时 flags 是 `03`，丢弃时是 `02`，最低位是 sampled 标志。
- OTLP 报文里的 `trace_id` / `span_id` 是原始字节，不是十六进制字符串；十六进制是消费端转换后的显示形式。
- resource 属性由 SDK 补齐 `telemetry.sdk.name`、`telemetry.sdk.version`、`service.instance.id`，业务只需给 `service.name`。

## 边界

- 接收端只在内存里累积 span，进程重启即丢；没有落盘、没有查询接口。
- 没有鉴权，不校验来源。
- 只做 traces。metrics、logs、baggage 都没有实现。
- 用 `SimpleSpanProcessor` 同步导出，方便看到每一步。生产环境应换 `BatchSpanProcessor`。
- 没接 collector，也没接 Jaeger、Tempo 一类后端。
- 没有 tail sampling、没有敏感字段脱敏、没有采样率动态调整。
