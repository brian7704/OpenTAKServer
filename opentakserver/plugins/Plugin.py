from __future__ import annotations

from abc import abstractmethod

import colorlog
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from poetry.plugins.base_plugin import BasePlugin


class Plugin(BasePlugin):
    """
    Generic plugin
    """

    group = "opentakserver.plugin"

    @abstractmethod
    def activate(self, app: Flask, logger: colorlog, db: SQLAlchemy) -> None: ...
