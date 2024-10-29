import pathlib
from dataclasses import dataclass
from urllib.parse import urlparse

from flask import request, current_app as app

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class VideoRecording(db.Model):
    __tablename__ = 'video_recordings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_path: Mapped[str] = mapped_column(String(255), unique=True)
    path: Mapped[str] = mapped_column(String(255), ForeignKey("video_streams.path"))
    in_progress: Mapped[bool] = mapped_column(Boolean)
    start_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    stop_time: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=True)
    height: Mapped[int] = mapped_column(Integer, nullable=True)
    video_codec: Mapped[str] = mapped_column(String(255), nullable=True)
    video_bitrate: Mapped[int] = mapped_column(Integer, nullable=True)
    audio_codec: Mapped[str] = mapped_column(String(255), nullable=True)
    audio_bitrate: Mapped[int] = mapped_column(Integer, nullable=True)
    audio_samplerate: Mapped[int] = mapped_column(Integer, nullable=True)
    audio_channels: Mapped[int] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=True)
    video_stream = relationship("VideoStream", back_populates="recordings")

    def serialize(self):
        return {
            'segment_path': self.segment_path,
            'path': self.path,
            'in_progress': self.in_progress
        }

    def to_json(self):
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
                'id': self.id,
                'segment_path': self.segment_path,
                'path': self.path,
                'in_progress': self.in_progress,
                'start_time': iso8601_string_from_datetime(self.start_time) if self.start_time else None,
                'stop_time': iso8601_string_from_datetime(self.stop_time) if self.stop_time else None,
                'duration': self.duration,
                'filename': pathlib.Path(self.segment_path).name,
                'width': self.width,
                'height': self.height,
                'video_codec': self.video_codec,
                'video_bitrate': self.video_bitrate,
                'audio_codec': self.audio_codec,
                'audio_bitrate': self.audio_bitrate,
                'audio_samplerate': self.audio_samplerate,
                'audio_channels': self.audio_channels,
                'file_size': self.file_size,
                'thumbnail': f"{protocol}://{hostname}:{port}/api/videos/thumbnail?path={self.path}&recording={pathlib.Path(self.segment_path).name}"
            }
