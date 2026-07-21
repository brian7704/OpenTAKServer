# Federation

OpenTAKServer implements TAK Server **federation** v1 and the situational-
awareness subset of v2: server-to-server exchange between independent
administrative domains. Each side keeps its own users, certificate authority,
and admin control, and allowlists what crosses the link. OpenTAKServer-to-
OpenTAKServer operation and interoperability with official TAK Server 5.5 are
live-validated over both transports. Direct-spoke interoperability with
official TAK Federation Hub 5.7 is also live-validated over both transports.

Two transports, both carrying the official protobuf `FederatedEvent` and both
using the same federation truststore and group model:

- **v1** (port 9000): length-prefixed `FederatedEvent` frames over a
  mutually-authenticated TLS socket.
- **v2** (port 9001): the official `FederatedChannel` gRPC service over
  HTTP/2 — `ClientEventStream`/`ServerEventStream` for events, plus
  `getIdentity`/`HealthCheck`. `getIdentity` is optional on the peer: official
  TAK Server 5.5 declares it but leaves its server implementation unimplemented.

The protobuf and service definitions are vendored from the TAK Product Center's
public TAK Server source (GPLv3, like OpenTAKServer) and are intended to be wire
compatible. Set a federate's `protocol_version` (1 or 2) to choose the transport
for an outbound connection; both listeners run at once for inbound.

## Implemented scope and invariants

This implementation is intentionally bounded to point-to-point situational
awareness:

- v1 framed TLS and v2 gRPC share the same CoT conversion, group filtering,
  loop guard, contact registration, and local-UID collision policy.
- CoT and contact announcements cross a link only when the sender belongs to an
  allowed outbound group. Empty group lists allow no new contacts or data;
  contact deletions may still cross so removing access revokes prior presence.
- Both transports require mutual TLS against the federation CA truststore.
  v1 pins the peer leaf on its transport connection. Because synchronous
  Python gRPC does not expose the client-side peer certificate, v2 checks the
  same leaf pin with a verified TLS/HTTP2 preflight immediately before opening
  its CA- and authority-verified gRPC channel.
- An unknown inbound certificate is registered as
  `<certificate-CN>-<fingerprint-prefix>` with empty groups. A remote UID that
  already belongs to a local EUD is rejected rather than modifying that EUD.
- Federation traffic enters through `cot_parser`, not `firehose`, preventing
  re-federation and multi-hop loops.

Not in this scope: ROL/mission federation, group-mapping RPCs, transitive
federation through a normal TAK Server, and service-manager/installer wiring.

## What federates

- Situational awareness CoT (positions, markers, alerts) and GeoChat,
  including point-to-point chat addressed with `<marti><dest/>`
- Contact announcements (`ContactListEntry` create/delete for connected EUDs)

Mission/Data Sync federation and mission packages are the ROL (resource
operation language) side of v2 and are not implemented. v2 here is the SA
subset of the `FederatedChannel` service; ROL and group-mapping RPCs are
declared for wire compatibility but are not served.

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
federation is never re-federated. Official TAK Server applies the same boundary:
its v1 and v2 federate subscriptions reject events already marked as federated.
Point-to-point federation therefore does not forward multi-hop.

This rules out a normal official server as a transparent federation gateway:

```text
OTS --federation--> official TAK --federation--> Hub
      direct link       does not re-federate the received OTS event
```

If a Hub policy accepts only official TAK Servers, the bounded options are:

1. connect OTS directly to the Hub if the policy owner accepts its verified
   protocol-compatible implementation;
2. inject OTS SA/chat into the official server through a controlled local
   streaming/data-feed bridge, so the official server sees locally originated
   traffic and can federate it to the Hub; or
3. make official TAK Server the users' home server for the Hub-connected
   enclave.

Option 2 is a CoT gateway, not federation-through-federation, and still does
not add OTS ROL/mission federation.

If the Hub policy owner accepts OTS's CA identity, OTS can instead connect
directly as a normal Hub spoke. This topology is live-validated:

```text
OTS A --v1/v2--> official Federation Hub <--v1/v2-- OTS B
```

The Hub policy graph controls which spoke CAs may exchange traffic. OTS keeps
its structural loop guard, while the Hub performs the authorized brokering.
This carries the implemented SA/contact/GeoChat subset; it does not add
ROL/mission or federated-group-stream support.

A federate with **empty group lists exchanges no new contacts or data** - after
trust is established you must assign inbound/outbound groups (use `__ANON__`
for the default channel) before data flows. Contact deletion messages remain
effective so an administrator can revoke access without leaving stale presence.

## Trust model

Federation uses a **separate truststore** from EUD client certificates:
`<OTS_CA_FOLDER>/federation/` holds one PEM per trusted peer CA. A partner's
CA being in the federation truststore lets their *server* connect to the
federation port - it does not let their EUD certificates connect to the
streaming port, and vice versa.

Federates are identified by the SHA-256 fingerprint of their server
certificate. Inbound federates are auto-registered with a collision-resistant
CN/fingerprint name and empty group lists. Outbound federates have their leaf
fingerprint pinned on first connect and later connections must present the same
certificate. For v2, a short verified mutual-TLS/HTTP2 handshake obtains and
checks the leaf identity immediately before the gRPC streams are opened. This
preflight is a separate TLS connection; the stream itself remains protected by
the configured CA and authority, but Python gRPC cannot bind the leaf pin to
that exact socket.

## Setup

1. **Enable** federation in `config.yml` (or by environment variable):

   ```yaml
   OTS_ENABLE_FEDERATION: true
   OTS_FEDERATION_V1_PORT: 9000
   OTS_FEDERATION_V2_PORT: 9001
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
     "protocol_version": 1,
     "outbound": true,
     "inbound_groups": ["__ANON__"],
     "outbound_groups": ["__ANON__"]
   }
   ```

   For an inbound-only federate, skip this step: the row is auto-created when
   they connect, then assign groups with the same `POST /api/federation` call.

   For v2, use `"protocol_version": 2` and the peer's v2 port (normally 9001).

4. **Run the federation server** process. Installer/service-manager integration
   is not included in this change, so deployments must start it explicitly:

   ```bash
   federation_server
   ```

5. **Verify**: `GET /api/federation` shows `last_connected`/`last_error` per
   federate.

The validated official TAK Server setup uploads OpenTAKServer's `ca.pem` on
*Manage Federate Certificate Authorities*, enables the v1/v2 listener, and
assigns inbound and outbound federate groups. Only one side needs an outgoing
connection. Use port 9000 with protocol version 1 or port 9001 with protocol
version 2. For v2, set `OTS_FEDERATION_V2_AUTHORITY` to the official server
certificate's DNS name or IP identity.

## Validation

Unit and in-process transport coverage lives in `tests/test_federation.py`.
The HeartBeat repository's `tools/fed_live_test.py` stands up two complete OTS
stacks with separate RabbitMQ, Postgres, and CA instances and exercises either
transport end to end. Each run retains logs plus a `result.json` artifact under
its printed `/tmp/fed-live-*` workspace.

Because this branch changes the EUD concurrency model from per-connection
forks to threads (so duplicate-UID ownership can be shared safely), the
HeartBeat repository also provides `tools/eud_threading_soak_test.py`. It uses
real EUD handler and CoT parser processes with disposable RabbitMQ/Postgres,
parallel first-SA connections, repeated same-UID replacements, broadcast and
addressed-message checks, thread/RSS sampling, log scanning, and stalled TLS
handshakes:

```bash
cd heartbeat
python3 tools/eud_threading_soak_test.py
```

On 2026-07-21 the default gate passed all 43 checks with 24 simultaneous EUDs,
five rounds replacing 23 UIDs in parallel (115 replacement sessions), and 12
stalled TLS clients. TCP threads stayed at 80 in every active round and
returned from 80 to the 32-thread process baseline; SSL threads rose from 32
to 56 and returned to 32. No SQLAlchemy, RabbitMQ-thread, or Flask application
context failures were logged.

`tools/fed_official_live_test.py` performs the official interoperability gate.
It copies an installed official TAK payload into `/tmp`, uses disposable
databases and containers, exchanges federation CAs, and validates mTLS/pinning,
SA in both directions, federated-contact registration, addressed GeoChat in
both directions, non-broadcast DM routing, and loop freedom. It does not modify
the installed payload, active TAK backend, or persistent official database:

```bash
cd heartbeat
python3 tools/fed_official_live_test.py --tak-home /path/to/tak-server
python3 tools/fed_official_live_test.py --tak-home /path/to/tak-server --v2
```

On 2026-07-21 both runs passed all 10 checks against official TAK Server
`5.5-RELEASE-58-HEAD`. The v2 run also exposed and fixed a compatibility detail:
official 5.5 returns `UNIMPLEMENTED` for the optional `getIdentity` RPC, while
identity is carried in the stream `Subscription` as used by stock TAK clients.

`tools/fed_hub_live_test.py` performs the official Federation Hub gate with two
full OTS spokes. It extracts the official Docker distribution below `/tmp`,
creates disposable Hub/OTS trust and CA policy, activates that policy through
the official Hub admin API, and exercises the production path without changing
the downloaded archive or persistent HeartBeat state:

```bash
cd heartbeat
python3 tools/fed_hub_live_test.py --hub-bundle ~/Downloads/takserver-fedhub-docker-5.7-RELEASE-43.zip
python3 tools/fed_hub_live_test.py --hub-bundle ~/Downloads/takserver-fedhub-docker-5.7-RELEASE-43.zip --v2
```

On 2026-07-21 both runs passed all 12 checks against official Federation Hub
`5.7-RELEASE-43`: both OTS-to-Hub mTLS/pinned links, SA and addressed GeoChat
through the Hub in both directions, federated contacts, DM non-broadcast, and
loop freedom. The v2 run exposed Hub's required health refresh and a Hub 5.7
compatibility quirk: its unary `HealthCheck` sends `SERVING` without completing
the RPC. OTS now refreshes the stream on the official cadence and tolerates
that non-completing response.

## Configuration reference

| Key | Default | Meaning |
|-----|---------|---------|
| `OTS_ENABLE_FEDERATION` | `False` | Master switch for the federation server |
| `OTS_FEDERATION_V1_PORT` | `9000` | Listening port for federation v1 |
| `OTS_FEDERATION_ENABLE_V2` | `True` | Also run the v2 (gRPC) listener |
| `OTS_FEDERATION_V2_PORT` | `9001` | Listening port for federation v2 |
| `OTS_FEDERATION_V2_HEALTH_CHECK_INTERVAL_SECONDS` | `5` | Interval for v2 `HealthCheck(SERVING)` reports required by TAK Server and Federation Hub |
| `OTS_FEDERATION_V2_AUTHORITY` | `opentakserver` | Peer cert CN gRPC verifies against (TAK trusts by CA; OTS server certs use CN `opentakserver`) |
| `OTS_FEDERATION_INTERFACE` | `0.0.0.0` | Listening interface |
| `OTS_FEDERATION_RECONNECT_SECONDS` | `30` | Default outbound reconnect interval |
| `OTS_FEDERATION_CONTACT_INTERVAL_SECONDS` | `30` | Contact announcement refresh |
| `OTS_FEDERATION_MAX_FRAME_BYTES` | `16777216` | Reject frames larger than this |
| `OTS_FEDERATION_VERIFY_HOSTNAME` | `False` | Also verify the peer's hostname (TAK federation normally trusts by CA only) |
| `OTS_FEDERATION_TRUSTSTORE_FOLDER` | `<OTS_CA_FOLDER>/federation` | Peer CA PEM folder |
