from contextvars import ContextVar
import logging
import os
import sys
from typing import Any, Dict, Optional, TypedDict
from importlib import metadata
import uuid
import platform
import socket
from flask import current_app


def get_service_context() -> dict:
    # service
    entry_point = os.path.basename(
        sys.argv[0]
    )  # TODO: make this more reliable. if script name is changed, this breaks

    service_name = os.environ.get(
        "OTEL_SERVICE_NAME", entry_point
    )  # https://opentelemetry.io/docs/languages/sdk-configuration/general/#otel_service_name

    service_version = metadata.version(__package__ or entry_point)

    return {
        "service.name": service_name,
        "service.namespace": "OpenTakServer",
        "service.instance.id": uuid.uuid4(),
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


def get_context():
    """Gather ambient context about the running service. use this data to enrich telemetry context."""

    ctx = {}
    ctx.update(get_service_context())
    ctx.update(get_deployment_context())
    return ctx


class LogCtx:
    """Context manager for logging metadata.

    For example:
    ```python
    with LogCtx({"somekey":"somevalue"}) as log:
        log.info("i have extra context")

    log.info("but not me")
    ```
    """

    # thread local context var
    _log_context: ContextVar[Dict[str, Any]] = ContextVar("log_context", default={})

    def __init__(self, logger: Optional[logging.Logger] = None, **context):
        self.logger = logger or logging.getLogger()
        self.new_context = context
        self.token = {}
        self.adapter = None

    def __enter__(self):
        # merge with existing context
        existing = LogCtx._log_context.get()
        merged = {**existing, **self.new_context}

        # save old context and set new
        self.token = LogCtx._log_context.set(merged)

        # create adapter with merged context
        self.adapter = logging.LoggerAdapter(self.logger, merged)
        return self.adapter

    def __exit__(self, exc_type, exc_val, exc_tb):
        # restore previous context
        LogCtx._log_context.reset(self.token)  # type: ignore
        return False
