from bs4 import BeautifulSoup
from androguard.core.apk import APK

from sqlalchemy import Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from opentakserver.extensions import db


class Plugins(db.Model):
    __tablename__ = "plugins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    distro: Mapped[str] = mapped_column(String(255), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    author: Mapped[str] = mapped_column(String(255), nullable=True, default=None)
    version: Mapped[str] = mapped_column(String(255), nullable=True, default=None)
