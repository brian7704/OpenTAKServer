from flask import current_app as app


class Fields:
    def fields(self):

        field_filter = [
            "Meta",
            "_wtforms_meta",
            "fields",
            "csrf_token",
            "hidden_tag",
            "is_submitted",
            "populate_obj",
            "process",
            "validate",
            "validate_on_submit",
        ]

        return_value = []

        for a in dir(self):
            if not a.startswith("__") and callable(getattr(self, a)) and a not in field_filter:
                field = getattr(self, a)
                try:
                    print(f"{field.label.text} - {app.config.get(field.label.text)}")
                    return_value.append(
                        {
                            "label": field.label.text,
                            "name": a,
                            "type": field.type,
                            "description": field.description,
                            "required": field.flags.required,
                            "disabled": field.flags.disabled or field.flags.readonly,
                            "min": field.flags.min,
                            "max": field.flags.max,
                            "data": app.config.get(field.label.text),
                        }
                    )
                except AttributeError:
                    continue

        return return_value
