import typing as t

import ldap3
from flask_security.datastore import Datastore, UserDatastore, UserMixin, RoleMixin, WebAuthnMixin
from opentakserver.extensions import logger
from ldap3 import Connection, Server


class LDAPDatastore(Datastore):
    def commit(self):
        logger.info(f"commit")

    def put(self, model):
        logger.info(f"put: {model}")

    def delete(self, model):
        logger.info(f"delete: {model}")


class LDAPUserDatastore(LDAPDatastore, UserDatastore):
    def __init__(self, user_model: t.Type[UserMixin], role_model: t.Type[RoleMixin], webauthn_model: t.Type[WebAuthnMixin], db):
        LDAPDatastore.__init__(self, db)
        UserDatastore.__init__(self, user_model, role_model, webauthn_model)

    def find_user(self, case_insensitive=False, **kwargs: t.Any) -> UserMixin:
        pass

    def find_role(self, role: str) -> RoleMixin | None:
        pass

    def find_webauthn(self, credential_id: bytes) -> WebAuthnMixin | None:
        pass

    def create_webauthn(
        self,
        user: UserMixin,
        credential_id: bytes,
        public_key: bytes,
        name: str,
        sign_count: int,
        usage: str,
        device_type: str,
        backup_state: bool,
        transports: list[str] | None = None,
        extensions: str | None = None,
        **kwargs: t.Any,
    ) -> None:
        pass
