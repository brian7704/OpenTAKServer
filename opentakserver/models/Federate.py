from sqlalchemy import JSON, TEXT, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import false_values
from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime

"""
    Note to self: either make fed_truststore.jks or save individual certs and associate them with federates
"""


class Federate(db.Model):
    __tablename__ = "federates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    shared_alerts: Mapped[bool] = mapped_column(Boolean, default=True, false_values=false_values)
    archive: Mapped[bool] = mapped_column(Boolean, default=False, false_values=false_values)
    federate_group_matching: Mapped[bool] = mapped_column(
        Boolean, default=True, false_values=false_values
    )
    automatic_group_matching: Mapped[bool] = mapped_column(
        Boolean, default=True, false_values=false_values
    )
    fallback_group_matching: Mapped[bool] = mapped_column(
        Boolean, default=False, false_values=false_values
    )
    # -1 is takserver's default for no limit
    max_hops: Mapped[int] = mapped_column(Integer, default=-1)
    # When enabled, group hop limiting will be used in place of max hops. Individual group hop limits can be configured on the 'edit groups' page
    use_group_hop_limiting: Mapped[bool] = mapped_column(
        Boolean, default=False, false_values=false_values
    )
    # takserver notes field says "Notes may contain upper and lower case letters, numbers, spaces and underscores up to 30 characters."
    notes: Mapped[str] = mapped_column(String(255), nullable=True)
    certificate_file: Mapped[str] = mapped_column(String(255))
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    serial_number: Mapped[str] = mapped_column(String(255), unique=True)
    federation_connections = relationship("FederationConnection", back_populates="federate")

    def from_wtf(self, form):
        self.name = form.name.data
        self.shared_alerts = form.shared_alerts.data
        self.federate_group_matching = form.federate_group_matching.data
        self.automatic_group_matching = form.automatic_group_matching.data
        self.max_hops = form.max_hops.data
        self.use_group_hop_limiting = form.use_group_hop_limiting.data
        self.notes = form.notes.data
        self.certificate_file = form.certificate_file.data
        self.issuer = form.issuer.data
        self.subject = form.subject.data
        self.serial_number = form.serial_number.data

    def serialize(self):
        return {
            "name": self.name,
            "shared_alerts": self.shared_alerts,
            "federate_group_matching": self.federate_group_matching,
            "automatic_group_matching": self.automatic_group_matching,
            "max_hops": self.max_hops,
            "use_group_hop_limiting": self.use_group_hop_limiting,
            "notes": self.notes,
            "certificate_file": self.certificate_file,
            "issuer": self.issuer,
            "subject": self.subject,
            "serial_number": self.serial_number,
        }

    def to_json(self):
        return self.serialize()
