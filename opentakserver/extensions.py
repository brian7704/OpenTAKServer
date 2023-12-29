import colorlog
from flask_sqlalchemy import SQLAlchemy
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

nginx_config_template = Template("""server {
        listen {{http_streaming_port}} default_server;
        listen [::]:{{http_streaming_port}} default_server;

        root /var/www/html;

        index index.html index.htm index.nginx-debian.html;

        server_name {{server_address}};

        location / {
                 proxy_pass http://127.0.0.1:8081;
                 proxy_http_version 1.1;
                 proxy_set_header Host $host;
        }

}

server {

        root /var/www/html;

        index index.html index.htm index.nginx-debian.html;

        server_name {{server_address}};


        location /Marti {
                if ($ssl_client_verify != SUCCESS) {
                        return 400;
                        break;
                }
                proxy_pass http://127.0.0.1:8081;
                proxy_http_version 1.1;
                proxy_set_header Host $host;
        }

        location / {
                proxy_pass http://127.0.0.1:8081;
                proxy_http_version 1.1;
                proxy_set_header Host $host;
        }


    listen {{https_streaming_port}} ssl;
    ssl_certificate {{server_cert}};
    ssl_certificate_key {{server_key}};
    ssl_verify_client optional;
    ssl_client_certificate  {{ca_cert}};
}


server {

    root /var/www/html;
    index index.html index.htm index.nginx-debian.html;

    server_name {{server_address}};

    location /Marti {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    listen {{certificate_enrollment_port}} ssl;
    ssl_certificate {{server_cert}};
    ssl_certificate_key {{server_key}};
    ssl_verify_client optional;
    ssl_client_certificate  {{ca_cert}};
}""")
