import sys

import click
from flask import g, current_app as app
from flask.cli import with_appcontext

from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.extensions import logger


@click.group()
@click.option('-x', '--x-arg', multiple=True,
              help='Additional arguments consumed by custom env.py scripts')
@with_appcontext
def ots(x_arg):
    g.x_arg = x_arg


@ots.command()
@with_appcontext
def create_ca():
    ca = CertificateAuthority(logger, app)
    if not ca.check_if_ca_exists():
        logger.info("Creating certificate authority...")
        ca.create_ca()
    else:
        logger.warning("Certificate authority already exists")
    sys.exit()
