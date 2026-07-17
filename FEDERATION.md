# Federation

OpenTAKServer implements TAK Server **federation** (v1 and v2): server-to-server
exchange of situational awareness with other TAK servers (official TAK Server
or another OpenTAKServer), across independent administrative domains. Each
side keeps its own users, certificate authority, and admin control, and
allowlists what crosses the link.

Two transports, both carrying the official protobuf `FederatedEvent` and both
using the same federation truststore and group model:

- **v1** (port 9000): length-prefixed `FederatedEvent` frames over a
  mutually-authenticated TLS socket.
- **v2** (port 9001): the official `FederatedChannel` gRPC service over
  HTTP/2 — `ClientEventStream`/`ServerEventStream` for events, plus
  `getIdentity`/`HealthCheck`.

The protobuf and service definitions are vendored from the TAK Product Center's
public TAK Server source (GPLv3, like OpenTAKServer), so an official TAK Server
can federate with OpenTAKServer with no changes on its side. Set a federate's
`protocol_version` (1 or 2) to choose the transport for an outbound connection;
both listeners run at once for inbound.

## What federates

- Situational awareness CoT (positions, markers, alerts) and GeoChat,
  including point-to-point chat addressed with `<marti><dest/>`
- Contact announcements (`ContactListEntry` create/delete for connected EUDs)

Not yet: mission/Data Sync federation and mission packages — these are the ROL
(resource operation language) side of v2, which is not implemented. v2 here is
the SA subset of the `FederatedChannel` service (the ROL and group-mapping RPCs
are declared for wire compatibility but not served).

## How it works

The `federation_server` process (a sibling of `eud_handler` and `cot_parser`)
owns all federation links:

- **Outbound**: each link consumes the `firehose` exchange (every CoT received
  from a local EUD), filters by the federate's *outbound groups* against the
  sending user's group memberships, converts to `FederatedEvent`, and streams
  frames to the peer.
- **Inbound**: received events are converted back to CoT and published to the
  `cot_parser` exchange like any locally received event, tagged with the
  federate's *inbound groups* so they route into those channels (and are
  persisted/parsed normally).

Loop prevention is structural: only EUD handlers publish to `firehose`, and
federated traffic enters via `cot_parser`, so an event that arrived over
federation is never re-federated. Like TAK Server, point-to-point federation
does not forward multi-hop.

A federate with **empty group lists exchanges nothing** - after trust is
established you must assign inbound/outbound groups (use `__ANON__` for the
default channel) before data flows. This matches official TAK Server, where
traffic starts only after both sides configure federate groups.

## Trust model

Federation uses a **separate truststore** from EUD client certificates:
`<OTS_CA_FOLDER>/federation/` holds one PEM per trusted peer CA. A partner's
CA being in the federation truststore lets their *server* connect to the
federation port - it does not let their EUD certificates connect to the
streaming port, and vice versa.

Federates are identified by the SHA-256 fingerprint of their server
certificate. Inbound federates are auto-registered (with empty group lists)
on first connection; outbound federates have their fingerprint pinned on
first connect and later connections must present the same certificate.

## Setup

1. **Enable** federation in `config.yml` (or by environment variable):

   ```yaml
   OTS_ENABLE_FEDERATION: true
   OTS_FEDERATION_V1_PORT: 9000
   ```

2. **Swap CAs** with the other administrative domain out of band (email, USB).
   Yours is `<OTS_CA_FOLDER>/ca.pem`. Upload theirs:

   ```
   POST /api/federation/ca            (multipart field "ca", or JSON {"filename", "pem"})
   GET  /api/federation/ca            list trusted federation CAs
   ```

3. **Create the federate** (only one side dials - the other just listens):

   ```
   POST /api/federation
   {
     "name": "partner-agency",
     "address": "tak.partner.example",
     "port": 9000,
     "outbound": true,
     "inbound_groups": ["__ANON__"],
     "outbound_groups": ["__ANON__"]
   }
   ```

   For an inbound-only federate, skip this step: the row is auto-created when
   they connect, then assign groups with the same `POST /api/federation` call.

4. **Run the federation server** process:

   ```bash
   federation_server
   ```

5. **Verify**: `GET /api/federation` shows `last_connected`/`last_error` per
   federate.

On the official TAK Server side, this is the standard federation setup: upload
OpenTAKServer's `ca.pem` on *Manage Federate Certificate Authorities*, create
an outgoing connection to port 9000 with protocol version 1 (or just listen),
and assign federate groups.

## Configuration reference

| Key | Default | Meaning |
|-----|---------|---------|
| `OTS_ENABLE_FEDERATION` | `False` | Master switch for the federation server |
| `OTS_FEDERATION_V1_PORT` | `9000` | Listening port for federation v1 |
| `OTS_FEDERATION_ENABLE_V2` | `True` | Also run the v2 (gRPC) listener |
| `OTS_FEDERATION_V2_PORT` | `9001` | Listening port for federation v2 |
| `OTS_FEDERATION_V2_AUTHORITY` | `opentakserver` | Peer cert CN gRPC verifies against (TAK trusts by CA; OTS server certs use CN `opentakserver`) |
| `OTS_FEDERATION_INTERFACE` | `0.0.0.0` | Listening interface |
| `OTS_FEDERATION_RECONNECT_SECONDS` | `30` | Default outbound reconnect interval |
| `OTS_FEDERATION_CONTACT_INTERVAL_SECONDS` | `30` | Contact announcement refresh |
| `OTS_FEDERATION_MAX_FRAME_BYTES` | `16777216` | Reject frames larger than this |
| `OTS_FEDERATION_VERIFY_HOSTNAME` | `False` | Also verify the peer's hostname (TAK federation normally trusts by CA only) |
| `OTS_FEDERATION_TRUSTSTORE_FOLDER` | `<OTS_CA_FOLDER>/federation` | Peer CA PEM folder |
