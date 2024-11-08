import json
import re
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import current_app as app
import pika.channel

ISO8601_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
ISO8601_FORMAT_NO_MICROSECONDS = "%Y-%m-%dT%H:%M:%SZ"
affiliations = ['friendly', 'hostile', 'unknown', 'pending', 'assumed', 'neutral', 'suspect', 'joker', 'faker']

# For WTForms BooleanField, the default doesn't include 'False'
# https://wtforms.readthedocs.io/en/3.1.x/fields/?highlight=false_values#wtforms.fields.BooleanField
false_values = (False, 'False', 'false', '')


def get_tasking(cot_type):
    if re.match("^t-x-f", cot_type):
        return "remarks"
    if re.match("^t-x-s", cot_type):
        return "state/sync"
    if re.match("^t-s", cot_type):
        return "required"
    if re.match("^t-z", cot_type):
        return "cancel"
    if re.match("^t-x-c-c", cot_type):
        return "commcheck"
    if re.match("^t-x-c-g-d", cot_type):
        return "dgps"
    if re.match("^t-k-d", cot_type):
        return "destroy"
    if re.match("^t-k-i", cot_type):
        return "investigate"
    if re.match("^t-k-t", cot_type):
        return "target"
    if re.match("^t-k", cot_type):
        return "strike"
    if re.match("^t-", cot_type):
        return "tasking"
    return None


def get_affiliation(cot_type):
    if re.match("^t-", cot_type):
        return get_tasking(cot_type)
    if re.match("^a-f-", cot_type):
        return "friendly"
    if re.match("^a-h-", cot_type):
        return "hostile"
    if re.match("^a-u-", cot_type):
        return "unknown"
    if re.match("^a-p-", cot_type):
        return "pending"
    if re.match("^a-a-", cot_type):
        return "assumed"
    if re.match("^a-n-", cot_type):
        return "neutral"
    if re.match("^a-s-", cot_type):
        return "suspect"
    if re.match("^a-j-", cot_type):
        return "joker"
    if re.match("^a-k-", cot_type):
        return "faker"
    return None


def get_battle_dimension(cot_type):
    if re.match("^a-.-A", cot_type):
        return "airborne"
    if re.match("^a-.-G", cot_type):
        return "ground"
    if re.match("^a-.-G-I", cot_type):
        return "installation"
    if re.match("^a-.-S", cot_type):
        return "surface/sea"
    if re.match("^a-.-U", cot_type):
        return "subsurface"
    return None


def parse_type(cot_type):
    if re.match("^a-.-G-I", cot_type):
        return "installation"
    if re.match("^a-.-G-E-V", cot_type):
        return "vehicle"
    if re.match("^a-.-G-E", cot_type):
        return "equipment"
    if re.match("^a-.-A-W-M-S", cot_type):
        return "sam"
    if re.match("^a-.-A-M-F-Q-r", cot_type):
        return "uav"


def cot_type_to_2525c(cot_type):
    mil_std_2525c = "s"
    cot_type_list = cot_type.split("-")
    cot_type_list.pop(0)  # this should always be letter a
    affiliation = cot_type_list.pop(0)
    battle_dimension = cot_type_list.pop(0)
    mil_std_2525c += affiliation
    mil_std_2525c += battle_dimension
    mil_std_2525c += "-"

    for letter in cot_type_list:
        if letter.isupper():
            mil_std_2525c += letter.lower()

    while len(mil_std_2525c) < 10:
        mil_std_2525c += "-"

    return mil_std_2525c


def datetime_from_iso8601_string(datetime_string):
    if not datetime_string:
        return datetime.now()
    try:
        return datetime.strptime(datetime_string, ISO8601_FORMAT)
    except ValueError:
        return datetime.strptime(datetime_string, ISO8601_FORMAT_NO_MICROSECONDS)


def iso8601_string_from_datetime(datetime_object):
    if datetime_object:
        return datetime_object.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-2] + "Z"
    else:
        return None


def iso8601_string_from_datetime_no_ms(datetime_object):
    if datetime_object:
        return datetime_object.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        return None


def generate_delete_cot(uid: str, cot_type: str) -> Element:
    now = datetime.now()

    event = Element('event', {'how': 'h-g-i-g-o', 'type': 't-x-d-d', 'version': '2.0',
                              'uid': uid, 'start': iso8601_string_from_datetime(now),
                              'time': iso8601_string_from_datetime(now),
                              'stale': iso8601_string_from_datetime(now)})
    SubElement(event, 'point', {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0',
                                'lon': '0'})
    detail = SubElement(event, 'detail')
    SubElement(detail, 'link', {'relation': 'p-p', 'uid': uid, 'type': cot_type})
    SubElement(detail, '_flow-tags_',
               {'TAK-Server-f1a8159ef7804f7a8a32d8efc4b773d0': iso8601_string_from_datetime(now)})

    return event


def publish_cot(cot: Element, channel: pika.channel.Channel):
    channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
        {'cot': tostring(cot).decode('utf-8'), 'uid': app.config['OTS_NODE_ID']}),
                          properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
