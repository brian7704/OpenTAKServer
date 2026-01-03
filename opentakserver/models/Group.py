import datetime
import enum
import re
from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.models.GroupUser import GroupUser
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship


class GroupTypeEnum(str, enum.Enum):
    SYSTEM = "SYSTEM"
    LDAP = "LDAP"


class GroupDirectionEnum(str, enum.Enum):
    IN = "IN"  # Write
    OUT = "OUT"  # Read


@dataclass
class Group(db.Model):
    __tablename__ = "groups"

    IN = "IN"
    OUT = "OUT"
    SYSTEM = "SYSTEM"
    LDAP = "LDAP"

    def __init__(self):
        super().__init__()
        self.bitpos = self.get_next_bitpos()

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    distinguishedName: Mapped[str] = mapped_column(String(255), nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    type: Mapped[str] = mapped_column(String(255))
    bitpos: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String, nullable=True)
    users = relationship("User", secondary="groups_users", viewonly=True, back_populates="groups", cascade="all, delete")
    missions = relationship("Mission", secondary="groups_missions", viewonly=True, back_populates="groups", cascade="all, delete")

    def get_next_bitpos(self) -> int:
        # the __ANON__ group is always 2 so default to 3 here
        bitpos = 3
        max_bitpos = db.session.execute(db.session.query(Group).order_by(Group.bitpos.desc()).limit(1)).first()
        if max_bitpos:
            bitpos = max_bitpos[0].bitpos + 1

        return bitpos

    def set_bitpos(self, new_bitpos : int = None):
        if new_bitpos:
            self.bitpos = new_bitpos
        else:
            self.bitpos = self.get_next_bitpos()

    def serialize(self):
        return {
            'name': self.name,
            'distinguishedName': self.distinguishedName,
            'created': self.created,
            'type': self.type,
            'bitpos': self.bitpos,
            'description': self.description,
        }

    def to_json(self):
        return_value = self.serialize()
        return_value['id'] = self.id
        return_value['bitpos'] = "{0:b}".format(self.bitpos)
        return_value['users'] = [user.serialize() for user in self.users]
        return_value['missions'] = [mission.serialize() for mission in self.missions]
        return return_value

    def to_marti_json_in(self):
        # Remove the _READ and _WRITE suffixes when using LDAP for groups
        remove_read = re.compile(re.escape("_read"), re.IGNORECASE)
        remove_write = re.compile(re.escape("_write"), re.IGNORECASE)
        group_name = remove_read.sub("", self.name)
        group_name = remove_write.sub("", group_name)

        return {
            'name': group_name,
            'direction': Group.IN,
            'created': iso8601_string_from_datetime(self.created or datetime.datetime.now(tz=datetime.timezone.utc)).split("T")[0],
            'type': self.type,
            'bitpos': self.bitpos,
            'active': True,
            'description': self.description or "",
        }

    def to_marti_json_out(self):
        return_value = self.to_marti_json_in()
        return_value['direction'] = Group.OUT
        return return_value
