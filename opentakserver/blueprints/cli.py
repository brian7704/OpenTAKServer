import os
import platform
import sys

import click
import yaml
from flask import g, current_app as app
from flask.cli import with_appcontext

from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.defaultconfig import DefaultConfig
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


@ots.command()
@click.option("--overwrite", is_flag=True)
@with_appcontext
def generate_config(overwrite):
    app.config.from_object(DefaultConfig)

    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")) and not overwrite:
        logger.warning("config.yml already exists")
        return

    logger.info("Creating config.yml")
    with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config:
        conf = {}
        for option in DefaultConfig.__dict__:
            # Fix the sqlite DB path on Windows
            if option == "SQLALCHEMY_DATABASE_URI" and platform.system() == "Windows" and DefaultConfig.__dict__[option].startswith("sqlite"):
                conf[option] = DefaultConfig.__dict__[option].replace("////", "///").replace("\\", "/")
            elif option.isupper():
                conf[option] = DefaultConfig.__dict__[option]
        config.write(yaml.safe_dump(conf))
