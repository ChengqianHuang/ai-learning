"""客户端：起 CLIENT span，把 traceparent 注入请求头，再发 POST。"""
import argparse
import urllib.error
import urllib.request

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import SpanKind, Status, StatusCode

SERVICE_NAME = "otel-client"


def build_tracer(exporter, ratio):
    provider = TracerProvider(
        resource=Resource.create({"service.name": SERVICE_NAME}),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    if exporter == "console":
        span_exporter = ConsoleSpanExporter()
    else:
        span_exporter = OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces")
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(SERVICE_NAME)


def call(tracer, url, payload):
    with tracer.start_as_current_span(
        "POST /analyse",
        kind=SpanKind.CLIENT,
        attributes={"server.address": "127.0.0.1", "url.full": url},
    ) as span:
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        propagate.inject(headers)
        traceparent = headers.get("traceparent", "")
        span.set_attribute("http.request.header.traceparent", traceparent)

        request = urllib.request.Request(
            url, data=payload.encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
                status = response.status
            span.set_attribute("http.response.status_code", status)
            span.set_status(Status(StatusCode.OK))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            status = exc.code
            span.set_attribute("http.response.status_code", status)
            span.set_status(Status(StatusCode.ERROR, f"HTTP {status}"))

        context = span.get_span_context()
        return {
            "trace_id": format(context.trace_id, "032x"),
            "span_id": format(context.span_id, "016x"),
            "sampled": context.trace_flags.sampled,
            "traceparent": traceparent,
            "http_status": status,
            "body": body,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/analyse")
    parser.add_argument("--exporter", choices=["otlp", "console"], default="otlp")
    parser.add_argument("--sample-ratio", type=float, default=1.0)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--empty", action="store_true", help="发送空正文，触发服务端错误路径")
    args = parser.parse_args()
    if not 0.0 <= args.sample_ratio <= 1.0:
        parser.error("sample-ratio 必须在 0 和 1 之间")

    tracer = build_tracer(args.exporter, args.sample_ratio)
    payload = "" if args.empty else "第一行\n第二行\n```python\nprint(1)\n```"
    for index in range(args.repeat):
        result = call(tracer, args.url, payload)
        print(f"#{index + 1} trace_id={result['trace_id']} sampled={result['sampled']} http={result['http_status']}")
        print(f"    traceparent={result['traceparent']}")
        print(f"    body={result['body'][:120]}")
    trace.get_tracer_provider().shutdown()


if __name__ == "__main__":
    main()
