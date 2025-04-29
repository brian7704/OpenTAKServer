from __future__ import annotations

from flask import current_app as app
from abc import abstractmethod

from flask import Flask, Blueprint, url_for

from opentakserver.extensions import logger
from opentakserver.plugins.BasePlugin import BasePlugin


class Plugin(BasePlugin):
    """
    Generic plugin
    """

    def __init__(self):
        self._app: Flask | None = None
        self._config = {}
        self.metadata = {}
        self.name = ""
        self.distro = ""
        self.routes = []

    group = "opentakserver.plugin"
    blueprint: Blueprint | None = None

    @abstractmethod
    def activate(self, app: Flask, enabled: bool) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def get_info(self) -> dict | None: ...

    @abstractmethod
    def load_metadata(self) -> {}: ...

    def has_no_empty_params(self, rule):
        defaults = rule.defaults if rule.defaults is not None else ()
        arguments = rule.arguments if rule.arguments is not None else ()
        return len(defaults) >= len(arguments)

    def get_plugin_routes(self, url_prefix: str):
        for rule in app.url_map.iter_rules():
            # Filter out rules we can't navigate to in a browser
            # and rules that require parameters
            if ("GET" in rule.methods or "POST" in rule.methods) and self.has_no_empty_params(rule):
                url = url_for(rule.endpoint, **(rule.defaults or {}))
                if url.startswith(url_prefix) and url not in self.routes:
                    self.routes.append(url)
                    logger.warning(f"Adding {url}")
