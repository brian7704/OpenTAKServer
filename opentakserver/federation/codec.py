"""Federation v1 frame codec.

TAK Server federation v1 streams protobuf ``FederatedEvent`` messages over a
mutually-authenticated TLS socket. Each frame is a 4-byte big-endian unsigned
length followed by the serialized message. There is no handshake or
negotiation; peers simply start streaming frames after the TLS handshake.
Reference implementation: TAK Server's NioNettyFederationServerHandler.
"""

import struct

from opentakserver.federation.proto import fig_pb2

LENGTH_PREFIX = struct.Struct(">I")

# TAK Server does not bound frame size, but an unbounded length prefix from a
# misbehaving peer would let it allocate arbitrary memory. SA events are tiny;
# even image-bearing events stay far below this.
DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024


class FrameTooLargeError(Exception):
    def __init__(self, size: int, limit: int):
        super().__init__(f"federation frame of {size} bytes exceeds limit of {limit}")
        self.size = size
        self.limit = limit


def encode_frame(event: fig_pb2.FederatedEvent) -> bytes:
    payload = event.SerializeToString()
    return LENGTH_PREFIX.pack(len(payload)) + payload


class FrameDecoder:
    """Incremental decoder for a stream of length-prefixed FederatedEvents.

    Feed arbitrary chunks from the socket; complete messages are returned as
    they become available and partial frames are buffered until the rest
    arrives.
    """

    def __init__(self, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES):
        self._buffer = bytearray()
        self._max_frame_bytes = max_frame_bytes

    def feed(self, data: bytes) -> list[fig_pb2.FederatedEvent]:
        self._buffer.extend(data)
        events = []

        while True:
            if len(self._buffer) < LENGTH_PREFIX.size:
                break

            (size,) = LENGTH_PREFIX.unpack_from(self._buffer, 0)
            if size > self._max_frame_bytes:
                raise FrameTooLargeError(size, self._max_frame_bytes)

            if len(self._buffer) < LENGTH_PREFIX.size + size:
                break

            payload = bytes(self._buffer[LENGTH_PREFIX.size : LENGTH_PREFIX.size + size])
            del self._buffer[: LENGTH_PREFIX.size + size]

            event = fig_pb2.FederatedEvent()
            event.ParseFromString(payload)
            events.append(event)

        return events
