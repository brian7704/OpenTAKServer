import hashlib

import jwt
import datetime
import os
from dataclasses import dataclass

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db, logger
from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flask import current_app as app


@dataclass
class Token(db.Model):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), ForeignKey("user.username"), nullable=True, unique=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    creation: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.datetime.now(datetime.timezone.utc))
    not_before: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    expiration: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    user = relationship("User", back_populates="tokens")

    def to_json(self) -> dict:
        json_token = {
            "username": self.username,
            "iad": iso8601_string_from_datetime(self.creation),
            "iss": "OpenTAKServer",
            "aud": "OpenTAKServer"
        }

        if self.max_uses:
            json_token["max"] = self.max_uses

        if self.not_before:
            json_token["nbf"] = iso8601_string_from_datetime(self.not_before)

        if self.expiration:
            json_token["exp"] = iso8601_string_from_datetime(self.expiration)

        return json_token

    def hash_token(self, token: str = None) -> str:
        sha256 = hashlib.sha256()

        if token:
            sha256.update(token.encode())
            token_hash = sha256.hexdigest()
        else:
            sha256.update(self.generate_token().encode())
            token_hash = sha256.hexdigest()
            self.token_hash = token_hash

        return token_hash

    def generate_token(self) -> str or None:
        if not self.username:
            return None

        token = {
            "iat": iso8601_string_from_datetime(self.creation),
            "sub": self.username
        }

        if self.not_before:
            token["nbf"] = iso8601_string_from_datetime(self.not_before)

        if self.expiration:
            token["exp"] = iso8601_string_from_datetime(self.expiration)

        if self.max_uses:
            token["max"] = self.max_uses

        with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.nopass.key"), "rb") as key:
            return jwt.encode(token, key.read(), algorithm="RS256")

    def verify_token(self, token: str) -> bool:
        with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.pub"), "r") as key:
            try:
                token_hash = self.hash_token(token)

                token_from_db = db.session.query(Token).filter_by(token_hash=token_hash).first()
                if not token_from_db:
                    return False

                token_from_db: Token = token_from_db[0]

                if token_from_db.disabled:
                    return False

                # Will raise InvalidTokenError on bad signature, expired, or before the nbf date
                decoded_token: dict = jwt.decode(token, key.read(), algorithm=["RS256"])

                if "max_uses" in decoded_token.keys() and self.total_uses >= decoded_token["max_uses"]:
                    return False

                return True

            except jwt.exceptions.InvalidTokenError:
                logger.error("Invalid token")
                return False
            except BaseException as e:
                logger.error(f"Failed to decode token: {e}")
                return False