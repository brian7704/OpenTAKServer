"""Functions setup observability instrumentation as OTS dependency
"""

from typing import Any

from opentakserver.telemetry.logs import ConsoleSinkOpts, FileSinkOpts, LoggingOptions
from opentakserver.telemetry.metrics import MetricsOptions
from opentakserver.telemetry.traces import TracingOptions


def configure_logging(cfg: dict[str, Any]) -> LoggingOptions:
    """Map OTS config to logging config

    Args:
        cfg (dict[str, Any]): DefaultConfig.to_dict or yaml loaded OTS config

    Returns:
        LoggingOptions: Options to use with setup_logging function
    """
    opts = LoggingOptions()
    if cfg.get("DEBUG") in ["true", "1", "yes"]:
        opts.level = "DEBUG"
    else:
        opts.level = cfg.get("OTS_LOG_LEVEL")

    # file
    if cfg.get("OTS_LOG_FILE_ENABLED", True):
        opts.file = FileSinkOpts(
            backup_count=cfg.get("OTS_BACKUP_COUNT"),
            directory=cfg.get("OTS_DATA_FOLDER"),
            name="opentakserver.log",
            format=cfg.get("OTS_LOG_FILE_FORMAT"),
            rotate_interval=cfg.get("OTS_LOG_ROTATE_INTERVAL"),
            rotate_when=cfg.get("OTS_LOG_ROTATE_WHEN"),
            level=cfg.get("OTS_LOG_FILE_LEVEL"),
        )

    # console
    if cfg.get("OTS_LOG_CONSOLE_ENABLED", True):
        opts.console = ConsoleSinkOpts(
            format=cfg.get("OTS_LOG_CONSOLE_FORMAT"),
            level=cfg.get("OTS_LOG_CONSOLE_LEVEL"),
        )

    # otel
    opts.otel_enabled = cfg.get("OTS_LOG_OTEL_ENABLE")
    return opts


def configure_metrics(cfg: dict[str,Any]) -> MetricsOptions:
    return MetricsOptions()

def configure_tracing(cfg: dict[str,Any]) -> TracingOptions:
    return TracingOptions()