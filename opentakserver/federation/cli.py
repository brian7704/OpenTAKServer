"""Federation management CLI: ``python -m opentakserver.federation.cli``.

A thin, scriptable front end over the Federation model and the federation
truststore, so an operator (or the HeartBeat ``heartbeat fed`` wrapper) can
manage federates without hand-writing REST calls. Every subcommand supports
``--json`` for machine consumption (the HeartBeat dashboard reads
``status --json``).

This runs in the OpenTAKServer virtualenv against the same config.yml/database
as the server, using the federation_server app context.
"""

import argparse
import json
import os
import sys

from sqlalchemy import select

from opentakserver.federation import truststore
from opentakserver.federation.federation_server import app


def _print(obj, as_json):
    if as_json:
        print(json.dumps(obj, default=str))
    return obj


def _peer_state(row):
    """Coarse connection state from the stored timestamps/error.

    ``connected`` if the last connect is newer than the last disconnect and
    there is no standing error, otherwise ``down``. ``idle`` when it has never
    connected.
    """
    if row.last_connected is None and row.last_disconnected is None:
        return "idle"
    lc = row.last_connected
    ld = row.last_disconnected
    if lc is not None and (ld is None or lc >= ld) and not row.last_error:
        return "connected"
    return "down"


def cmd_list(args):
    from opentakserver.extensions import db
    from opentakserver.models.Federation import Federation

    with app.app_context():
        rows = db.session.execute(select(Federation).order_by(Federation.name)).all()
        peers = [row[0].to_json() for row in rows]

    if args.json:
        _print({"federates": peers}, True)
    else:
        if not peers:
            print("No federates configured.")
            return
        for peer in peers:
            direction = "dial" if peer["outbound"] else "listen"
            groups = ",".join(peer.get("inbound_groups") or []) or "-"
            out_groups = ",".join(peer.get("outbound_groups") or []) or "-"
            enabled = "on" if peer["enabled"] else "off"
            target = f"{peer['address']}:{peer['port']}" if peer["address"] else "(inbound)"
            print(
                f"  {peer['name']:<20} v{peer['protocol_version']} {direction:<6} {enabled:<3} "
                f"{target:<28} in[{groups}] out[{out_groups}]"
            )


def cmd_status(args):
    from opentakserver.extensions import db
    from opentakserver.models.Federation import Federation

    with app.app_context():
        rows = db.session.execute(select(Federation).order_by(Federation.name)).all()
        peers = []
        for (row,) in rows:
            data = row.to_json()
            data["state"] = _peer_state(row)
            peers.append(data)

    federation_enabled = bool(app.config.get("OTS_ENABLE_FEDERATION"))
    payload = {
        "enabled": federation_enabled,
        "v1_port": app.config.get("OTS_FEDERATION_V1_PORT"),
        "v2_port": app.config.get("OTS_FEDERATION_V2_PORT"),
        "v2_enabled": bool(app.config.get("OTS_FEDERATION_ENABLE_V2")),
        "federates": peers,
    }

    if args.json:
        _print(payload, True)
        return

    print(f"Federation: {'enabled' if federation_enabled else 'disabled'}")
    print(f"  v1 port {payload['v1_port']}  v2 port {payload['v2_port']}")
    if not peers:
        print("  no federates configured")
        return
    for peer in peers:
        mark = {"connected": "[UP ]", "down": "[DN ]", "idle": "[---]"}[peer["state"]]
        target = f"{peer['address']}:{peer['port']}" if peer["address"] else "(inbound)"
        line = f"  {mark} {peer['name']:<20} v{peer['protocol_version']} {target}"
        if peer.get("last_error"):
            line += f"  err: {peer['last_error']}"
        print(line)


def _parse_groups(value):
    if not value:
        return []
    return [g.strip() for g in value.split(",") if g.strip()]


def cmd_add(args):
    from opentakserver.extensions import db
    from opentakserver.models.Federation import Federation

    with app.app_context():
        row = db.session.execute(
            select(Federation).filter_by(name=args.name)
        ).first()
        row = row[0] if row else Federation()
        row.name = args.name
        if row.inbound_groups is None:
            row.inbound_groups = []
        if row.outbound_groups is None:
            row.outbound_groups = []

        if args.address is not None:
            row.address = args.address or None
        if args.port is not None:
            row.port = args.port
        row.protocol_version = args.protocol
        row.outbound = bool(args.address)
        if args.enabled is not None:
            row.enabled = args.enabled
        elif row.enabled is None:
            row.enabled = True
        if args.reconnect is not None:
            row.reconnect_interval = args.reconnect

        if args.in_groups is not None:
            row.inbound_groups = _parse_groups(args.in_groups)
        if args.out_groups is not None:
            row.outbound_groups = _parse_groups(args.out_groups)
        if args.groups is not None:
            both = _parse_groups(args.groups)
            row.inbound_groups = both
            row.outbound_groups = both

        if row.outbound and not row.address:
            print("error: outbound federate requires --host", file=sys.stderr)
            return 2

        db.session.add(row)
        db.session.commit()
        result = row.to_json()

    _print({"ok": True, "federate": result}, args.json) or print(f"Saved federate '{args.name}'.")
    return 0


def cmd_remove(args):
    from opentakserver.extensions import db
    from opentakserver.models.Federation import Federation

    with app.app_context():
        row = db.session.execute(
            select(Federation).filter_by(name=args.name)
        ).first()
        if not row:
            print(f"error: no federate named '{args.name}'", file=sys.stderr)
            return 1
        db.session.delete(row[0])
        db.session.commit()

    _print({"ok": True}, args.json) or print(f"Removed federate '{args.name}'.")
    return 0


def _set_enabled(name, enabled, as_json):
    from opentakserver.extensions import db
    from opentakserver.models.Federation import Federation

    with app.app_context():
        row = db.session.execute(select(Federation).filter_by(name=name)).first()
        if not row:
            print(f"error: no federate named '{name}'", file=sys.stderr)
            return 1
        row[0].enabled = enabled
        db.session.commit()

    _print({"ok": True, "enabled": enabled}, as_json) or print(
        f"Federate '{name}' {'enabled' if enabled else 'disabled'}."
    )
    return 0


def cmd_enable(args):
    return _set_enabled(args.name, True, args.json)


def cmd_disable(args):
    return _set_enabled(args.name, False, args.json)


def cmd_ca_list(args):
    with app.app_context():
        cas = truststore.list_cas(app.config)
    if args.json:
        _print({"cas": cas}, True)
        return 0
    if not cas:
        print("No federation CAs trusted yet.")
        return 0
    for ca in cas:
        print(f"  {ca['filename']:<28} {ca.get('subject', ca.get('error', ''))}")
    return 0


def cmd_ca_import(args):
    if not os.path.exists(args.file):
        print(f"error: no such file: {args.file}", file=sys.stderr)
        return 1
    with open(args.file, "rb") as f:
        pem = f.read()
    with app.app_context():
        try:
            result = truststore.save_ca(app.config, args.name or os.path.basename(args.file), pem)
        except ValueError as e:
            print(f"error: invalid certificate: {e}", file=sys.stderr)
            return 1
    _print({"ok": True, "ca": result}, args.json) or print(
        f"Trusted federation CA '{result['filename']}' ({result.get('subject', '')})."
    )
    return 0


def cmd_ca_export(args):
    ca_path = os.path.join(app.config.get("OTS_CA_FOLDER"), "ca.pem")
    if not os.path.exists(ca_path):
        print(f"error: CA not found at {ca_path}", file=sys.stderr)
        return 1
    with open(ca_path, "rb") as f:
        pem = f.read()
    if args.out:
        with open(args.out, "wb") as f:
            f.write(pem)
        _print({"ok": True, "path": args.out}, args.json) or print(
            f"Exported this server's CA to {args.out} — hand it to the peer administrator."
        )
    else:
        sys.stdout.buffer.write(pem)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="opentakserver.federation.cli")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list configured federates").set_defaults(func=cmd_list)
    sub.add_parser("status", help="federates with live connection state").set_defaults(
        func=cmd_status
    )

    add = sub.add_parser("add", help="add or update a federate")
    add.add_argument("name")
    add.add_argument("--host", "--address", dest="address", default=None)
    add.add_argument("--port", type=int, default=None)
    add.add_argument("--protocol", type=int, choices=(1, 2), default=1)
    add.add_argument("--reconnect", type=int, default=None)
    add.add_argument("--groups", default=None, help="comma-separated, sets both directions")
    add.add_argument("--in-groups", dest="in_groups", default=None)
    add.add_argument("--out-groups", dest="out_groups", default=None)
    add.add_argument("--enabled", dest="enabled", action="store_true", default=None)
    add.add_argument("--disabled", dest="enabled", action="store_false", default=None)
    add.set_defaults(func=cmd_add)

    rm = sub.add_parser("remove", help="delete a federate")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_remove)

    en = sub.add_parser("enable", help="enable a federate")
    en.add_argument("name")
    en.set_defaults(func=cmd_enable)

    dis = sub.add_parser("disable", help="disable a federate")
    dis.add_argument("name")
    dis.set_defaults(func=cmd_disable)

    ca = sub.add_parser("ca", help="federation CA truststore")
    ca_sub = ca.add_subparsers(dest="ca_command", required=True)
    ca_sub.add_parser("list", help="list trusted peer CAs").set_defaults(func=cmd_ca_list)
    ca_import = ca_sub.add_parser("import", help="trust a peer CA")
    ca_import.add_argument("file")
    ca_import.add_argument("--name", default=None)
    ca_import.set_defaults(func=cmd_ca_import)
    ca_export = ca_sub.add_parser("export", help="export this server's CA")
    ca_export.add_argument("--out", default=None)
    ca_export.set_defaults(func=cmd_ca_export)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    # Propagate the top-level --json to subcommand handlers
    if not hasattr(args, "json"):
        args.json = False
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
