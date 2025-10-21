# Multicast Support for OpenTAKServer

OpenTAKServer now supports UDP multicast for sending and receiving CoT (Cursor on Target) messages. This feature enables local network discovery and mesh networking capabilities compatible with TAK clients that support multicast.

## Overview

The multicast feature consists of two components:

1. **Multicast Receiver**: Listens for CoT messages on a UDP multicast group and forwards them to OpenTAKServer
2. **Multicast Sender**: Broadcasts CoT messages from OpenTAKServer to the multicast group

Both components can be enabled/disabled independently and run as a separate service alongside the main OpenTAKServer components.

## Configuration

Multicast settings can be configured via environment variables or in the `config.yml` file:

### Environment Variables

```bash
# Enable/disable multicast (default: False)
OTS_ENABLE_MULTICAST=True

# Multicast group address (default: 239.2.3.1 - standard TAK multicast address)
OTS_MULTICAST_ADDRESS=239.2.3.1

# Multicast port (default: 8087)
OTS_MULTICAST_PORT=8087

# Multicast TTL - Time to Live (default: 1)
# 1 = local network only, higher values allow routing
OTS_MULTICAST_TTL=1

# Enable/disable sending CoT to multicast (default: True)
OTS_MULTICAST_SEND=True

# Enable/disable receiving CoT from multicast (default: True)
OTS_MULTICAST_RECEIVE=True
```

### config.yml

Add these settings to your `~/ots/config.yml`:

```yaml
OTS_ENABLE_MULTICAST: true
OTS_MULTICAST_ADDRESS: "239.2.3.1"
OTS_MULTICAST_PORT: 8087
OTS_MULTICAST_TTL: 1
OTS_MULTICAST_SEND: true
OTS_MULTICAST_RECEIVE: true
```

## Running the Multicast Handler

### Standalone Installation

If you installed OpenTAKServer via pip/poetry:

```bash
# Start the multicast handler
multicast_handler
```

### Docker Installation

Build the multicast Docker image:

```bash
docker build -f opentakserver/eud_handler/Dockerfile-multicast -t opentakserver-multicast .
```

Run the multicast container:

```bash
docker run -d \
  --name ots-multicast \
  --network host \
  -e OTS_ENABLE_MULTICAST=True \
  -e OTS_MULTICAST_ADDRESS=239.2.3.1 \
  -e OTS_MULTICAST_PORT=8087 \
  -e OTS_RABBITMQ_SERVER_ADDRESS=127.0.0.1 \
  -v ~/ots:/root/ots \
  opentakserver-multicast
```

**Note**: Using `--network host` is recommended for multicast to work properly, as it requires access to the host's network interfaces.

### Systemd Service

Create a systemd service file `/etc/systemd/system/ots-multicast.service`:

```ini
[Unit]
Description=OpenTAKServer Multicast Handler
After=network.target rabbitmq-server.service

[Service]
Type=simple
User=ots
WorkingDirectory=/opt/opentakserver
Environment="OTS_ENABLE_MULTICAST=True"
Environment="OTS_MULTICAST_ADDRESS=239.2.3.1"
Environment="OTS_MULTICAST_PORT=8087"
ExecStart=/usr/local/bin/multicast_handler
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ots-multicast
sudo systemctl start ots-multicast
sudo systemctl status ots-multicast
```

## How It Works

### Message Flow

#### Receiving Multicast CoT:
1. External TAK client broadcasts CoT to multicast group `239.2.3.1:8087`
2. MulticastServer receives the UDP packet
3. CoT XML is validated and parsed
4. Message is published to RabbitMQ `cot_controller` exchange
5. cot_parser processes the message (same as TCP/SSL connections)
6. Message is distributed to all connected clients via RabbitMQ

#### Sending Multicast CoT:
1. Client sends CoT to OpenTAKServer (via TCP/SSL)
2. Message flows through normal processing pipeline
3. Message is published to RabbitMQ `cot` fanout exchange
4. MulticastSender receives the message from RabbitMQ
5. CoT XML is broadcast to multicast group `239.2.3.1:8087`
6. All devices listening on multicast receive the message

### Loop Prevention

The multicast sender automatically prevents message loops by checking the message source. If a message originated from multicast, it will not be re-broadcast to avoid infinite loops.

## Network Requirements

### Firewall Configuration

Ensure UDP port 8087 (or your configured port) is open for multicast traffic:

```bash
# Linux (iptables)
sudo iptables -A INPUT -p udp --dport 8087 -j ACCEPT
sudo iptables -A OUTPUT -p udp --dport 8087 -j ACCEPT

# Linux (ufw)
sudo ufw allow 8087/udp

# firewalld
sudo firewall-cmd --permanent --add-port=8087/udp
sudo firewall-cmd --reload
```

### Network Interface Configuration

For multicast to work, your network interface must support IGMP (Internet Group Management Protocol):

```bash
# Check if multicast is enabled on your interface
ip link show eth0

# Look for "MULTICAST" flag
# Example output: <BROADCAST,MULTICAST,UP,LOWER_UP>
```

### Router Configuration

Some routers block multicast traffic by default. Ensure:
- IGMP snooping is enabled
- Multicast routing is enabled (if needed across VLANs)
- Multicast group 239.2.3.1 is allowed

## Testing Multicast

### Test with netcat

Send a test CoT message to the multicast group:

```bash
echo '<?xml version="1.0"?><event version="2.0" uid="TEST-001" type="a-f-G-U-C" time="2025-01-01T12:00:00Z" start="2025-01-01T12:00:00Z" stale="2025-01-01T12:05:00Z"><point lat="0.0" lon="0.0" hae="0.0" ce="9999999" le="9999999"/><detail></detail></event>' | socat - UDP4-DATAGRAM:239.2.3.1:8087
```

### Test with Python

```python
import socket
import struct

MULTICAST_GROUP = '239.2.3.1'
MULTICAST_PORT = 8087

# Create socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

# Send CoT message
cot_xml = '''<?xml version="1.0"?>
<event version="2.0" uid="TEST-001" type="a-f-G-U-C"
       time="2025-01-01T12:00:00Z" start="2025-01-01T12:00:00Z"
       stale="2025-01-01T12:05:00Z">
    <point lat="0.0" lon="0.0" hae="0.0" ce="9999999" le="9999999"/>
    <detail></detail>
</event>'''

sock.sendto(cot_xml.encode('utf-8'), (MULTICAST_GROUP, MULTICAST_PORT))
print("Sent CoT to multicast")
```

### Monitor Multicast Traffic

Listen for multicast messages:

```bash
# Using tcpdump
sudo tcpdump -i any -n udp port 8087

# Using socat
socat UDP4-RECVFROM:8087,ip-add-membership=239.2.3.1:0.0.0.0,fork -
```

## Troubleshooting

### No multicast messages received

1. **Check if multicast is enabled**:
   ```bash
   grep OTS_ENABLE_MULTICAST ~/ots/config.yml
   ```

2. **Check multicast handler logs**:
   ```bash
   tail -f ~/ots/logs/opentakserver.log | grep multicast
   ```

3. **Verify network interface supports multicast**:
   ```bash
   ip link show | grep MULTICAST
   ```

4. **Check RabbitMQ connection**:
   ```bash
   sudo rabbitmqctl list_connections
   ```

5. **Test network reachability**:
   ```bash
   ping 239.2.3.1
   ```

### Messages sent but not received by clients

1. **Check TTL setting**: Increase `OTS_MULTICAST_TTL` if clients are on different subnets
2. **Check firewall**: Ensure UDP port 8087 is open
3. **Check router multicast settings**: Enable IGMP snooping
4. **Verify multicast group**: Ensure all clients use the same multicast address

### Multicast handler crashes

1. **Check RabbitMQ is running**:
   ```bash
   sudo systemctl status rabbitmq-server
   ```

2. **Check database connectivity**:
   ```bash
   psql -U ots -d ots -c "SELECT 1"
   ```

3. **Review logs for errors**:
   ```bash
   tail -100 ~/ots/logs/opentakserver.log
   ```

## Performance Considerations

- **UDP is unreliable**: Multicast uses UDP, which doesn't guarantee delivery. Use TCP/SSL connections for critical communications.
- **Network overhead**: Broadcasting to multicast adds network traffic. Monitor your network bandwidth.
- **TTL settings**: Keep TTL low (1-2) for local networks to prevent multicast storms.
- **Message rate**: High-frequency position updates can flood the network. Consider throttling.

## Security Considerations

- **No authentication**: Multicast messages are not authenticated. Anyone on the network can send/receive.
- **No encryption**: Messages are sent in plain text. Don't send sensitive information via multicast.
- **Network segmentation**: Use VLANs or network segmentation to limit multicast scope.
- **Firewall rules**: Restrict multicast traffic to trusted network segments.

## Use Cases

1. **Local Discovery**: Allow TAK clients to discover the server without manual configuration
2. **Mesh Networking**: Enable peer-to-peer CoT sharing in disconnected environments
3. **Redundancy**: Provide backup communication channel if TCP/SSL fails
4. **Testing**: Easy testing and development without server authentication
5. **Legacy Support**: Support older TAK versions that rely on multicast

## Related Documentation

- [TAK Protocol Documentation](https://tak.gov)
- [RFC 1112 - IP Multicast](https://tools.ietf.org/html/rfc1112)
- [OpenTAKServer Documentation](https://docs.opentakserver.io)

## Support

For issues, questions, or feature requests related to multicast support:
- GitHub Issues: https://github.com/brian7704/OpenTAKServer/issues
- Documentation: https://docs.opentakserver.io
