from datetime import datetime

ISO8601_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
ISO8601_FORMAT_NO_MICROSECONDS = "%Y-%m-%dT%H:%M:%SZ"


def datetime_from_iso8601_string(datetime_string):
    try:
        return datetime.strptime(datetime_string, ISO8601_FORMAT)
    except ValueError:
        return datetime.strptime(datetime_string, ISO8601_FORMAT_NO_MICROSECONDS)


def iso8601_string_from_datetime(datetime_object):
    return datetime_object.strftime("%Y-%m-%dT%H:%M:%S.%f"[:-3] + "Z")
