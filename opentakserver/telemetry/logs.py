from contextvars import ContextVar, Token
from dataclasses import dataclass
import datetime
import sys
from typing import Any, Callable, Dict, Literal, Optional, TypedDict

import logging
import logging.handlers
import os

from click import Context
import colorlog

from pythonjsonlogger.json import JsonFormatter
from pythonjsonlogger.core import RESERVED_ATTRS
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk.resources import Resource

from opentakserver.telemetry.context import get_context


@dataclass
class FileSinkOpts:
    directory: str
    name: str

    # rotation settings
    rotate_when: str
    rotate_interval: int
    backup_count: int

    format: Literal["ndjson", "ots", "plain"]
    level: str = "INFO"


@dataclass
class ConsoleSinkOpts:
    format: Literal["ndjson", "ots", "plain"]

    level: str = "INFO"

@dataclass
class LoggingOptions:
    service_name: str = "opentakserver"
    file: Optional[FileSinkOpts] = None
    console: Optional[ConsoleSinkOpts] = None
    otel_enabled: bool = False
    level: str = "INFO"


class ContextFilter(logging.Filter):
    """Add context to non-otel log handlers"""

    def __init__(self,context_getter:Callable[[],dict]):
        super().__init__()
        self.context_getter = context_getter

    def filter(self, record):
        self.context = self.context_getter()
        for key, value in self.context.items():
            setattr(record, key.replace(".", "_"), value)
        return True


def _set_formatter(handler: logging.Handler, format: Literal["ndjson", "ots", "plain"]):
    if format == "ndjson":
        show_attrs = [
            "levelname",
            "name",
            "pathname",
            "lineno",
            "funcName",
            "exc_info",
            "stack_info",
            "exc_text",
        ]
        # python-json-logger is quite verbose. hide most in RESERVED_ATTRS except some useful ones.
        hidden_attrs = list(filter(lambda x: x not in show_attrs, RESERVED_ATTRS))

        handler.setFormatter(JsonFormatter(timestamp=True, reserved_attrs=hidden_attrs))
    elif format == "ots":
        if sys.stdout.isatty():
            handler.setFormatter(
                colorlog.ColoredFormatter(
                    "%(log_color)s[%(asctime)s] - OpenTAKServer[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        else:
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] - OpenTAKServer[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"
                )
            )
    else:
        # plain and unknown, just use default formatter.
        ...


def setup_logging(opts: LoggingOptions) -> logging.Logger:
    """Setup global python logger with log sinks and enriched context

    Call this before starting flask or any other frameworks
    """

    logger = logging.getLogger("")  # root logger

    # parse log level from config
    logLevel = logging.getLevelNamesMapping().get(opts.level.upper(), logging.INFO)
    logger.setLevel(logLevel)

    def _set_level(handler: logging.Handler, level: str):
        if opts.level != level:
            # allow per sink override
            logLevel = logging.getLevelNamesMapping().get(
                opts.level.upper(), logging.INFO
            )
            handler.setLevel(logLevel)

    logger.handlers.clear()
    
    logger.addFilter(ContextFilter(lambda : get_context(opts.service_name)))

    # Console handler
    if opts.console is not None:
        ch = colorlog.StreamHandler()
        _set_formatter(ch, opts.console.format)
        _set_level(ch, opts.console.level)
        logger.addHandler(ch)

    # File handler
    if opts.file is not None:
        # ensure dir exists
        os.makedirs(opts.file.directory, exist_ok=True)

        # setup rotating logging handler
        fh = logging.handlers.TimedRotatingFileHandler(
            os.path.join(opts.file.directory, opts.file.name),
            when=opts.file.rotate_when,
            interval=opts.file.rotate_interval,
            backupCount=opts.file.backup_count,
        )

        _set_formatter(fh, opts.file.format)
        _set_level(fh, opts.file.level)

        logger.addHandler(fh)

    # OTel handler
    if opts.otel_enabled:
        provider = LoggerProvider(resource=Resource.create(get_context(opts.service_name)))
        exporter = OTLPLogExporter()
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        set_logger_provider(provider)
        oh = LoggingHandler(logger_provider=provider)
        logger.addHandler(oh)

    return logger
