from dataclasses import dataclass
import logging
from typing import Optional
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.metrics._internal import Meter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry import metrics

from opentakserver.telemetry.context import get_context
@dataclass
class MetricsOptions:
    enabled: bool = False
    service_name: str = "opentakserver"

def setup_metrics(opts: MetricsOptions) -> Optional[Meter]:
    if opts.enabled == False:
        logging.info("metrics exporter disabled.")
        return
    
    metric_exporter = OTLPMetricExporter()  # configure via OTEL_* env vars
    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=5000)
    ctx = get_context(opts.service_name)
    resource = Resource.create(ctx)

    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[reader])
    )
    
    return metrics.get_meter(name=ctx.get("service.name"),version=ctx.get("service.version"))