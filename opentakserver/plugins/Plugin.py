from __future__ import annotations

from abc import abstractmethod

from flask import Flask, Blueprint

from opentakserver.plugins.BasePlugin import BasePlugin


class Plugin(BasePlugin):
    """
    Generic plugin
    """

    group = "opentakserver.plugin"
    blueprint: Blueprint | None = None

    @abstractmethod
    def activate(self, app: Flask) -> None: ...
