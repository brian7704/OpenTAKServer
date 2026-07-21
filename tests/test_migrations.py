from contextlib import nullcontext
from importlib import import_module

import pytest


migration = import_module(
    "opentakserver.migrations.versions.6a7929c07690_altered_foreign_key_on_device_profiles"
)


class FakeInspector:
    def __init__(self, foreign_keys):
        self.foreign_keys = foreign_keys

    def get_foreign_keys(self, table_name):
        assert table_name == "device_profiles"
        return self.foreign_keys


class FakeBatchOperation:
    def __init__(self):
        self.dropped = []
        self.created = []

    def drop_constraint(self, name, type_):
        self.dropped.append((name, type_))

    def create_foreign_key(self, name, table, local_columns, remote_columns):
        self.created.append((name, table, local_columns, remote_columns))


def configure_migration(monkeypatch, foreign_keys):
    batch = FakeBatchOperation()
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.sa, "inspect", lambda _bind: FakeInspector(foreign_keys)
    )
    monkeypatch.setattr(
        migration.op,
        "batch_alter_table",
        lambda table_name, schema=None: nullcontext(batch),
    )
    return batch


@pytest.mark.parametrize("constraint_name", ["eud_uid", "device_profiles_eud_uid_fkey"])
def test_upgrade_drops_deployed_eud_uid_foreign_key(monkeypatch, constraint_name):
    batch = configure_migration(
        monkeypatch,
        [
            {
                "name": constraint_name,
                "constrained_columns": ["eud_uid"],
            }
        ],
    )

    migration.upgrade()

    assert batch.dropped == [(constraint_name, "foreignkey")]


def test_upgrade_is_safe_when_foreign_key_is_already_absent(monkeypatch):
    batch = configure_migration(monkeypatch, [])

    migration.upgrade()

    assert batch.dropped == []


def test_downgrade_restores_foreign_key_only_when_absent(monkeypatch):
    batch = configure_migration(monkeypatch, [])

    migration.downgrade()

    assert batch.created == [("eud_uid", "euds", ["eud_uid"], ["uid"])]
