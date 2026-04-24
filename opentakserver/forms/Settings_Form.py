from flask_babel import gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, IntegerField, FloatField
from wtforms.validators import Optional, InputRequired, NumberRange, IPAddress, URL

from opentakserver.forms.Fields import Fields
from opentakserver.functions import false_values


class SettingsForm(FlaskForm, Fields):
    debug = BooleanField(false_values=false_values, validators=[Optional()], label="DEBUG")
    ots_data_folder = StringField(validators=[Optional()], label="OTS_DATA_FOLDER")
    ots_listener_address = StringField(
        validators=[Optional(), IPAddress()], label="OTS_LISTENER_ADDRESS", default="127.0.0.1"
    )
    ots_listener_port = IntegerField(
        validators=[Optional(), NumberRange(min=1, max=65535)],
        label="OTS_LISTENER_PORT",
        default=8081,
    )
    ots_enable_tcp_streaming_port = BooleanField(
        false_values=false_values, validators=[Optional()], label="OTS_ENABLE_TCP_STREAMING_PORT"
    )
    ots_tcp_streaming_port = IntegerField(
        validators=[Optional(), NumberRange(min=1, max=65535)],
        label="OTS_TCP_STREAMING_PORT",
        default=8088,
    )
    ots_ssl_streaming_port = IntegerField(
        validators=[Optional(), NumberRange(min=1, max=65535)],
        label="OTS_SSL_STREAMING_PORT",
        default=8089,
    )
    ots_backup_count = IntegerField(
        validators=[Optional(), NumberRange(min=1)], label="OTS_BACKUP_COUNT"
    )
    ots_enable_channels = BooleanField(
        false_values=false_values, validators=[Optional()], label="OTS_ENABLE_CHANNELS"
    )
    ots_rabbitmq_server_address = StringField(
        validators=[Optional(), IPAddress()],
        default="127.0.0.1",
        label="OTS_RABBITMQ_SERVER_ADDRESS",
    )
    ots_rabbitmq_username = StringField(
        validators=[Optional()], default="guest", label="OTS_RABBITMQ_USERNAME"
    )
    ots_rabbitmq_password = StringField(
        validators=[Optional()], default="guest", label="OTS_RABBITMQ_PASSWORD"
    )
    ots_rabbitmq_ttl = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=86400000, label="OTS_RABBITMQ_TTL"
    )
    ots_rabbitmq_prefetch = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=2, label="OTS_RABBITMQ_PREFETCH"
    )
    ots_mediamtx_api_address = StringField(
        validators=[Optional()],
        default="http://localhost:9997",
        label="OTS_MEDIAMTX_API_ADDRESS",
    )
    ots_ssl_cert_header = StringField(
        validators=[Optional()], default="X-Ssl-Cert", label="OTS_SSL_CERT_HEADER"
    )
    ots_ca_name = StringField(
        validators=[Optional()], default="OpenTAKServer-CA", label="OTS_CA_NAME"
    )
    ots_ca_password = StringField(validators=[Optional()], label="OTS_CA_PASSWORD")
    ots_ca_expiration_time = IntegerField(
        validators=[Optional()], default=3650, label="OTS_CA_EXPIRATION_TIME"
    )
    ots_ca_country = StringField(validators=[Optional()], default="WW", label="OTS_CA_COUNTRY")
    ots_ca_state = StringField(validators=[Optional()], default="XX", label="OTS_CA_STATE")
    ots_ca_city = StringField(validators=[Optional()], default="YY", label="OTS_CA_CITY")
    ots_ca_organization = StringField(
        validators=[Optional()], default="ZZ", label="OTS_CA_ORGANIZATION"
    )
    ots_ca_organizational_unit = StringField(
        validators=[Optional()], default="OpenTAKServer", label="OTS_CA_ORGANIZATIONAL_UNIT"
    )
    ots_ca_subject = StringField(validators=[Optional()], label="OTS_CA_SUBJECT")
    ots_cot_parser_processes = IntegerField(
        validators=[Optional(), NumberRange(min=1)], default=1, label="OTS_COT_PARSER_PROCESSES"
    )
    ots_enable_ldap = BooleanField(
        validators=[Optional()], false_values=false_values, label="OTS_ENABLE_LDAP"
    )
    ots_ldap_admin_group = StringField(
        validators=[Optional()], default="ots_admin", label="OTS_LDAP_ADMIN_GROUP"
    )
    ots_ldap_color_attribute = StringField(
        validators=[Optional()], default="colorAttribute", label="OTS_LDAP_COLOR_ATTRIBUTE"
    )
    ots_ldap_role_attribute = StringField(
        validators=[Optional()], default="roleAttribute", label="OTS_LDAP_ROLE_ATTRIBUTE"
    )
    ots_ldap_callsign_attribute = StringField(
        validators=[Optional()], default="callsignAttribute", label="OTS_LDAP_CALLSIGN_ATTRIBUTE"
    )
    ots_ldap_preference_attribute_prefix = StringField(
        validators=[Optional()], default="ots_", label="OTS_LDAP_PREFERENCE_ATTRIBUTE_PREFIX"
    )
    ots_ldap_group_prefix = StringField(
        validators=[Optional()], default="ots_", label="OTS_LDAP_GROUP_PREFIX"
    )
    ldap_host = StringField(validators=[Optional()], default="127.0.0.1", label="LDAP_HOST")
    ldap_base_dn = StringField(validators=[Optional()], default="", label="LDAP_BASE_DN")
    ldap_user_dn = StringField(validators=[Optional()], default="", label="LDAP_USER_DN")
    ldap_bind_user_dn = StringField(
        validators=[Optional()],
        default="cn=admin,ou=users=dc=example,dc=com",
        label="LDAP_BIND_USER_DN",
    )
    ldap_bind_user_password = StringField(
        validators=[Optional()], default="password", label="LDAP_BIND_USER_PASSWORD"
    )
    ots_log_rotate_when = StringField(
        validators=[Optional()], default="midnight", label="OTS_LOG_ROTATE_WHEN"
    )
    ots_log_rotate_interval = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=0, label="OTS_LOG_ROTATE_INTERVAL"
    )
    ots_adsb_lat = FloatField(
        validators=[Optional(), NumberRange(min=-90, max=90)],
        default=40.744213,
        label="OTS_ADSB_LAT",
    )
    ots_adsb_lon = FloatField(
        validators=[Optional(), NumberRange(min=-180, max=180)],
        default=-73.986939,
        label="OTS_ADSB_LON",
    )
    ots_adsb_radius = IntegerField(
        validators=[Optional(), NumberRange(min=1, max=250)], default=10, label="OTS_ADSB_RADIUS"
    )
    ots_adsb_api_url = StringField(
        validators=[Optional(), URL()],
        default="https://api.airplanes.live/v2/point/",
        label="OTS_ADSB_API_URL",
    )
    ots_adsb_api_key = StringField(validators=[Optional()], default=None, label="OTS_ADSB_API_KEY")
    ots_adsb_group = StringField(validators=[Optional()], default="ADS-B", label="OTS_ADSB_GROUP")
    ots_ais_group = StringField(validators=[Optional()], default="AIS", label="OTS_AIS_GROUP")
    ots_plugin_repo = StringField(
        validators=[Optional(), URL()],
        default="https://repo.opentakserver.io/brian/prod/",
        label="OTS_PLUGIN_REPO",
    )
    ots_aishub_username = StringField(validators=[Optional()], label="OTS_AISHUB_USERNAME")
    ots_aishub_south_lat = FloatField(
        validators=[Optional(), NumberRange(min=-90, max=90)],
        label="OTS_AISHUB_SOUTH_LAT",
    )
    ots_aishub_west_lon = FloatField(
        validators=[Optional(), NumberRange(min=-180, max=180)],
        label="OTS_AISHUB_WEST_LON",
    )
    ots_aishub_north_lat = FloatField(
        validators=[Optional(), NumberRange(min=-90, max=90)],
        label="OTS_AISHUB_NORTH_LAT",
    )
    ots_aishub_east_lon = FloatField(
        validators=[Optional(), NumberRange(min=-180, max=180)],
        label="OTS_AISHUB_EAST_LON",
    )
    ots_aishub_mmsi_list = StringField(
        validators=[Optional()], default=None, label="OTS_AISHUB_MMSI_LIST"
    )
    ots_aishub_imo_list = StringField(
        validators=[Optional()], default=None, label="OTS_AISHUB_IMO_LIST"
    )
    ots_enable_mumble_authentication = BooleanField(
        validators=[Optional()], false_values=false_values, label="OTS_ENABLE_MUMBLE_AUTHENTICATION"
    )
    ots_enable_meshtastic = BooleanField(
        validators=[Optional()], false_values=false_values, label="OTS_ENABLE_MESHTASTIC"
    )
    ots_meshtastic_topic = StringField(
        validators=[Optional()], default="opentakserver", label="OTS_MESHTASTIC_TOPIC"
    )
    ots_meshtastic_publish_interval = IntegerField(
        validators=[Optional(), NumberRange(min=0)],
        default=30,
        label="OTS_MESHTASTIC_PUBLISH_INTERVAL",
    )
    ots_meshtastic_nodeinfo_interval = IntegerField(
        validators=[Optional(), NumberRange(min=0)],
        default=3,
        label="OTS_MESHTASTIC_NODEINFO_INTERVAL",
    )
    ots_meshtastic_group = StringField(
        validators=[Optional()], default="Meshtastic", label="OTS_MESHTASTIC_GROUP"
    )
    ots_enable_email = BooleanField(
        validators=[Optional()], false_values=false_values, label="OTS_ENABLE_EMAIL"
    )
    mail_server = StringField(
        validators=[Optional()], default="smtp.gmail.com", label="MAIL_SERVER"
    )
    mail_port = IntegerField(
        validators=[Optional(), NumberRange(min=1, max=65535)], default=587, label="MAIL_PORT"
    )
    mail_use_ssl = BooleanField(
        validators=[Optional()], false_values=false_values, label="MAIL_USE_SSL"
    )
    mail_use_tls = BooleanField(
        validators=[Optional()], false_values=false_values, label="MAIL_USE_TLS"
    )
    mail_username = StringField(validators=[Optional()], default=None, label="MAIL_USERNAME")
    mail_password = StringField(validators=[Optional()], default=None, label="MAIL_PASSWORD")
    mail_debug = BooleanField(
        validators=[Optional()], false_values=false_values, label="MAIL_DEBUG"
    )
    ots_delete_old_data_seconds = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=0, label="OTS_DELETE_OLD_DATA_SECONDS"
    )
    ots_delete_old_data_minutes = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=0, label="OTS_DELETE_OLD_DATA_MINUTES"
    )
    ots_delete_old_data_hours = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=0, label="OTS_DELETE_OLD_DATA_HOURS"
    )
    ots_delete_old_data_days = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=0, label="OTS_DELETE_OLD_DATA_DAYS"
    )
    ots_delete_old_data_weeks = IntegerField(
        validators=[Optional(), NumberRange(min=0)], default=1, label="OTS_DELETE_OLD_DATA_WEEKS"
    )
    sqlalchemy_echo = BooleanField(
        validators=[Optional()], false_values=false_values, label="SQLALCHEMY_ECHO"
    )
    sqlalchemy_track_modifications = BooleanField(
        validators=[Optional()], false_values=false_values, label="SQLALCHEMY_TRACK_MODIFICATIONS"
    )
    sqlalchemy_record_queries = BooleanField(
        validators=[Optional()], false_values=false_values, label="SQLALCHEMY_RECORD_QUERIES"
    )
