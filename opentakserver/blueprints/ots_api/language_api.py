from flask import Blueprint
from flask import current_app as app
from flask import jsonify, session
from flask_babel import gettext

from opentakserver.extensions import babel

language_api = Blueprint("language_api", __name__)


@language_api.route("/api/language/test")
def test_lang():
    return jsonify({"success": True, "message": gettext("This is a test")})


@language_api.route("/api/language")
def get_languages():
    return jsonify(app.config.get("OTS_LANGUAGES"))


@language_api.route("/api/language/<lang_code>", methods=["PUT"])
def set_language(lang_code):
    if not lang_code:
        session["language"] = "en"

    else:
        lang_codes = []
        for translation in babel.list_translations():
            lang_codes.append(translation.language)

        if lang_code in lang_codes:
            session["language"] = lang_code
            return jsonify({"success": True})
        else:
            return (
                jsonify(
                    {"success": False, "error": gettext(f"{lang_code} is not a supported language")}
                ),
                400,
            )
