import json
import uuid
from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement, tostring

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.config import Config


@dataclass
class VideoStream(db.Model):
    __tablename__ = 'video_streams'

    path: Mapped[str] = mapped_column(String, primary_key=True)

    protocol: Mapped[str] = mapped_column(String, default='rtsp')
    address: Mapped[str] = mapped_column(String, default=Config.OTS_SERVER_ADDRESS)
    port: Mapped[int] = mapped_column(Integer, default=8554)
    network_timeout: Mapped[int] = mapped_column(Integer, default=10000)
    uid: Mapped[str] = mapped_column(String, nullable=True)
    buffer_time: Mapped[int] = mapped_column(Integer, nullable=True)
    rover_port: Mapped[int] = mapped_column(Integer, nullable=True)
    rtsp_reliable: Mapped[int] = mapped_column(Integer, nullable=True, default=1)
    ignore_embedded_klv: Mapped[bool] = mapped_column(Boolean, nullable=True)
    alias: Mapped[str] = mapped_column(String, nullable=True)
    preferred_mac_address: Mapped[str] = mapped_column(String, nullable=True)
    preferred_interface_address: Mapped[str] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, ForeignKey("user.username"), nullable=True)
    xml: Mapped[str] = mapped_column(String, nullable=True)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    mediamtx_settings: Mapped[str] = mapped_column(String, default="")
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
    cot = relationship("CoT", back_populates="video")
    user = relationship("User", back_populates="video_streams")
    recordings = relationship("VideoRecording", back_populates="video_stream")

    def serialize(self):
        return {
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
            'ready': self.ready,
        }

    def to_json(self):
        try:
            mediamtx_settings = json.loads(self.mediamtx_settings)
            source = mediamtx_settings['source']
            record = mediamtx_settings['record']
        except json.decoder.JSONDecodeError:
            source = ""
            record = False

        return {
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
            'ready': self.ready,
            'source': source,
            'record': record,
            'rtsp_link': "{}://{}:{}/{}".format(self.protocol, self.address, self.port, self.path),
            'webrtc_link': "https://{}:{}/webrtc/{}".format(self.address, Config.OTS_HTTPS_PORT, self.path),
            'hls_link': "https://{}:{}/hls/{}".format(self.address, Config.OTS_HTTPS_PORT, self.path),
        }

    def generate_xml(self):

        feed = Element('feed')
        SubElement(feed, 'protocol').text = self.protocol if self.protocol else 'rtsp'
        SubElement(feed, 'alias').text = self.alias if self.alias else self.path
        SubElement(feed, 'uid').text = self.uid if self.uid else str(uuid.uuid4())
        SubElement(feed, 'address').text = self.address
        SubElement(feed, 'port').text = str(self.port) if self.port else "8554"
        SubElement(feed, 'roverPort').text = str(self.rover_port)
        SubElement(feed, 'ignoreEmbeddedKLV').text = self.ignore_embedded_klv
        SubElement(feed, 'preferredMacAddress').text = self.preferred_mac_address
        SubElement(feed, 'preferredInterfaceAddress').text = self.preferred_interface_address
        SubElement(feed, 'path').text = self.path
        SubElement(feed, 'buffer').text = str(self.buffer_time) if self.buffer_time else ""
        SubElement(feed, 'timeout').text = str(self.network_timeout) if self.network_timeout else "10000"
        SubElement(feed, 'rtspReliable').text = str(self.rtsp_reliable) if self.rtsp_reliable else "1"

        self.xml = tostring(feed).decode('utf-8')
