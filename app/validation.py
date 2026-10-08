"""Input validation. Pure functions with no Flask/DB imports, so they are trivial to unit test.

Two levels of validation, on purpose:

1. REQUEST level  - the request as a whole is unusable (missing event name, no recipients,
   too many recipients...). We reject it with HTTP 400 and create nothing.
2. RECIPIENT level - one recipient has bad data (bad email, empty name...). We do NOT reject
   the request; that recipient is recorded as a failed certificate with a reason and
   every valid recipient is still processed.
"""
import re
import unicodedata
from datetime import datetime, timezone

DEFAULT_TITLE = "Certificate of Completion"

# Deliberately simple: something@something.tld, no spaces. Full RFC 5322 validation is
# overkill here (the only real proof an address works is sending mail to it).
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_NAME_LEN = 100
MAX_EMAIL_LEN = 254  # the practical maximum length of an email address


class ValidationError(Exception):
    """Raised when the whole request is invalid. `details` is a list of {field, message}."""

    def __init__(self, details):
        super().__init__("Invalid request")
        self.details = details


def _has_control_chars(text):
    # Unicode category "C*" = control/format characters (newlines, tabs, zero-width, ...)
    return any(unicodedata.category(ch).startswith("C") for ch in text)


def _clean_text(value, field, max_len, errors, default=None, is_renderable=None):
    """Validate one string field of the job. Returns the cleaned value (or None on error)."""
    if value is None:
        if default is not None:
            return default
        errors.append({"field": field, "message": "This field is required."})
        return None
    if not isinstance(value, str):
        errors.append({"field": field, "message": "Must be a string."})
        return None
    value = value.strip()
    if not value:
        errors.append({"field": field, "message": "Must not be empty."})
        return None
    if len(value) > max_len:
        errors.append({"field": field, "message": f"Must be at most {max_len} characters."})
        return None
    if _has_control_chars(value):
        errors.append({"field": field, "message": "Must not contain control characters."})
        return None
    if is_renderable is not None and not is_renderable(value):
        errors.append({
            "field": field,
            "message": "Contains characters the certificate font cannot render.",
        })
        return None
    return value


def validate_job_request(payload, max_recipients, is_renderable=None):
    """Validate the top-level request. Returns (job_fields, raw_recipients) or raises ValidationError.

    Recipients are returned RAW (not validated here) - see module docstring, level 2.
    """
    if not isinstance(payload, dict):
        raise ValidationError([{"field": "body", "message": "Request body must be a JSON object."}])

    errors = []
    job = {
        "event_name": _clean_text(payload.get("event_name"), "event_name", 120, errors,
                                  is_renderable=is_renderable),
        "issued_by": _clean_text(payload.get("issued_by"), "issued_by", 80, errors,
                                 is_renderable=is_renderable),
        "title": _clean_text(payload.get("title"), "title", 80, errors,
                             default=DEFAULT_TITLE, is_renderable=is_renderable),
    }

    # issue_date: optional, strict YYYY-MM-DD, defaults to today (UTC).
    raw_date = payload.get("issue_date")
    if raw_date is None:
        job["issue_date"] = datetime.now(timezone.utc).date().isoformat()
    else:
        try:
            if not isinstance(raw_date, str):
                raise ValueError
            job["issue_date"] = datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()
        except ValueError:
            errors.append({"field": "issue_date", "message": "Must be a date formatted YYYY-MM-DD."})

    recipients = payload.get("recipients")
    if not isinstance(recipients, list):
        errors.append({"field": "recipients", "message": "Must be a list of recipient objects."})
    elif len(recipients) == 0:
        errors.append({"field": "recipients", "message": "Must contain at least one recipient."})
    elif len(recipients) > max_recipients:
        errors.append({
            "field": "recipients",
            "message": f"Too many recipients ({len(recipients)}). Maximum per request is {max_recipients}.",
        })

    if errors:
        raise ValidationError(errors)
    return job, recipients


def validate_recipient(raw):
    """Validate ONE recipient. Returns (clean_dict, None) if valid, else (None, error_message).

    All problems are collected so the client can fix everything in one go.
    """
    if not isinstance(raw, dict):
        return None, "Recipient must be an object with 'name' and 'email'."

    problems = []

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("name is required and must be a non-empty string")
        name = None
    else:
        name = name.strip()
        if len(name) > MAX_NAME_LEN:
            problems.append(f"name must be at most {MAX_NAME_LEN} characters")
        elif _has_control_chars(name):
            problems.append("name must not contain control characters")

    email = raw.get("email")
    if not isinstance(email, str) or not email.strip():
        problems.append("email is required and must be a non-empty string")
        email = None
    else:
        email = email.strip().lower()
        if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
            problems.append("email is not a valid email address")

    if problems:
        return None, "Invalid recipient: " + "; ".join(problems) + "."
    return {"name": name, "email": email}, None
