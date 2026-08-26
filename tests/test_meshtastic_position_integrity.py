import datetime
import types
import unittest
from unittest.mock import MagicMock, patch

from opentakserver.controllers import meshtastic_controller as module


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Query:
    def __init__(self):
        self.filters = {}

    def filter_by(self, **filters):
        self.filters = filters
        return self


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _Session:
    def __init__(self, commit_error=None, euds_by_uid=None, euds_by_meshtastic_id=None):
        self.added = []
        self.commit_error = commit_error
        self.rolled_back = False
        self.euds_by_uid = euds_by_uid or {}
        self.euds_by_meshtastic_id = euds_by_meshtastic_id or {}

    def query(self, model):
        return _Query()

    def execute(self, query):
        if "uid" in query.filters:
            return _Result(self.euds_by_uid.get(query.filters["uid"]))
        return _Result(self.euds_by_meshtastic_id.get(query.filters.get("meshtastic_id")))

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if isinstance(value, _CoT) and value.id is None:
                value.id = 17

    def commit(self):
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rolled_back = True


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
    def make_controller(self, mapped_uid=None):
        controller = object.__new__(module.MeshtasticController)
        controller.context = _Context()
        controller.logger = MagicMock()
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
                "uid": mapped_uid,
            }
        }
        return controller

    def protobuf(self):
        return types.SimpleNamespace(
            latitude_i=389123456,
            longitude_i=-91234567,
            altitude=123,
            ground_track=45,
            ground_speed=6,
        )

    def test_position_uses_one_canonical_uid_with_and_without_mapping(self):
        raw_uid = "a1b2c3d4"
        mapped_uid = "ATAK-MAPPED-UID"
        raw_eud = types.SimpleNamespace(uid=raw_uid)
        mapped_eud = types.SimpleNamespace(uid=mapped_uid)
        scenarios = (
            ("raw", None, {}, {}, raw_uid),
            ("mapped-existing", mapped_uid, {mapped_uid: mapped_eud}, {}, mapped_uid),
            (
                "raw-existing",
                mapped_uid,
                {},
                {int(raw_uid, 16): raw_eud},
                raw_uid,
            ),
            ("mapped-new", mapped_uid, {}, {}, mapped_uid),
        )
        for name, memory_uid, by_uid, by_mesh_id, canonical_uid in scenarios:
            with self.subTest(name=name):
                controller = self.make_controller(memory_uid)
                eud_updates = []

                def record_eud_update(uid, from_id, update_if_exists=True, last_event_time=None):
                    eud_updates.append((uid, from_id, update_if_exists, last_event_time))

                controller.insert_or_update_eud = record_eud_update
                session = _Session(
                    euds_by_uid=by_uid,
                    euds_by_meshtastic_id=by_mesh_id,
                )
                socketio = _SocketIO()

                with (
                    patch.object(module, "db", types.SimpleNamespace(session=session)),
                    patch.object(module, "socketio", socketio),
                    patch.object(module, "CoT", _CoT, create=True),
                    patch.object(module, "Point", _Point),
                ):
                    event = controller.position(self.protobuf(), raw_uid, "all", "POSITION_APP")

                self.assertEqual(event.attrib["uid"], canonical_uid)
                self.assertEqual(eud_updates[0][:3], (canonical_uid, raw_uid, False))
                self.assertIsInstance(eud_updates[0][3], datetime.datetime)
                self.assertEqual(eud_updates[0][3].tzinfo, datetime.timezone.utc)

                cot = next(value for value in session.added if isinstance(value, _CoT))
                point = next(value for value in session.added if isinstance(value, _Point))
                self.assertEqual(cot.sender_uid, canonical_uid)
                self.assertEqual(point.device_uid, canonical_uid)
                self.assertEqual(point.uid, canonical_uid)
                self.assertEqual(point.cot_id, cot.id)
                self.assertIs(point.cot, cot)
                self.assertEqual(point.to_json()["type"], "a-f-G-U-C")
                self.assertEqual(point.to_json()["how"], "m-g")
                self.assertEqual(socketio.emitted[0][1]["type"], "a-f-G-U-C")

    def test_position_rolls_back_failed_cot_point_transaction(self):
        controller = self.make_controller("ATAK-MAPPED-UID")
        controller.insert_or_update_eud = lambda *args, **kwargs: None
        session = _Session(commit_error=RuntimeError("database write failed"))
        socketio = _SocketIO()

        with (
            patch.object(module, "db", types.SimpleNamespace(session=session)),
            patch.object(module, "socketio", socketio),
            patch.object(module, "CoT", _CoT, create=True),
            patch.object(module, "Point", _Point),
        ):
            event = controller.position(self.protobuf(), "a1b2c3d4", "all", "POSITION_APP")

        self.assertIsNone(event)
        self.assertTrue(session.rolled_back)
        self.assertEqual(socketio.emitted, [])

    def test_existing_eud_conflict_updates_only_activity_after_rollback(self):
        controller = self.make_controller("ATAK-MAPPED-UID")
        event_time = datetime.datetime(2026, 8, 26, 14, 0, tzinfo=datetime.timezone.utc)
        eud = MagicMock()
        eud.to_json.return_value = {}
        eud_type = MagicMock(return_value=eud)
        eud_type.uid = MagicMock()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = None
        session.commit.side_effect = [
            module.sqlalchemy.exc.IntegrityError(
                "duplicate EUD", params=None, orig=RuntimeError("duplicate")
            ),
            None,
        ]
        update = MagicMock()

        with (
            patch.object(module, "db", types.SimpleNamespace(session=session)),
            patch.object(module, "socketio", MagicMock()),
            patch.object(module, "EUD", eud_type),
            patch.object(module, "Team", MagicMock()),
            patch.object(module.sqlalchemy, "update", return_value=update),
        ):
            controller.insert_or_update_eud(
                "ATAK-MAPPED-UID",
                "a1b2c3d4",
                update_if_exists=False,
                last_event_time=event_time,
            )

        session.rollback.assert_called_once_with()
        self.assertEqual(session.commit.call_count, 2)
        update.where.return_value.values.assert_called_once_with(
            last_event_time=event_time,
            last_status="Connected",
        )


if __name__ == "__main__":
    unittest.main()
