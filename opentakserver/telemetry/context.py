from contextvars import ContextVar, Token
from heapq import merge
import logging
import os
import sys
from typing import Any, Dict, Optional, TypedDict
from importlib import metadata
import uuid
import platform
import socket
from flask import current_app


def get_service_context(service_name:str = "") -> dict:
    if service_name == "":
        # Determine a stable service name and version. Prefer env override.
        service_name = os.environ.get("OTEL_SERVICE_NAME","opentakserver")
        
    try:
        service_version = metadata.version(service_name)
    except metadata.PackageNotFoundError:
        try:
            service_version = metadata.version("opentakserver")
        except metadata.PackageNotFoundError:
            service_version = ""
        service_version = ""

    return {
        "service.name": service_name,
        "service.namespace": "OpenTakServer",
        "service.instance.id": str(uuid.uuid4()),
        "service.version": service_version,
    }


def get_deployment_context() -> dict:
    deployment_env = os.environ.get("FLASK_ENV", os.environ.get("APP_ENV", "unknown"))
    if deployment_env == "unknown":
        try:
            # incase flask app isn't bound yet.
            # TODO: find a cleaner way to decouple from flask app
            debug = current_app.config.get("DEBUG") in ["true", "1", "yes"]
            deployment_env = current_app.config.get(
                "FLASK_ENV",
                current_app.config.get(
                    "APP_ENV", "development" if debug else "unknown"
                ),
            )
        except Exception:
            deployment_env = "unknown"

    return {"deployment.environment.name": deployment_env}


def get_context(service_name:str) -> dict:
    """Gather ambient context about the running service. use this data to enrich telemetry context."""

    ctx = {}
    ctx.update(get_service_context(service_name))
    ctx.update(get_deployment_context())
    return ctx


# thread local context var
_log_context: ContextVar[Dict[str, Any]] = ContextVar("log_context", default={})

# A filter instance shared across LogCtx usages; it reads the ContextVar at
# emit time and injects values into the LogRecord.
class _RecordFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _log_context.get() or {}
        if not ctx:
            return True
        # inject keys directly onto the record when possible, otherwise
        # stash them under `ots_context` to avoid clobbering LogRecord attrs.
        for k, v in ctx.items():
            if hasattr(record, k):
                oc = getattr(record, "ots_context", None)
                if oc is None:
                    oc = {}
                    setattr(record, "ots_context", oc)
                oc[k] = v
            else:
                setattr(record, k, v)
        return True

class LogCtx:
    """Context manager for logging metadata.

    For example:
    ```python
    
    with LogCtx({"somekey":"somevalue"}):
        logging.info("i have extra context")

    logging.info("but not me")
    ```
    """

    

    _filter = _RecordFilter()
    _filter_refcount = 0

    def __init__(self, logger: Optional[logging.Logger] = None, **context):
        # logger is kept only for rare internal use; callers should use
        # logging.getLogger() and rely on the filter to inject context.
        self.logger = logger or logging.getLogger()
        self.new_context = context
        self.token: Optional[Token[Dict[str, Any]]] = None

    def __enter__(self):
        # merge with existing context and set it
        existing = _log_context.get() or {}
        merged = {**existing, **self.new_context}
        self.token = _log_context.set(merged)

        # ensure our filter is attached to the root logger (only once)
        root = logging.getLogger()
        if LogCtx._filter_refcount == 0:
            root.addFilter(LogCtx._filter)
        LogCtx._filter_refcount += 1

        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        # restore previous context
        if self.token is not None:
            try:
                _log_context.reset(self.token)  # type: ignore
            except Exception:
                pass

        # detach our filter if no active contexts remain
        LogCtx._filter_refcount = max(0, LogCtx._filter_refcount - 1)
        if LogCtx._filter_refcount == 0:
            try:
                logging.getLogger().removeFilter(LogCtx._filter)
            except Exception:
                pass

        self.token = None
        return False
