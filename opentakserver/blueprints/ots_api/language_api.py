from gettext import gettext

from flask import Blueprint, jsonify, session
from flask_security import auth_required

from opentakserver.extensions import babel, logger

language_api = Blueprint('language_api', __name__)


@language_api.route("/api/language/test")
@auth_required()
def test_lang():
    return jsonify({"success": True, "message": gettext("This is a test")})


@language_api.route('/api/language')
@auth_required()
def get_languages():
    langs = []
    for lang in babel.list_translations():
        langs.append({"code": lang.language, "name": lang.language_name})

    return jsonify(langs)


@language_api.route('/api/language/<lang_code>', methods=["PUT"])
@auth_required()
def set_language(lang_code):
    if not lang_code:
        session['language'] = 'en'

    else:
        lang_codes = []
        for translation in babel.list_translations():
            lang_codes.append(translation.language)

        if lang_code in lang_codes:
            session['language'] = lang_code
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": f"{lang_code} is not a supported language"}), 400
