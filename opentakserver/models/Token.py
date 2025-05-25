import hashlib
import json
import time
import traceback

import jwt
import os
from dataclasses import dataclass

from opentakserver.extensions import db, logger
from sqlalchemy import String, ForeignKey, Integer, Boolean, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flask import current_app as app


@dataclass
class Token(db.Model):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(255), ForeignKey("user.username"), nullable=True, unique=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=None, nullable=True)
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    creation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=int(time.time()))
    not_before: Mapped[int] = mapped_column(BigInteger, nullable=True)
    expiration: Mapped[int] = mapped_column(BigInteger, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    user = relationship("User", back_populates="tokens")

    def to_json(self, hash=False) -> dict:
        json_token = {
            "sub": self.username,
            "iat": self.creation,
            "iss": "OpenTAKServer",
            "aud": "OpenTAKServer"
        }

        if self.max_uses or not hash:
            json_token["max"] = self.max_uses

        if self.not_before or not hash:
            json_token["nbf"] = self.not_before

        if self.expiration or not hash:
            json_token["exp"] = self.expiration

        return json_token

    def hash_token(self, token: str = None) -> str:
        sha256 = hashlib.sha256()

        if token:
            sha256.update(token.encode())
            token_hash = sha256.hexdigest()
        else:
            sha256.update(json.dumps(self.to_json(True)).encode())
            token_hash = sha256.hexdigest()
            self.token_hash = token_hash

        return token_hash

    def generate_token(self) -> str or None:
        if not self.username:
            return None

        token = {
            "sub": self.username,
            "iat": self.creation,
            "iss": "OpenTAKServer",
            "aud": "OpenTAKServer"
        }

        if self.max_uses:
            token["max"] = self.max_uses

        if self.not_before:
            token["nbf"] = self.not_before

        if self.expiration:
            token["exp"] = self.expiration

        with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.nopass.key"), "rb") as key:
            encoded_token = jwt.encode(token, key.read(), algorithm="RS256")
            return encoded_token

    @staticmethod
    def verify_token(token: str) -> bool:
        with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", "opentakserver", "opentakserver.pub"), "r") as key:
            try:
                # Will raise InvalidTokenError on bad signature, expired, or before the nbf date
                decoded_token: dict = jwt.decode(token, key.read(), algorithms=["RS256"], audience="OpenTAKServer")

                sha256 = hashlib.sha256()
                sha256.update(json.dumps(decoded_token).encode())
                token_hash = sha256.hexdigest()

                token_from_db = db.session.query(Token).filter_by(token_hash=token_hash).first()
                if not token_from_db:
                    logger.error(f"Token not in db: {token_hash}")
                    return False

                if token_from_db.disabled:
                    logger.error("Token disabled")
                    return False

                if "max" in decoded_token.keys() and token_from_db.total_uses >= decoded_token["max"]:
                    logger.error(f"Too many uses for token {token_hash}")
                    return False

                token_from_db.total_uses += 1
                db.session.add(token_from_db)
                db.session.commit()

                return True

            except jwt.exceptions.InvalidTokenError as e:
                logger.error(f"Invalid token: {e}")
                logger.debug(traceback.format_exc())
                return False
            except BaseException as e:
                logger.error(f"Failed to decode token: {e}")
                logger.debug(traceback.format_exc())
                return False
