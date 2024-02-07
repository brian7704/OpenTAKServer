import logging
import os

import colorlog
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from opentakserver.models.Base import Base
from jinja2 import Template
from flask_mail import Mail
from flask_apscheduler import APScheduler
from flask import current_app as app

from opentakserver.config import Config

logger = colorlog.getLogger('OpenTAKServer')

mail = Mail()

apscheduler = APScheduler()

db = SQLAlchemy(model_class=Base)

socketio = SocketIO(logger=logger, engineio_logger=None, async_mode='eventlet')

nginx_config_template = Template("""server {
        listen {{http_port}} default_server;
        listen [::]:{{http_port}} default_server;

        root /var/www/html;

        index index.html index.htm index.nginx-debian.html;

        server_name opentakserver_{{http_port}};

        location / {
                 proxy_pass http://127.0.0.1:8081;
                 proxy_http_version 1.1;
                 proxy_set_header Host $host;
                 proxy_set_header X-Forwarded-For $remote_addr;
        }

        location /socket.io {
                include proxy_params;
                proxy_http_version 1.1;
                proxy_buffering off;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection "Upgrade";
                proxy_set_header Host $host;
                proxy_set_header X-Forwarded-For $remote_addr;
                proxy_pass http://127.0.0.1:8081/socket.io;
        }
        
        try_files $uri /index.html;
        client_max_body_size 100M;
}

server {

        root /var/www/html;
        index index.html index.htm index.nginx-debian.html;
        server_name opentakserver_{{https_port}};

        location /Marti/api/tls {
                return 404;
        }

        location /Marti {
                if ($ssl_client_verify != SUCCESS) {
                        return 400;
                        break;
                }
                proxy_pass http://127.0.0.1:8081;
                proxy_http_version 1.1;
                proxy_set_header Host $host;
                proxy_set_header X-Forwarded-For $remote_addr;
        }


        location / {
                proxy_pass http://127.0.0.1:8081;
                proxy_http_version 1.1;
                proxy_set_header Host $host;
                proxy_set_header X-Forwarded-For $remote_addr;
        }

        location /socket.io {
                include proxy_params;
                proxy_http_version 1.1;
                proxy_buffering off;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection "Upgrade";
                proxy_set_header Host $host;
                proxy_set_header X-Forwarded-For $remote_addr;
                proxy_pass http://127.0.0.1:8081/socket.io;
        }
        
        try_files $uri /index.html;
        client_max_body_size 100M;


    # listen [::]:{{https_port}} ssl ipv6only=on;
    listen {{https_port}} ssl;
    ssl_certificate {{server_cert_file}};
    ssl_certificate_key {{server_key_file}};
    ssl_verify_client optional;
    ssl_client_certificate {{ca_cert}};
}


server {

    root /var/www/html;
    index index.html index.htm index.nginx-debian.html;

    server_name opentakserver_{{certificate_enrollment_port}};

    location /Marti/api/tls {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }

    # listen [::]:{{certificate_enrollment_port}} ssl ipv6only=on;
    listen {{certificate_enrollment_port}} ssl;
    ssl_certificate {{server_cert_file}};
    ssl_certificate_key {{server_key_file}};
    ssl_verify_client optional;
    ssl_client_certificate {{ca_cert}};
}""")
