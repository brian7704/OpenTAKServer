import hashlib
import os

import Ice
from cryptography import x509
from flask import Flask
from flask_ldap3_login import AuthenticationResponseStatus
from flask_security import verify_password

from ..extensions import ldap_manager

# Load up Murmur slice file into Ice
Ice.loadSlice(
    "",
    [
        "-I" + Ice.getSliceDir(),
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "Murmur.ice"),
    ],
)
import Murmur


# Each OTS user gets a 1000-id range in Mumble.  PC username auth uses the base
# id (user.id * 1000); ATAK callsign auth uses base + a deterministic offset
# derived from the callsign (so a single OTS account can connect from multiple
# devices simultaneously, as the official ATAK VX voice plugin does).
MUMBLE_ID_RANGE = 1000
MUMBLE_ID_CALLSIGN_OFFSET_RANGE = MUMBLE_ID_RANGE - 1


class MumbleAuthenticator(Murmur.ServerUpdatingAuthenticator):
    def __init__(self, app, logger, ice):
        Murmur.ServerUpdatingAuthenticator.__init__(self)
        self.app: Flask = app
        self.logger = logger
        self.ice = ice

    # ----- public lookup helpers (also used by mumble_ice_app) ---------------

    @staticmethod
    def resolve_identity(app, username, certlist=None):
        """Look up an OTS user from a Mumble username, ATAK callsign, or cert.

        Lookup chain (first match wins):
          1. OTS username (PC clients)
          2. EUD callsign exact match
          3. EUD callsign with `---<uuid>` suffix stripped (ATAK adds this)
          4. Above with `_` -> ` ` (ATAK Mumble plugin replaces spaces in callsigns)
          5. Cert CN -> EUD.uid (immutable; survives callsign renames)

        Does NOT verify password.  Returns (user_or_None, is_callsign_auth_bool).
        """
        from opentakserver.models.EUD import EUD

        user = app.security.datastore.find_user(username=username)
        if user:
            return user, False

        eud = EUD.query.filter_by(callsign=username).first()

        base_callsign = username
        if not eud and "---" in username:
            base_callsign = username.split("---")[0]
            eud = EUD.query.filter_by(callsign=base_callsign).first()

        if not eud:
            spaced = base_callsign.replace("_", " ")
            if spaced != base_callsign:
                eud = EUD.query.filter_by(callsign=spaced).first()

        if not eud and certlist:
            eud = MumbleAuthenticator._eud_from_cert(certlist)

        if eud and eud.user_id:
            user = app.security.datastore.find_user(id=eud.user_id)
            if user:
                return user, True
        return None, False

    @staticmethod
    def _eud_from_cert(certlist):
        """Look up an EUD by parsing the client cert chain's CN.

        ATAK device certs use the EUD UID (e.g. `ANDROID-xxxx`) as the cert CN,
        so this lookup survives mid-session callsign renames -- the OTS EUDs
        table only updates on the next CoT, but the Mumble plugin auths
        immediately with the new name.
        """
        from opentakserver.models.EUD import EUD

        for cert_bytes in certlist:
            try:
                cert = x509.load_der_x509_certificate(cert_bytes)
                cns = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
                if not cns:
                    continue
                eud = EUD.query.filter_by(uid=cns[0].value).first()
                if eud:
                    return eud
            except Exception:
                continue
        return None

    @staticmethod
    def mumble_identity(user, is_callsign_auth, presented_username):
        """Return (mumble_user_id, display_name) for an authenticated user.

        PC username auth   -> (user.id * 1000, user.username)
        ATAK callsign auth -> (user.id * 1000 + hash(callsign) % 999 + 1, callsign)

        The hash offset lets one OTS account connect from multiple ATAK devices
        simultaneously, each with a unique Mumble user id (the VX plugin even
        opens two sockets per device, each with a different `---<uuid>` suffix).
        """
        if is_callsign_auth:
            digest = int(hashlib.md5(presented_username.encode()).hexdigest(), 16)
            offset = digest % MUMBLE_ID_CALLSIGN_OFFSET_RANGE + 1
            return user.id * MUMBLE_ID_RANGE + offset, presented_username
        return user.id * MUMBLE_ID_RANGE, user.username

    # ----- Murmur Ice callbacks ---------------------------------------------

    def authenticate(self, username, password, certlist, certhash, strong, current=None):
        """Authenticate a Mumble client.

        Returns (mumble_id, display_name, group_list) on success or
        (-1, None, None) on failure.  Returning -2 tells Murmur to use its
        own auth fallback (used only for SuperUser).
        """
        if username == "SuperUser":
            return -2, None, None

        self.logger.info("Mumble auth request for {}".format(username))

        with self.app.app_context():
            user, is_callsign_auth = self.resolve_identity(self.app, username, certlist)

            if not user:
                self.logger.warning("Mumble auth: user {} not found".format(username))
                return -1, None, None
            if not user.active:
                self.logger.warning("Mumble auth: user {} is deactivated".format(username))
                return -1, None, None

            mumble_groups = [g.name for g in user.groups]
            if any(r.name == "administrator" for r in user.roles):
                mumble_groups.append("admin")

            authenticated = False

            if self.app.config.get("OTS_ENABLE_LDAP"):
                auth_result = ldap_manager.authenticate(username, password)
                if auth_result.status == AuthenticationResponseStatus.success:
                    # Keep this import inline to avoid a circular import at startup.
                    from opentakserver.blueprints.ots_api.ldap_api import save_user

                    save_user(
                        auth_result.user_dn,
                        auth_result.user_id,
                        auth_result.user_info,
                        auth_result.user_groups,
                    )
                    authenticated = True
            elif is_callsign_auth:
                # ATAK clients authenticate by client cert, not password.
                # The cert was already validated by Murmur's TLS layer before
                # this callback was invoked; we only need to verify that the
                # presented identity (callsign or cert CN) maps to an EUD.
                authenticated = True
            elif verify_password(password, user.password):
                authenticated = True

            if not authenticated:
                self.logger.warning("Mumble auth: bad password for {}".format(username))
                return -1, None, None

            mumble_id, display_name = self.mumble_identity(user, is_callsign_auth, username)
            self.logger.info(
                "Mumble auth: id={} display={} groups={}".format(
                    mumble_id, display_name, mumble_groups
                )
            )
            return mumble_id, display_name, mumble_groups

    def getInfo(self, id, current=None):
        """Return user info to Murmur so it stays authoritative for Ice-authed users.

        Murmur 1.3 will otherwise look up cert/password against its local
        ``user_info`` table, which is empty for Ice-authed users.  That causes
        a "Wrong certificate or password for existing user" rejection on every
        reconnect -- before Ice authenticate() is even called.
        """
        if id is None or id <= 0:
            return False, None
        try:
            with self.app.app_context():
                from opentakserver.extensions import db
                from opentakserver.models.user import User

                user = db.session.get(User, id // MUMBLE_ID_RANGE)
                if not user:
                    return False, None
                info = {Murmur.UserInfo.UserName: user.username}
                if user.email:
                    info[Murmur.UserInfo.UserEmail] = user.email
                return True, info
        except Exception as e:
            self.logger.error("Mumble getInfo({}) failed: {}".format(id, e))
            return False, None

    def nameToId(self, name, current=None):
        """Tell Murmur the Mumble id that owns a given name.

        Returning -2 (fall through) makes Murmur consult its local users table,
        which causes the rename/reconnect rejection bug; returning the encoded
        id keeps Ice authoritative.
        """
        if not name or name == "SuperUser":
            return -2
        try:
            with self.app.app_context():
                user, is_callsign_auth = self.resolve_identity(self.app, name)
                if not user:
                    return -2
                mumble_id, _ = self.mumble_identity(user, is_callsign_auth, name)
                return mumble_id
        except Exception as e:
            self.logger.error("Mumble nameToId({}) failed: {}".format(name, e))
            return -2

    def idToName(self, id, current=None):
        """Return display name for a Mumble id.  Used for ACL/log lookups."""
        if id is None or id <= 0:
            return ""
        try:
            with self.app.app_context():
                from opentakserver.extensions import db
                from opentakserver.models.user import User

                user = db.session.get(User, id // MUMBLE_ID_RANGE)
                return user.username if user else ""
        except Exception as e:
            self.logger.error("Mumble idToName({}) failed: {}".format(id, e))
            return ""

    def idToTexture(self, id, current=None):
        return b""

    def registerUser(self, info, current=None):
        return -2

    def unregisterUser(self, id, current=None):
        return -1

    def getRegisteredUsers(self, filter, current=None):
        return {}

    def setInfo(self, id, info, current=None):
        return 0

    def setTexture(self, id, texture, current=None):
        return -1
