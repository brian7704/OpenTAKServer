import colorlog
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from models.Base import Base
from jinja2 import Template

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s[%(asctime)s] - %(levelname)s - %(name)s - %(message)s', datefmt="%Y-%m-%d %H:%M:%S"))

logger = colorlog.getLogger('OpenTAKServer')
logger.setLevel('DEBUG')
if not logger.hasHandlers():
    logger.addHandler(handler)

db = SQLAlchemy(model_class=Base)

socketio = SocketIO(logger=logger, engineio_logger=logger)

nginx_config_template = Template("""server {
        listen {{http_streaming_port}} default_server;
        listen [::]:{{http_streaming_port}} default_server;

        root /var/www/html;

        index index.html index.htm index.nginx-debian.html;

        server_name opentakserver_8080;

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

}

server {

        root /var/www/html;

        index index.html index.htm index.nginx-debian.html;

        server_name opentakserver_8443;

        location /Marti/api/tls {
                return 404;
        }

        location /Marti {
                if ($ssl_client_verify != SUCCESS) {
                        return 400;
                        break;
                }
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


    # listen [::]:8443 ssl ipv6only=on;
    listen 8443 ssl;
    ssl_certificate /root/ots/ca/certs/serotina.io/serotina.io.pem;
    ssl_certificate_key /root/ots/ca/certs/serotina.io/serotina.io.nopass.key;
    ssl_verify_client optional;
    ssl_client_certificate  /root/ots/ca/ca.pem;
}


server {

    root /var/www/html;
    index index.html index.htm index.nginx-debian.html;

    server_name opentakserver_8446;

    location /Marti/api/tls {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }

    # listen [::]:8446 ssl ipv6only=on;
    listen 8446 ssl;
    ssl_certificate {{server_cert_file}};
    ssl_certificate_key {{server_key_file}};
    ssl_verify_client optional;
    ssl_client_certificate {{ca_cert}};
}""")
