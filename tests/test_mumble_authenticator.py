from unittest.mock import MagicMock

import pytest

pytest.importorskip("Ice")

from opentakserver.mumble.mumble_authenticator import MumbleAuthenticator


def make_authenticator():
    auth = MumbleAuthenticator.__new__(MumbleAuthenticator)  # skip __init__/Ice setup
    auth.app = MagicMock()
    auth.logger = MagicMock()
    datastore = auth.app.security.datastore
    datastore.find_user.return_value = None  # -> returns -1 before touching password logic
    return auth, datastore


@pytest.mark.parametrize(
    "raw_username,expected_lookup",
    [
        ("ANVIL---47c4c853-4e52-4b97-9a0b-08a0f961b0fa", "ANVIL"),
        ("plainuser", "plainuser"),
    ],
)
def test_username_lookup_strips_atak_vx_uid_suffix(raw_username, expected_lookup):
    auth, datastore = make_authenticator()

    auth.authenticate(raw_username, "password", None, None, None)

    datastore.find_user.assert_called_once_with(username=expected_lookup)
