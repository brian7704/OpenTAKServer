import datetime
import logging
import os
import subprocess

import pytest
import sqlalchemy
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from flask import Flask
from flask_security.models import fsqla
from geoalchemy2.admin.dialects import sqlite as sqlite_dialect

from opentakserver.certificate_authority import (
    CertificateAuthority,
    get_serial_number,
    is_revoked,
)
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.extensions import db
from opentakserver.models.RevokedCertificate import RevokedCertificate


@pytest.fixture
def ca_app(tmp_path, monkeypatch):
    # GeoAlchemy loads SpatiaLite on every SQLite connection, these tests don't need it
    monkeypatch.setattr(sqlite_dialect, "load_spatialite", lambda *args, **kwargs: None)

    app = Flask(__name__)
    app.config.from_object(DefaultConfig)
    app.config["OTS_CA_FOLDER"] = str(tmp_path / "ca")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    db.init_app(app)

    # Registers all models, as create_app() does, so SQLAlchemy can resolve their relationships
    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass
    from opentakserver.blueprints.ots_api import ots_api  # noqa: F401
    from opentakserver.models.role import Role  # noqa: F401
    from opentakserver.models.user import User  # noqa: F401

    with app.app_context():
        RevokedCertificate.__table__.create(db.engine)
        ca = CertificateAuthority(logging.getLogger(), app)
        # create_ca() and sign_csr() run openssl with relative paths from the CA folder
        cwd = os.getcwd()
        try:
            ca.create_ca()
        finally:
            os.chdir(cwd)
        yield app, ca


def sign_client_cert(ca: CertificateAuthority, common_name: str) -> x509.Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    pem = ca.sign_csr(csr.public_bytes(serialization.Encoding.PEM), common_name, False)
    return x509.load_pem_x509_certificate(pem)


def revoke(cert: x509.Certificate, common_name: str):
    db.session.add(
        RevokedCertificate(
            serial_number=format(cert.serial_number, "x"),
            common_name=common_name,
            revoked_at=datetime.datetime.now(datetime.timezone.utc),
        )
    )
    db.session.commit()


def test_client_serial_numbers_are_random_and_large(ca_app):
    app, ca = ca_app
    serials = {sign_client_cert(ca, "alice").serial_number for _ in range(3)}
    assert len(serials) == 3
    assert all(serial > 2**64 for serial in serials)


def test_get_serial_number_is_hex(ca_app):
    app, ca = ca_app
    cert = sign_client_cert(ca, "alice")
    pem = cert.public_bytes(serialization.Encoding.PEM)
    assert get_serial_number(pem) == format(cert.serial_number, "x")


def test_initial_openssl_crl_revokes_nothing(ca_app):
    app, ca = ca_app
    cert = sign_client_cert(ca, "alice")
    assert not is_revoked(cert, app.config["OTS_CA_FOLDER"])


def test_missing_crl_revokes_nothing(ca_app):
    app, ca = ca_app
    cert = sign_client_cert(ca, "alice")
    os.remove(os.path.join(app.config["OTS_CA_FOLDER"], "ca.crl"))
    assert not is_revoked(cert, app.config["OTS_CA_FOLDER"])


def test_revoked_certificate_is_in_signed_crl(ca_app):
    app, ca = ca_app
    revoked = sign_client_cert(ca, "alice")
    other_device = sign_client_cert(ca, "alice")
    revoke(revoked, "alice")
    ca.generate_crl()

    ca_folder = app.config["OTS_CA_FOLDER"]
    assert is_revoked(revoked, ca_folder)
    assert not is_revoked(other_device, ca_folder)

    with open(os.path.join(ca_folder, "ca.pem"), "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read())
    with open(os.path.join(ca_folder, "ca.crl"), "rb") as f:
        crl = x509.load_pem_x509_crl(f.read())
    assert crl.is_signature_valid(ca_cert.public_key())
    assert crl.issuer == ca_cert.subject


def test_crl_change_is_picked_up(ca_app):
    app, ca = ca_app
    ca_folder = app.config["OTS_CA_FOLDER"]
    first = sign_client_cert(ca, "alice")
    second = sign_client_cert(ca, "bob")

    revoke(first, "alice")
    ca.generate_crl()
    assert not is_revoked(second, ca_folder)

    revoke(second, "bob")
    ca.generate_crl()
    assert is_revoked(first, ca_folder)
    assert is_revoked(second, ca_folder)


def test_openssl_honours_generated_crl(ca_app, tmp_path):
    """nginx (ssl_crl) and other OpenSSL based tools must accept the CRL"""
    app, ca = ca_app
    ca_folder = app.config["OTS_CA_FOLDER"]
    revoked = sign_client_cert(ca, "alice")
    valid = sign_client_cert(ca, "bob")
    revoke(revoked, "alice")
    ca.generate_crl()

    def openssl_verify(cert: x509.Certificate):
        path = tmp_path / "cert.pem"
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return subprocess.run(
            [
                "openssl",
                "verify",
                "-crl_check",
                "-CAfile",
                os.path.join(ca_folder, "ca.pem"),
                "-CRLfile",
                os.path.join(ca_folder, "ca.crl"),
                str(path),
            ],
            capture_output=True,
            text=True,
        )

    assert openssl_verify(valid).returncode == 0
    result = openssl_verify(revoked)
    assert result.returncode != 0
    assert "revoked" in result.stdout + result.stderr
