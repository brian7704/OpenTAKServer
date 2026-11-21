import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import fromstring

import sqlalchemy.exc
from flask import Flask
from flask_security.models import fsqla_v3 as fsqla

from opentakserver.extensions import db

try:
    fsqla.FsModels.set_db_info(db)
except sqlalchemy.exc.InvalidRequestError:
    pass

import opentakserver.app  # noqa: E402, F401
from opentakserver.blueprints.marti_api.video_marti_api import video_marti_api  # noqa: E402
from opentakserver.blueprints.ots_api.mediamtx_api import mediamtx_api_blueprint  # noqa: E402
from opentakserver.models.Group import Group  # noqa: E402
from opentakserver.models.role import Role  # noqa: E402, F401
from opentakserver.models.user import User  # noqa: E402, F401
from opentakserver.models.VideoStream import (  # noqa: E402
    VideoStream,
    get_user_group_names,
    get_video_owner,
    user_can_access_video_stream,
)


def _make_user(user_id: int, username: str, is_admin: bool = False, active: bool = True):
    return SimpleNamespace(
        id=user_id,
        username=username,
        password=f"hashed-{username}",
        active=active,
        fs_uniquifier=f"uid-{username}",
        has_role=lambda role: is_admin and role == "administrator",
    )


def _make_membership(group_name: str):
    return SimpleNamespace(group=SimpleNamespace(name=group_name))


def _make_test_app(users_by_username: dict, memberships: dict, ldap_enabled: bool = False):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["OTS_ENABLE_LDAP"] = ldap_enabled
    app.config["OTS_LDAP_GROUP_PREFIX"] = "ots_"
    app.config["OTS_IP_WHITELIST"] = ["127.0.0.1"]
    app.config["OTS_MEDIAMTX_TOKEN"] = "secret-mtx-token"
    app.config["OTS_MEDIAMTX_API_ADDRESS"] = "http://127.0.0.1:9997"
    app.config["OTS_SSL_CERT_HEADER"] = "X-Ssl-Cert"

    users_by_uid = {u.fs_uniquifier: u for u in users_by_username.values()}

    datastore = MagicMock()
    datastore.find_user.side_effect = lambda username=None, fs_uniquifier=None: (
        users_by_username.get(username) if username else users_by_uid.get(fs_uniquifier)
    )
    app.security = SimpleNamespace(datastore=datastore)

    app.register_blueprint(mediamtx_api_blueprint)
    app.register_blueprint(video_marti_api)

    app._test_memberships = memberships
    return app


def test_group_isolation_between_blufor_opfor_and_cadre():
    blufor = _make_user(1, "kevblufor")
    opfor = _make_user(2, "kevopfor")
    cadre = _make_user(3, "kevcadre")
    admin = _make_user(4, "admin", is_admin=True)
    anon = _make_user(5, "anonuser")

    users = {u.username: u for u in (blufor, opfor, cadre, admin, anon)}
    memberships = {
        (1, Group.IN): ["blufor"],
        (1, Group.OUT): ["blufor"],
        (2, Group.IN): ["opfor"],
        (2, Group.OUT): ["opfor"],
        (3, Group.IN): ["1S"],
        (3, Group.OUT): ["1S", "blufor", "opfor"],
    }
    app = _make_test_app(users, memberships)

    blufor_stream = SimpleNamespace(user=blufor, username="kevblufor", cot=None)
    opfor_stream = SimpleNamespace(user=opfor, username="kevopfor", cot=None)
    cadre_stream = SimpleNamespace(user=cadre, username="kevcadre", cot=None)
    anon_stream = SimpleNamespace(user=None, username=None, cot=None)

    def _fake_group_lookup(user, direction):
        if not user:
            return {"__ANON__"}
        groups = set(memberships.get((user.id, direction), []))
        return groups or {"__ANON__"}

    with app.app_context(), patch(
        "opentakserver.models.VideoStream.get_user_group_names", side_effect=_fake_group_lookup
    ):
        # Cross-group denied
        assert user_can_access_video_stream(opfor, blufor_stream) is False
        assert user_can_access_video_stream(blufor, opfor_stream) is False

        # Same-group and owner allowed
        assert user_can_access_video_stream(blufor, blufor_stream) is True
        assert user_can_access_video_stream(opfor, opfor_stream) is True

        # Cadre has OUT on both blufor and opfor, but blufor/opfor do not have 1S.OUT
        assert user_can_access_video_stream(cadre, blufor_stream) is True
        assert user_can_access_video_stream(cadre, opfor_stream) is True
        assert user_can_access_video_stream(blufor, cadre_stream) is False
        assert user_can_access_video_stream(opfor, cadre_stream) is False

        # Admin sees everything
        assert user_can_access_video_stream(admin, blufor_stream) is True
        assert user_can_access_video_stream(admin, cadre_stream) is True

        # Ungrouped (__ANON__) isolation
        assert user_can_access_video_stream(anon, anon_stream) is True
        assert user_can_access_video_stream(opfor, anon_stream) is False
        assert user_can_access_video_stream(anon, blufor_stream) is False


def test_get_video_owner_falls_back_to_cot_eud_user():
    blufor = _make_user(1, "kevblufor")
    app = _make_test_app({"kevblufor": blufor}, {})

    cot_backed_stream = SimpleNamespace(
        user=None,
        username=None,
        cot=SimpleNamespace(eud=SimpleNamespace(user=blufor)),
    )
    with app.app_context():
        assert get_video_owner(cot_backed_stream) == blufor


def test_get_user_group_names_supports_db_and_ldap():
    blufor = _make_user(1, "kevblufor")
    app = _make_test_app({"kevblufor": blufor}, {}, ldap_enabled=False)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_make_membership("blufor")]

    with app.app_context(), patch("opentakserver.models.VideoStream.db") as mock_db:
        mock_db.session.execute.return_value = mock_result
        assert get_user_group_names(blufor, Group.IN) == {"blufor"}

    ldap_app = _make_test_app({"kevblufor": blufor}, {}, ldap_enabled=True)
    with ldap_app.app_context(), patch("opentakserver.models.VideoStream.ldap_manager") as mock_ldap:
        mock_ldap.get_user_groups.return_value = [
            {"cn": "ots_blufor_write"},
            {"cn": "ots_opfor_read"},
            {"cn": "unrelated_blufor_write"},
        ]
        assert get_user_group_names(blufor, Group.IN) == {"ots_blufor"}
        assert get_user_group_names(blufor, Group.OUT) == {"ots_opfor"}


def test_external_auth_enforces_groups_on_rtsp_and_hls_and_preserves_local_whitelist():
    blufor = _make_user(1, "kevblufor")
    opfor = _make_user(2, "kevopfor")
    cadre = _make_user(3, "kevcadre")
    users = {u.username: u for u in (blufor, opfor, cadre)}
    memberships = {
        (1, Group.IN): ["blufor"],
        (1, Group.OUT): ["blufor"],
        (2, Group.IN): ["opfor"],
        (2, Group.OUT): ["opfor"],
        (3, Group.IN): ["1S"],
        (3, Group.OUT): ["1S", "blufor", "opfor"],
    }
    app = _make_test_app(users, memberships)
    client = app.test_client()

    blufor_stream = SimpleNamespace(
        path="live/uas-1",
        user=blufor,
        username="kevblufor",
        cot=None,
        ready=True,
    )

    def _fake_group_lookup(user, direction):
        if not user:
            return {"__ANON__"}
        return set(memberships.get((user.id, direction), [])) or {"__ANON__"}

    mock_query = MagicMock()
    mock_query.filter.return_value.first.return_value = blufor_stream

    with (
        patch(
            "opentakserver.models.VideoStream.get_user_group_names", side_effect=_fake_group_lookup
        ),
        patch("opentakserver.blueprints.ots_api.mediamtx_api.db") as mock_db,
        patch(
            "opentakserver.blueprints.ots_api.mediamtx_api.verify_password",
            side_effect=lambda pw, hashed: pw == "pass",
        ),
        patch(
            "opentakserver.blueprints.ots_api.mediamtx_api.parse_auth_token",
            side_effect=lambda tok: {"uid": f"uid-{tok}"},
        ),
    ):
        mock_db.session.query.return_value = mock_query

        # Cross-group RTSP read -> 401
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "192.168.50.20",
                "user": "kevopfor",
                "password": "pass",
                "path": "live/uas-1",
                "protocol": "rtsp",
                "action": "read",
                "query": "",
            },
        )
        assert res.status_code == 401

        # Same-group RTSP read -> 200
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "192.168.50.21",
                "user": "kevblufor",
                "password": "pass",
                "path": "live/uas-1",
                "protocol": "rtsp",
                "action": "read",
                "query": "",
            },
        )
        assert res.status_code == 200

        # Cadre RTSP read -> 200
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "192.168.50.22",
                "user": "kevcadre",
                "password": "pass",
                "path": "live/uas-1",
                "protocol": "rtsp",
                "action": "read",
                "query": "",
            },
        )
        assert res.status_code == 200

        # Proxied HLS from 127.0.0.1 must NOT bypass auth via IP whitelist
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "127.0.0.1",
                "user": "",
                "password": "",
                "path": "live/uas-1",
                "protocol": "hls",
                "action": "read",
                "query": "jwt=kevopfor",
            },
        )
        assert res.status_code == 401

        res = client.post(
            "/api/external_auth",
            json={
                "ip": "127.0.0.1",
                "user": "",
                "password": "",
                "path": "live/uas-1",
                "protocol": "hls",
                "action": "read",
                "query": "jwt=kevcadre",
            },
        )
        assert res.status_code == 200

        # Local ffmpeg restreaming over RTSP from 127.0.0.1 without credentials stays whitelisted
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "127.0.0.1",
                "user": "",
                "password": "",
                "path": "live/youtube",
                "protocol": "rtsp",
                "action": "publish",
                "query": "",
            },
        )
        assert res.status_code == 200

        # Internal MediaMTX webhook thumbnail token -> 200
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "192.168.50.134",
                "user": "",
                "password": "",
                "path": "live/uas-1",
                "protocol": "rtsp",
                "action": "read",
                "query": "token=secret-mtx-token",
            },
        )
        assert res.status_code == 200


def test_external_auth_publish_updates_owner_when_inactive_and_blocks_hijack_when_active():
    blufor = _make_user(1, "kevblufor")
    opfor = _make_user(2, "kevopfor")
    users = {"kevblufor": blufor, "kevopfor": opfor}
    memberships = {
        (1, Group.IN): ["blufor"],
        (1, Group.OUT): ["blufor"],
        (2, Group.IN): ["opfor"],
        (2, Group.OUT): ["opfor"],
    }
    app = _make_test_app(users, memberships)
    client = app.test_client()

    existing_stream = VideoStream()
    existing_stream.path = "live/uas-1"
    existing_stream.username = "kevopfor"
    existing_stream.ready = False
    existing_stream.mediamtx_settings = "{}"

    def _fake_group_lookup(user, direction):
        if not user:
            return {"__ANON__"}
        return set(memberships.get((user.id, direction), [])) or {"__ANON__"}

    mock_query = MagicMock()
    mock_query.filter.return_value.first.return_value = existing_stream

    with (
        patch(
            "opentakserver.models.VideoStream.get_user_group_names", side_effect=_fake_group_lookup
        ),
        patch("opentakserver.blueprints.ots_api.mediamtx_api.db") as mock_db,
        patch(
            "opentakserver.blueprints.ots_api.mediamtx_api.verify_password",
            return_value=True,
        ),
        patch("opentakserver.blueprints.ots_api.mediamtx_api.requests.post") as mock_post,
    ):
        mock_post.return_value = SimpleNamespace(status_code=200, text="")
        mock_db.session.commit.side_effect = [
            sqlalchemy.exc.IntegrityError("stmt", "params", Exception("dup")),
            None,
        ]
        mock_db.session.query.return_value = mock_query

        # Inactive stream path reused by kevblufor updates owner to kevblufor
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "192.168.50.21",
                "user": "kevblufor",
                "password": "pass",
                "path": "live/uas-1",
                "protocol": "rtsp",
                "action": "publish",
                "query": "",
            },
        )
        assert res.status_code == 200
        assert existing_stream.username == "kevblufor"

        # Now mark active under kevblufor; kevopfor attempting to hijack gets 401
        existing_stream.ready = True
        mock_db.session.commit.side_effect = [
            sqlalchemy.exc.IntegrityError("stmt", "params", Exception("dup")),
        ]
        res = client.post(
            "/api/external_auth",
            json={
                "ip": "192.168.50.20",
                "user": "kevopfor",
                "password": "pass",
                "path": "live/uas-1",
                "protocol": "rtsp",
                "action": "publish",
                "query": "",
            },
        )
        assert res.status_code == 401
        assert existing_stream.username == "kevblufor"


def test_marti_vcm_filters_feeds_by_group():
    blufor = _make_user(1, "kevblufor")
    opfor = _make_user(2, "kevopfor")
    cadre = _make_user(3, "kevcadre")
    users = {u.username: u for u in (blufor, opfor, cadre)}
    memberships = {
        (1, Group.IN): ["blufor"],
        (1, Group.OUT): ["blufor"],
        (2, Group.IN): ["opfor"],
        (2, Group.OUT): ["opfor"],
        (3, Group.IN): ["1S"],
        (3, Group.OUT): ["1S", "blufor", "opfor"],
    }
    app = _make_test_app(users, memberships)
    client = app.test_client()

    s_blu = VideoStream()
    s_blu.path = "live/blu-uas"
    s_blu.alias = "blu-uas"
    s_blu.uid = "uid-blu"
    s_blu.port = 8554
    s_blu.username = "kevblufor"
    s_blu.generate_xml("192.168.50.134")

    s_opf = VideoStream()
    s_opf.path = "live/opf-uas"
    s_opf.alias = "opf-uas"
    s_opf.uid = "uid-opf"
    s_opf.port = 8554
    s_opf.username = "kevopfor"
    s_opf.generate_xml("192.168.50.134")

    def _fake_group_lookup(user, direction):
        if not user:
            return {"__ANON__"}
        return set(memberships.get((user.id, direction), [])) or {"__ANON__"}

    video_marti_mod = importlib.import_module("opentakserver.blueprints.marti_api.video_marti_api")

    with (
        patch(
            "opentakserver.models.VideoStream.get_user_group_names", side_effect=_fake_group_lookup
        ),
        patch.object(video_marti_mod, "db") as mock_db,
    ):
        for req_user, expected_paths in [
            (opfor, ["live/opf-uas"]),
            (blufor, ["live/blu-uas"]),
            (cadre, ["live/blu-uas", "live/opf-uas"]),
        ]:
            mock_result = MagicMock()
            mock_result.scalars.return_value = [s_blu, s_opf]
            mock_db.session.execute.return_value = mock_result

            with patch.object(video_marti_mod, "_get_request_user", return_value=req_user):
                res = client.get("/Marti/vcm")
                assert res.status_code == 200
                xml_root = fromstring(res.data)
                paths = [f.find("path").text for f in xml_root.findall("feed")]
                assert paths == expected_paths
