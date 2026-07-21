"""Federation trust management.

TAK federation's security model hinges on a second truststore: the CAs that
may open *server-to-server* federation connections are kept separate from the
CA that signs EUD client certificates. A partner's CA lives only here, so
their TAK server can federate with us while EUD certificates issued by them
remain useless against the client streaming port.

Peer CA certificates are stored as individual PEM files in
``OTS_FEDERATION_TRUSTSTORE_FOLDER`` (default: ``<OTS_CA_FOLDER>/federation``).
Federates are identified by the SHA-256 fingerprint of their server
certificate, as in TAK Server.
"""

import hashlib
import logging
import os
import re
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding

logger = logging.getLogger("OpenTAKServer")


class NoFederationCAsError(Exception):
    def __init__(self, folder: str):
        super().__init__(
            f"No federation CA certificates in {folder} - upload a peer's CA before "
            "enabling federation"
        )


def truststore_folder(config) -> str:
    folder = config.get("OTS_FEDERATION_TRUSTSTORE_FOLDER") or os.path.join(
        config.get("OTS_CA_FOLDER"), "federation"
    )
    os.makedirs(folder, exist_ok=True)
    return folder


def _ca_paths(config) -> list[str]:
    folder = truststore_folder(config)
    return [
        os.path.join(folder, name) for name in sorted(os.listdir(folder)) if name.endswith(".pem")
    ]


def _server_cert_paths(config) -> tuple[str, str]:
    cert_folder = os.path.join(config.get("OTS_CA_FOLDER"), "certs", "opentakserver")
    return (
        os.path.join(cert_folder, "opentakserver.pem"),
        os.path.join(cert_folder, "opentakserver.nopass.key"),
    )


def _load_common(context: ssl.SSLContext, config) -> ssl.SSLContext:
    cert, key = _server_cert_paths(config)
    context.load_cert_chain(cert, key)

    ca_paths = _ca_paths(config)
    if not ca_paths:
        raise NoFederationCAsError(truststore_folder(config))
    for path in ca_paths:
        context.load_verify_locations(cafile=path)

    context.verify_mode = ssl.CERT_REQUIRED
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def server_ssl_context(config) -> ssl.SSLContext:
    return _load_common(ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER), config)


def client_ssl_context(config) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # TAK federation trusts by CA, not by hostname: federate certificates are
    # commonly issued to a server name that does not match the address dialed.
    context.check_hostname = bool(config.get("OTS_FEDERATION_VERIFY_HOSTNAME", False))
    return _load_common(context, config)


def truststore_pem(config) -> bytes:
    """All trusted peer CA certificates concatenated (for gRPC root_certificates)."""
    paths = _ca_paths(config)
    if not paths:
        raise NoFederationCAsError(truststore_folder(config))
    blob = b""
    for path in paths:
        with open(path, "rb") as f:
            blob += f.read()
            if not blob.endswith(b"\n"):
                blob += b"\n"
    return blob


def server_cert_pem(config) -> bytes:
    cert, _ = _server_cert_paths(config)
    with open(cert, "rb") as f:
        return f.read()


def server_key_pem(config) -> bytes:
    _, key = _server_cert_paths(config)
    with open(key, "rb") as f:
        return f.read()


def cert_fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def fingerprint_from_pem(pem: bytes) -> str | None:
    if not pem:
        return None
    return cert_fingerprint(x509.load_pem_x509_certificate(pem).public_bytes(Encoding.DER))


def peer_identity(ssl_socket: ssl.SSLSocket) -> tuple[str | None, str | None]:
    """Return (sha256 fingerprint, common name) of the peer's certificate."""
    der = ssl_socket.getpeercert(binary_form=True)
    if not der:
        return None, None

    fingerprint = cert_fingerprint(der)
    common_name = None
    try:
        cert = x509.load_der_x509_certificate(der)
        attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        if attrs:
            common_name = attrs[0].value
    except ValueError:
        logger.warning("Could not parse federation peer certificate for its common name")

    return fingerprint, common_name


def probe_grpc_peer_identity(
    config, address: str, port: int, authority: str, timeout: float = 15
) -> tuple[str, str | None]:
    """Verify and identify the certificate used by a federation v2 endpoint.

    Python's synchronous gRPC client does not expose the peer certificate. Do
    a short mutual-TLS/HTTP2 handshake first, using the same CA, client
    identity, and target authority as the gRPC channel, so the caller can
    enforce the per-federate leaf-certificate pin before opening the streams.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.set_alpn_protocols(["h2"])
    _load_common(context, config)

    with socket.create_connection((address, port), timeout=timeout) as raw_socket:
        with context.wrap_socket(raw_socket, server_hostname=authority) as tls_socket:
            if tls_socket.selected_alpn_protocol() != "h2":
                raise ssl.SSLError("federation v2 peer did not negotiate HTTP/2")
            fingerprint, common_name = peer_identity(tls_socket)

    if not fingerprint:
        raise ssl.SSLError("federation v2 peer did not present a certificate")
    return fingerprint, common_name


def _safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if not name.endswith(".pem"):
        name += ".pem"
    return name


def list_cas(config) -> list[dict]:
    cas = []
    for path in _ca_paths(config):
        entry = {"filename": os.path.basename(path)}
        try:
            with open(path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            entry["subject"] = cert.subject.rfc4514_string()
            entry["fingerprint"] = cert.fingerprint(hashes.SHA256()).hex()
            entry["not_after"] = cert.not_valid_after_utc.isoformat()
        except ValueError:
            entry["error"] = "unparseable certificate"
        cas.append(entry)
    return cas


def save_ca(config, filename: str, pem: bytes) -> dict:
    """Validate and store a peer CA certificate. Raises ValueError on bad PEM."""
    cert = x509.load_pem_x509_certificate(pem)

    filename = _safe_filename(filename)
    path = os.path.join(truststore_folder(config), filename)
    with open(path, "wb") as f:
        f.write(pem)

    logger.info(f"Added federation CA {cert.subject.rfc4514_string()} as {filename}")
    return {
        "filename": filename,
        "subject": cert.subject.rfc4514_string(),
        "fingerprint": cert.fingerprint(hashes.SHA256()).hex(),
    }


def delete_ca(config, filename: str) -> bool:
    path = os.path.join(truststore_folder(config), _safe_filename(filename))
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Removed federation CA {os.path.basename(path)}")
        return True
    return False
