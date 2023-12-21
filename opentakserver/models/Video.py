from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement, tostring

from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Video(db.Model):
    __tablename__ = 'video'

    protocol: Mapped[str] = mapped_column(String, primary_key=True, default='rtsp')
    address: Mapped[str] = mapped_column(String, primary_key=True)
    port: Mapped[int] = mapped_column(Integer, primary_key=True, default=8554)
    path: Mapped[str] = mapped_column(String, primary_key=True)

    network_timeout: Mapped[int] = mapped_column(Integer, default=12000)
    uid: Mapped[str] = mapped_column(String, nullable=True)
    buffer_time: Mapped[int] = mapped_column(Integer, default=5000)
    rover_port: Mapped[int] = mapped_column(Integer, nullable=True)
    rtsp_reliable: Mapped[int] = mapped_column(Integer, nullable=True)
    ignore_embedded_klv: Mapped[bool] = mapped_column(Boolean, nullable=True)
    alias: Mapped[str] = mapped_column(String, nullable=True)
    preferred_mac_address: Mapped[str] = mapped_column(String, nullable=True)
    preferred_interface_address: Mapped[str] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, ForeignKey("user.username"), nullable=True)
    xml: Mapped[str] = mapped_column(String, nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    cot = relationship("CoT", back_populates="video")
    user = relationship("User", back_populates="video_streams")

    def serialize(self):
        return {
            'video': {
                'network_timeout': self.network_timeout,
                'uid': self.uid,
                'protocol': self.protocol,
                'path': self.path,
                'buffer_time': self.buffer_time,
                'address': self.address,
                'port': self.port,
                'rover_port': self.rover_port,
                'rtsp_reliable': self.rtsp_reliable,
                'ignore_embedded_klv': self.ignore_embedded_klv,
                'alias': self.alias,
                'preferred_mac_address': self.preferred_mac_address,
                'preferred_interface_address': self.preferred_interface_address,
                'username': self.username,
                'link': "{}://{}:{}{}".format(self.protocol, self.address, self.port, self.path)
            }
        }

    def generate_xml(self):

        feed = Element('feed')
        SubElement(feed, 'protocol').text = self.protocol
        SubElement(feed, 'alias').text = self.alias
        SubElement(feed, 'uid').text = self.uid
        SubElement(feed, 'address').text = self.address
        SubElement(feed, 'port').text = str(self.port)
        SubElement(feed, 'roverPort').text = str(self.rover_port)
        SubElement(feed, 'ignoreEmbeddedKLV').text = self.ignore_embedded_klv
        SubElement(feed, 'preferredMacAddress').text = self.preferred_mac_address
        SubElement(feed, 'preferredInterfaceAddress').text = self.preferred_interface_address
        SubElement(feed, 'path').text = self.path
        SubElement(feed, 'buffer').text = str(self.buffer_time)
        SubElement(feed, 'timeout').text = str(self.network_timeout)
        SubElement(feed, 'rtspReliable').text = str(self.rtsp_reliable)

        self.xml = tostring(feed).decode('utf-8')
