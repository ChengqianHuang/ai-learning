"""被观测的服务：一个 HTTP 端点，内部两层 span，带一条失败路径。

从请求头提取 W3C traceparent，作为 SERVER span 的父上下文。
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

SERVICE_NAME = "otel-server"
TRACER = None


def build_tracer(exporter):
    provider = TracerProvider(
        resource=Resource.create({
            "service.name": SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment.name": "local",
        })
    )
    if exporter == "console":
        span_exporter = ConsoleSpanExporter()
    else:
        span_exporter = OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces")
    # SimpleSpanProcessor 同步导出，span 一结束就能在接收端看到。
    # 生产环境用 BatchSpanProcessor，批量发送并限制内存队列。
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(SERVICE_NAME)


def parse_input(raw):
    return [line for line in raw.splitlines() if line.strip()]


def score_text(lines):
    with TRACER.start_as_current_span("score_text") as span:
        words = [word for line in lines for word in line.split()]
        span.set_attribute("demo.line_count", len(lines))
        span.set_attribute("demo.word_count", len(words))
        span.set_attribute("demo.has_fence", any(line.startswith("```") for line in lines))
        span.set_attribute("demo.pipeline", ["parse", "score"])
        return {"lines": len(lines), "words": len(words)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")

        # W3C propagator 按小写键查找；HTTP 头本身大小写不敏感，这里先归一化。
        carrier = {key.lower(): value for key, value in self.headers.items()}
        parent = propagate.extract(carrier)

        with TRACER.start_as_current_span(
            "POST /analyse",
            context=parent,
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": "POST",
                "url.path": self.path,
                "http.request.body.size": len(raw),
            },
        ) as span:
            try:
                with TRACER.start_as_current_span(
                    "parse_input",
                    record_exception=False,
                    set_status_on_exception=False,
                ) as child:
                    child.set_attribute("demo.input_chars", len(raw))
                    try:
                        lines = parse_input(raw)
                        if not lines:
                            raise ValueError("输入为空，无法统计")
                    except ValueError as exc:
                        child.record_exception(exc)
                        child.set_status(Status(StatusCode.ERROR, str(exc)))
                        raise
                    child.set_attribute("demo.line_count", len(lines))

                stats = score_text(lines)
                span.set_status(Status(StatusCode.OK))
                self.send_json(200, {
                    "trace_id": format(span.get_span_context().trace_id, "032x"),
                    "stats": stats,
                })
            except ValueError as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute("error.type", type(exc).__name__)
                self.send_json(400, {
                    "trace_id": format(span.get_span_context().trace_id, "032x"),
                    "error": str(exc),
                })

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    global TRACER
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--exporter", choices=["otlp", "console"], default="otlp")
    args = parser.parse_args()
    TRACER = build_tracer(args.exporter)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"{SERVICE_NAME} http://127.0.0.1:{args.port}/analyse  exporter={args.exporter}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
