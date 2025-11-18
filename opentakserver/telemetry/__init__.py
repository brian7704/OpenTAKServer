
import logging
from dataclasses import dataclass
from typing import Optional
from opentelemetry.metrics._internal import Meter
from opentelemetry.instrumentation.logging import LoggingInstrumentor

from opentakserver.telemetry.logs import LoggingOptions, setup_logging
from opentakserver.telemetry.metrics import MetricsOptions, setup_metrics
from opentakserver.telemetry.traces import TracingOptions, setup_tracing

@dataclass
class TelemetryOpts:
    logging: LoggingOptions
    metrics: MetricsOptions
    tracing: TracingOptions

def setup_telemetry(opts:TelemetryOpts,service_name:str="") -> tuple[logging.Logger,Optional[Meter]]:
    if service_name != "":
        opts.logging.service_name = service_name
        opts.metrics.service_name = service_name
        opts.tracing.service_name = service_name
        
    logger = setup_logging(opts.logging)
    meter = setup_metrics(opts.metrics)
    setup_tracing(opts.tracing)
    
    # --- Auto instrumentation ---
    LoggingInstrumentor().instrument()
    
    return logger,meter