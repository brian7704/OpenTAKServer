import json
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse
from xml.etree.ElementTree import Element, SubElement, tostring

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, TEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship
from flask import current_app as app, request


@dataclass
class VideoStream(db.Model):
    __tablename__ = 'video_streams'

    path: Mapped[str] = mapped_column(String(255), primary_key=True)
    protocol: Mapped[str] = mapped_column(String(255), default='rtsp')
    port: Mapped[int] = mapped_column(Integer, default=8554)
    network_timeout: Mapped[int] = mapped_column(Integer, default=10000)
    uid: Mapped[str] = mapped_column(String(255), nullable=True)
    buffer_time: Mapped[int] = mapped_column(Integer, nullable=True)
    rover_port: Mapped[int] = mapped_column(Integer, nullable=True)
    rtsp_reliable: Mapped[int] = mapped_column(Integer, nullable=True, default=1)
    ignore_embedded_klv: Mapped[bool] = mapped_column(Boolean, nullable=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=True)
    preferred_mac_address: Mapped[str] = mapped_column(String(255), nullable=True)
    preferred_interface_address: Mapped[str] = mapped_column(String(255), nullable=True)
    username: Mapped[str] = mapped_column(String(255), ForeignKey("user.username"), nullable=True)
    xml: Mapped[str] = mapped_column(TEXT, nullable=True)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    mediamtx_settings: Mapped[str] = mapped_column(TEXT, default="")
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

        with app.app_context():
            url = urlparse(request.url_root)
            protocol = url.scheme
            hostname = url.hostname
            port = url.port
            if not port and protocol == 'https':
                port = 443
            elif not port and protocol == 'http':
                port = 80

            return {
                'network_timeout': self.network_timeout,
                'uid': self.uid,
                'protocol': self.protocol,
                'path': self.path,
                'buffer_time': self.buffer_time,
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
                'rtsp_link': "rtsp://{}:{}/{}".format(hostname, self.port, self.path),
                'webrtc_link': "{}://{}:{}/webrtc/{}/".format(protocol, hostname, port, self.path),
                'hls_link': "{}://{}:{}/hls/{}/".format(protocol, hostname, port, self.path),
                'thumbnail': f"{protocol}://{hostname}:{port}/api/videos/thumbnail?path={self.path}"
            }

    def generate_xml(self, hostname):

        feed = Element('feed')
        # Force rtsp to ensure compatibility with ATAK
        SubElement(feed, 'protocol').text = 'rtsp'
        SubElement(feed, 'alias').text = self.alias if self.alias else self.path
        SubElement(feed, 'uid').text = str(self.uid) if self.uid else str(uuid.uuid4())
        SubElement(feed, 'address').text = hostname
        SubElement(feed, 'port').text = str(self.port) if self.port else "8554"
        SubElement(feed, 'roverPort').text = str(self.rover_port)
        SubElement(feed, 'ignoreEmbeddedKLV').text = self.ignore_embedded_klv
        SubElement(feed, 'preferredMacAddress').text = self.preferred_mac_address
        SubElement(feed, 'preferredInterfaceAddress').text = self.preferred_interface_address
        SubElement(feed, 'path').text = self.path if self.path else self.alias
        SubElement(feed, 'buffer').text = str(self.buffer_time) if self.buffer_time else ""
        SubElement(feed, 'timeout').text = str(self.network_timeout) if self.network_timeout else "10000"
        SubElement(feed, 'rtspReliable').text = str(self.rtsp_reliable) if self.rtsp_reliable else "1"

        self.xml = tostring(feed).decode('utf-8')
