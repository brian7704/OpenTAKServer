

import logging
from opentakserver.telemetry.context import get_context
from opentelemetry.sdk.resources import Resource
from dataclasses import dataclass
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry import trace


@dataclass
class TracingOptions:
    enabled: bool = False
    service_name: str = "opentakserver"

def setup_tracing(opts: TracingOptions):
    if opts.enabled == False:
        logging.info("traces exporter disabled.")
        return
    
    ctx = get_context(opts.service_name)
    resource = Resource.create(ctx)
    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(trace_provider)