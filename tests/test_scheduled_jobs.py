from types import SimpleNamespace

from opentakserver.blueprints import scheduled_jobs


def test_purge_data_deletes_mission_invitations_before_missions(monkeypatch):
    deleted = []
    state = {"mission_invitations": 1}

    class Query:
        def __init__(self, model_name):
            self.model_name = model_name

        def delete(self):
            deleted.append(self.model_name)
            if self.model_name == "MissionInvitation":
                state["mission_invitations"] = 0
            if self.model_name == "Mission" and state["mission_invitations"]:
                raise AssertionError("mission_invitations still references missions")

    model_names = (
        "ZMIST",
        "VideoStream",
        "Alert",
        "CasEvac",
        "Certificate",
        "ChatroomsUids",
        "DataPackage",
        "Marker",
        "GeoChat",
        "Point",
        "RBLine",
        "Chatroom",
        "CoT",
        "MissionRole",
        "MissionContentMission",
        "MissionUID",
        "MissionChange",
        "MissionInvitation",
        "Mission",
        "EUD",
        "Team",
    )
    for model_name in model_names:
        monkeypatch.setattr(
            scheduled_jobs,
            model_name,
            SimpleNamespace(query=Query(model_name)),
        )

    monkeypatch.setattr(scheduled_jobs, "delete_video_recordings", lambda: None)
    monkeypatch.setattr(
        scheduled_jobs,
        "db",
        SimpleNamespace(session=SimpleNamespace(commit=lambda: None)),
    )
    monkeypatch.setattr(scheduled_jobs, "logger", SimpleNamespace(info=lambda _message: None))

    scheduled_jobs.purge_data()

    assert deleted.index("MissionInvitation") < deleted.index("Mission")
