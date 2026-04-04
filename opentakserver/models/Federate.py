from sqlalchemy import JSON, TEXT, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship


from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime

"""
    Note to self: either make fed_truststore.jks or save individual certs and associate them with federates
"""


class Federate(db.Model):
    __tablename__ = "federates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    shared_alerts: Mapped[bool] = mapped_column(Boolean)
    archive: Mapped[bool] = mapped_column(Boolean)
    federate_group_matching: Mapped[bool] = mapped_column(Boolean)
    automatic_group_matching: Mapped[bool] = mapped_column(Boolean)
    fallback_group_matching: Mapped[bool] = mapped_column(Boolean)
    # -1 is takserver's default for no limit
    max_hops: Mapped[int] = mapped_column(Integer, default=-1)
    # When enabled, group hop limiting will be used in place of max hops. Individual group hop limits can be configured on the 'edit groups' page
    use_group_hop_limiting: Mapped[bool] = mapped_column(Boolean)
    # takserver notes field says "Notes may contain upper and lower case letters, numbers, spaces and underscores up to 30 characters."
    notes: Mapped[str] = mapped_column(String(255))
    certificate_file: Mapped[str] = mapped_column(String(255))
