import re
from typing import Optional, Tuple

# Maps lowercase suffix codes (without leading underscore) to canonical OTS/TAK Team names.
TEAM_SUFFIX_MAP = {
    # Multi-character codes & explicit overrides
    "db": "Dark Blue",
    "darkblue": "Dark Blue",
    "dark_blue": "Dark Blue",
    "dg": "Dark Green",
    "darkgreen": "Dark Green",
    "dark_green": "Dark Green",
    "mr": "Maroon",
    "ma": "Maroon",
    "mn": "Maroon",
    "maroon": "Maroon",
    "br": "Brown",
    "bn": "Brown",
    "brown": "Brown",
    "gy": "Gray",
    "gr": "Gray",
    "gray": "Gray",
    "grey": "Gray",
    "mg": "Magenta",
    # Single-letter codes & full color names
    "r": "Red",
    "red": "Red",
    "b": "Blue",
    "blue": "Blue",
    "g": "Green",
    "green": "Green",
    "c": "Cyan",
    "cyan": "Cyan",
    "w": "White",
    "white": "White",
    "y": "Yellow",
    "yellow": "Yellow",
    "o": "Orange",
    "orange": "Orange",
    "m": "Magenta",
    "magenta": "Magenta",
    "p": "Purple",
    "purple": "Purple",
    "t": "Teal",
    "teal": "Teal",
}

_ATAK_ENUM_TEAM_MAP = {
    "Unspecifed_Color": "Cyan",
    "Dark_Blue": "Dark Blue",
    "Dark_Green": "Dark Green",
}

_ATAK_ENUM_ROLE_MAP = {
    "Unspecifed": "Team Member",
    "TeamMember": "Team Member",
    "TeamLead": "Team Lead",
    "ForwardObserver": "Forward Observer",
}

# Build regex alternatives ordered longest-first so 'dark_green'/'dg' match before 'g', etc.
_SORTED_CODES = sorted(TEAM_SUFFIX_MAP.keys(), key=len, reverse=True)
_CODE_PATTERN = "|".join(re.escape(code) for code in _SORTED_CODES)

# 1) Trailing suffix: e.g. "squad 1_r", "Tracker01_dg", "Alpha _db"
_TRAILING_RE = re.compile(rf"^(.*?)\s*_({_CODE_PATTERN})\s*$", re.IGNORECASE)

# 2) Mid-name token before trailing number: e.g. "tracker_r_01", "squad_b 2"
_MID_NUM_RE = re.compile(rf"^(.*?)\s*_({_CODE_PATTERN})(?=[_\-\s]+\d+\s*$)", re.IGNORECASE)


def normalize_atak_enum_team(enum_name: Optional[str], default_team: str = "Cyan") -> str:
    """Normalize protobuf atak_pb2.Team enum name (e.g. 'Dark_Blue') to OTS/TAK team name."""
    if not enum_name:
        return default_team
    return _ATAK_ENUM_TEAM_MAP.get(enum_name, enum_name.replace("_", " "))


def normalize_atak_enum_role(enum_name: Optional[str], default_role: str = "Team Member") -> str:
    """Normalize protobuf atak_pb2.MemberRole enum name (e.g. 'TeamMember') to OTS/TAK role."""
    if not enum_name:
        return default_role
    return _ATAK_ENUM_ROLE_MAP.get(enum_name, enum_name)


def parse_callsign_and_team(
    name: Optional[str], fallback_name: str = ""
) -> Tuple[str, Optional[str]]:
    """Parse a Meshtastic name for a team color suffix (e.g. _r, _b, _dg, _db).

    Returns:
        (cleaned_name, canonical_team_name_or_None)
    """
    if not name:
        return fallback_name, None

    raw = str(name).strip()
    if not raw:
        return fallback_name, None

    m = _TRAILING_RE.match(raw)
    if m:
        base = m.group(1).strip().rstrip("_").strip()
        code = m.group(2).lower()
        team = TEAM_SUFFIX_MAP[code]
        cleaned = base if base else (fallback_name or raw.lstrip("_"))
        return cleaned, team

    m_mid = _MID_NUM_RE.match(raw)
    if m_mid:
        prefix = m_mid.group(1).strip()
        code = m_mid.group(2).lower()
        rest = raw[m_mid.end() :]
        if prefix:
            cleaned = f"{prefix}{rest}".strip()
        else:
            cleaned = rest.lstrip("_- ").strip() or fallback_name or raw
        return cleaned, TEAM_SUFFIX_MAP[code]

    return raw, None


def resolve_meshtastic_identity(
    long_name: Optional[str],
    short_name: Optional[str],
    from_id: str,
    default_team: str = "Cyan",
    parse_suffix: bool = True,
) -> Tuple[str, str, str]:
    """Resolve (clean_long_name, clean_short_name, team_name) for a Meshtastic node."""
    fallback_short = str(from_id)[-4:] if from_id else "mesh"
    fallback_long = f"Meshtastic {fallback_short}"

    if not parse_suffix:
        raw_long = str(long_name).strip() if long_name else ""
        raw_short = str(short_name).strip() if short_name else ""
        return (
            raw_long if raw_long else fallback_long,
            raw_short if raw_short else fallback_short,
            default_team,
        )

    clean_long, team_from_long = parse_callsign_and_team(long_name, fallback_name=fallback_long)
    clean_short, team_from_short = parse_callsign_and_team(short_name, fallback_name=fallback_short)

    team = team_from_long or team_from_short or default_team
    if not clean_long:
        clean_long = fallback_long
    if not clean_short:
        clean_short = fallback_short

    return clean_long, clean_short, team
