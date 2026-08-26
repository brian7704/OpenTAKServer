import datetime
import logging
import types
import unittest
from unittest.mock import patch

from opentakserver.controllers import meshtastic_controller as module


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Session:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if isinstance(value, _CoT) and value.id is None:
                value.id = 17

    def commit(self):
        return None


class _SocketIO:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload, namespace=None):
        self.emitted.append((event, payload, namespace))


class _CoT:
    def __init__(self):
        self.id = None


class _Point:
    def __init__(self):
        self.cot_id = None
        self.cot = None

    def to_json(self):
        return {
            "uid": self.uid,
            "how": self.cot.how if self.cot else None,
            "type": self.cot.type if self.cot else None,
        }


class MeshtasticPositionIntegrityTest(unittest.TestCase):
    def test_position_persists_cot_link_and_refreshes_eud_activity(self):
        controller = object.__new__(module.MeshtasticController)
        controller.context = _Context()
        controller.logger = logging.getLogger(__name__)
        controller.meshtastic_devices = {
            "a1b2c3d4": {
                "hw_model": "HELTEC_V3",
                "long_name": "Mesh Alpha",
                "short_name": "Alpha",
                "macaddr": "AAECAwQF",
                "firmware_version": "2.7.6",
                "last_lat": "0.0",
                "last_lon": "0.0",
                "battery": 87,
                "meshtastic_id": "a1b2c3d4",
                "voltage": 0,
                "uptime": 0,
                "last_alt": "9999999.0",
                "course": "0.0",
                "speed": "0.0",
                "team": "Cyan",
                "role": "Team Member",
                "uid": None,
            }
        }

        eud_updates = []

        def record_eud_update(uid, from_id, update_if_exists=True, last_event_time=None):
            eud_updates.append((uid, from_id, update_if_exists, last_event_time))

        controller.insert_or_update_eud = record_eud_update
        protobuf = types.SimpleNamespace(
            latitude_i=389123456,
            longitude_i=-91234567,
            altitude=123,
            ground_track=45,
            ground_speed=6,
        )
        session = _Session()
        socketio = _SocketIO()

        with (
            patch.object(module, "db", types.SimpleNamespace(session=session)),
            patch.object(module, "socketio", socketio),
            patch.object(module, "CoT", _CoT, create=True),
            patch.object(module, "Point", _Point),
        ):
            event = controller.position(protobuf, "a1b2c3d4", "all", "POSITION_APP")

        self.assertIsNotNone(event)
        self.assertEqual(len(eud_updates), 1)
        self.assertIsInstance(eud_updates[0][3], datetime.datetime)
        self.assertEqual(eud_updates[0][3].tzinfo, datetime.timezone.utc)

        cot = next(value for value in session.added if isinstance(value, _CoT))
        point = next(value for value in session.added if isinstance(value, _Point))
        self.assertEqual(point.cot_id, cot.id)
        self.assertIs(point.cot, cot)
        self.assertEqual(point.uid, event.attrib["uid"])
        self.assertEqual(point.to_json()["type"], "a-f-G-U-C")
        self.assertEqual(point.to_json()["how"], "m-g")
        self.assertEqual(socketio.emitted[0][1]["type"], "a-f-G-U-C")


if __name__ == "__main__":
    unittest.main()
