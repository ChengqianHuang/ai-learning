"""最小 OTLP/HTTP 接收端。

只实现 POST /v1/traces：解析 protobuf，把同一 trace 的 span 按父子关系打印成树。
不校验鉴权、不落盘、不去重。
"""
import argparse
import json
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

SPAN_KIND = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS_CODE = {0: "UNSET", 1: "OK", 2: "ERROR"}

traces = defaultdict(list)


def any_value(value):
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [any_value(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: any_value(kv.value) for kv in value.kvlist_value.values}
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return getattr(value, kind)


def fmt_attributes(attributes, limit=6):
    parts = []
    for kv in attributes:
        raw = any_value(kv.value)
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        if len(text) > 48:
            text = text[:45] + "..."
        parts.append(f"{kv.key}={text}")
    if len(parts) > limit:
        return ", ".join(parts[:limit]) + f" (+{len(parts) - limit})"
    return ", ".join(parts)


def service_name(resource):
    for kv in resource.attributes:
        if kv.key == "service.name":
            return str(any_value(kv.value))
    return "unknown"


def print_tree(trace_id, records):
    by_id = {record["span"].span_id: record for record in records}
    children = defaultdict(list)
    roots = []
    for record in records:
        parent = record["span"].parent_span_id
        if parent and parent in by_id:
            children[parent].append(record)
        else:
            roots.append(record)
    roots.sort(key=lambda record: record["span"].start_time_unix_nano)

    print(f"\ntrace {trace_id}  spans={len(records)}")

    def walk(record, depth):
        span = record["span"]
        duration = (span.end_time_unix_nano - span.start_time_unix_nano) / 1e6
        indent = "  " * depth
        kind = SPAN_KIND.get(span.kind, span.kind)
        status = STATUS_CODE.get(span.status.code, span.status.code)
        print(f"{indent}- [{record['service']}] {span.name}  {kind}  {duration:.2f}ms  {status}")
        attrs = fmt_attributes(span.attributes)
        if attrs:
            print(f"{indent}    attrs: {attrs}")
        for event in span.events:
            print(f"{indent}    event: {event.name}  {fmt_attributes(event.attributes)}")
        for child in sorted(children[span.span_id], key=lambda item: item["span"].start_time_unix_nano):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    show_raw = False

    def do_POST(self):
        if self.path != "/v1/traces":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        request = trace_service_pb2.ExportTraceServiceRequest()
        request.ParseFromString(body)
        if self.show_raw:
            print(request)

        touched = set()
        for resource_spans in request.resource_spans:
            service = service_name(resource_spans.resource)
            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    key = span.trace_id.hex()
                    traces[key].append({"span": span, "service": service})
                    touched.add(key)
        for key in touched:
            print_tree(key, traces[key])

        payload = trace_service_pb2.ExportTraceServiceResponse().SerializeToString()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--raw", action="store_true", help="先用 protobuf 文本格式打印原始请求")
    args = parser.parse_args()
    Handler.show_raw = args.raw
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"OTLP/HTTP 接收端 http://127.0.0.1:{args.port}/v1/traces")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
