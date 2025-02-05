from __future__ import annotations

from abc import abstractmethod

from flask import Flask
from poetry.plugins.base_plugin import BasePlugin


class Plugin(BasePlugin):
    """
    Generic plugin not related to the console application.
    """

    group = "opentakserver.plugin"

    @abstractmethod
    def activate(self, app: Flask) -> None: ...
