import pytest

from opentakserver.controllers.meshtastic_team_filter import (
    normalize_atak_enum_role,
    normalize_atak_enum_team,
    parse_callsign_and_team,
    resolve_meshtastic_identity,
)


@pytest.mark.parametrize(
    "raw_name,expected_callsign,expected_team",
    [
        ("squad 1_r", "squad 1", "Red"),
        ("squad 2_b", "squad 2", "Blue"),
        ("squad 3_g", "squad 3", "Green"),
        ("squad 4_dg", "squad 4", "Dark Green"),
        ("squad 5_db", "squad 5", "Dark Blue"),
        ("squad 6_c", "squad 6", "Cyan"),
        ("squad 7_w", "squad 7", "White"),
        ("Alpha_y", "Alpha", "Yellow"),
        ("Bravo_o", "Bravo", "Orange"),
        ("Charlie_m", "Charlie", "Magenta"),
        ("Delta_mr", "Delta", "Maroon"),
        ("Echo_p", "Echo", "Purple"),
        ("Foxtrot_t", "Foxtrot", "Teal"),
        ("Golf_br", "Golf", "Brown"),
        ("Hotel_gy", "Hotel", "Gray"),
        ("Hotel_gr", "Hotel", "Gray"),
        ("Trainee 01 _DB ", "Trainee 01", "Dark Blue"),
        ("Tracker_dark_green", "Tracker", "Dark Green"),
        ("Squad_Bravo_r", "Squad_Bravo", "Red"),
        ("tracker_r_01", "tracker_01", "Red"),
        ("squad_dg 2", "squad 2", "Dark Green"),
    ],
)
def test_parse_callsign_and_team_matches_all_colors(raw_name, expected_callsign, expected_team):
    callsign, team = parse_callsign_and_team(raw_name, fallback_name="Meshtastic 1234")
    assert callsign == expected_callsign
    assert team == expected_team


@pytest.mark.parametrize(
    "raw_name",
    [
        "Squad_Bravo",
        "Meshtastic_b4c1",
        "Meshtastic 5ab8",
        "Kevin K Mesh Node",
        "PlainCallsign",
    ],
)
def test_parse_callsign_and_team_ignores_non_color_tokens(raw_name):
    callsign, team = parse_callsign_and_team(raw_name, fallback_name="Meshtastic 1234")
    assert callsign == raw_name
    assert team is None


def test_resolve_meshtastic_identity_respects_parse_suffix_flag():
    clean_long, clean_short, team = resolve_meshtastic_identity(
        "squad 1_r", "s1_r", "deadbeef", default_team="Cyan", parse_suffix=False
    )
    assert clean_long == "squad 1_r"
    assert clean_short == "s1_r"
    assert team == "Cyan"

    clean_long, clean_short, team = resolve_meshtastic_identity(
        "squad 1_r", "s1_r", "deadbeef", default_team="Cyan", parse_suffix=True
    )
    assert clean_long == "squad 1"
    assert clean_short == "s1"
    assert team == "Red"


def test_resolve_meshtastic_identity_short_name_fallback_and_empty_base():
    clean_long, clean_short, team = resolve_meshtastic_identity(
        "Trainee 1", "T1_b", "1234abcd", default_team="Cyan", parse_suffix=True
    )
    assert clean_long == "Trainee 1"
    assert clean_short == "T1"
    assert team == "Blue"

    clean_long, clean_short, team = resolve_meshtastic_identity(
        "_r", "", "1234abcd", default_team="Cyan", parse_suffix=True
    )
    assert clean_long == "Meshtastic abcd"
    assert clean_short == "abcd"
    assert team == "Red"


def test_normalize_atak_protobuf_enums():
    assert normalize_atak_enum_team("Dark_Blue") == "Dark Blue"
    assert normalize_atak_enum_team("Dark_Green") == "Dark Green"
    assert normalize_atak_enum_team("Unspecifed_Color") == "Cyan"
    assert normalize_atak_enum_team("Red") == "Red"

    assert normalize_atak_enum_role("TeamMember") == "Team Member"
    assert normalize_atak_enum_role("TeamLead") == "Team Lead"
    assert normalize_atak_enum_role("ForwardObserver") == "Forward Observer"
    assert normalize_atak_enum_role("Medic") == "Medic"
