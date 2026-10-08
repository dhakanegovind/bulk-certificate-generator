"""The ONE predefined certificate template, drawn as a PDF with ReportLab.

`render_certificate()` is the only function the rest of the app needs. It is intentionally
independent of Flask and the database: give it data, get a PDF file. That makes it easy to
test and easy to swap for a different template/library later.
"""
import os
import threading
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)  # 842 x 595 points

NAVY = colors.HexColor("#1f2a44")
GOLD = colors.HexColor("#b8934a")
GREY = colors.HexColor("#555555")

CUSTOM_FONT_NAME = "CertificateFont"
_font_lock = threading.Lock()


class CertificateError(Exception):
    """A problem with one specific certificate (its message is shown to the API client)."""


class UnsupportedCharactersError(CertificateError):
    pass


class TextTooLongError(CertificateError):
    pass


def is_renderable(text, font_path=None):
    """Can `text` be drawn with the configured font?

    ReportLab's built-in fonts only cover Western (cp1252) characters. For anything else it
    does NOT raise - it silently draws wrong glyphs - so we check explicitly.
    With a custom TTF font we trust the font and skip the check.
    """
    if font_path:
        return True
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def _ensure_renderable(label, text, font_path):
    bad = sorted({ch for ch in text if not is_renderable(ch, font_path)})
    if bad:
        shown = " ".join(bad[:5])
        raise UnsupportedCharactersError(
            f"{label} contains characters the certificate font cannot render ({shown}). "
            "Configure CERTIFICATE_FONT_PATH with a font that supports them."
        )


def _select_fonts(font_path):
    """Return the font names for each text role (registers the custom font once)."""
    if not font_path:
        return {"title": "Times-Bold", "body": "Helvetica", "name": "Times-BoldItalic",
                "strong": "Helvetica-Bold"}
    with _font_lock:  # ReportLab's font registry is global, so guard registration
        if CUSTOM_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(CUSTOM_FONT_NAME, font_path))
    return {role: CUSTOM_FONT_NAME for role in ("title", "body", "name", "strong")}


def _fit_font_size(text, font, max_size, max_width, min_size=10):
    """Largest font size (<= max_size) at which `text` fits in `max_width`."""
    size = max_size
    while size > min_size and pdfmetrics.stringWidth(text, font, size) > max_width:
        size -= 1
    if pdfmetrics.stringWidth(text, font, size) > max_width:
        raise TextTooLongError(f"Text is too long to fit on the certificate: {text[:30]!r}...")
    return size


def _draw(path, fonts, data):
    c = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"{data['title']} - {data['recipient_name']}")
    c.setAuthor(data["issued_by"])
    cx = PAGE_WIDTH / 2
    content_width = PAGE_WIDTH - 200

    # Double border: thick navy outside, thin gold inside.
    c.setStrokeColor(NAVY)
    c.setLineWidth(6)
    c.rect(20, 20, PAGE_WIDTH - 40, PAGE_HEIGHT - 40)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.rect(34, 34, PAGE_WIDTH - 68, PAGE_HEIGHT - 68)

    # Title
    c.setFillColor(NAVY)
    size = _fit_font_size(data["title"], fonts["title"], 40, content_width, min_size=18)
    c.setFont(fonts["title"], size)
    c.drawCentredString(cx, 450, data["title"])

    # "This is to certify that"
    c.setFillColor(GREY)
    c.setFont(fonts["body"], 15)
    c.drawCentredString(cx, 395, "This is to certify that")

    # Recipient name (the star of the show) + gold underline
    c.setFillColor(NAVY)
    name = data["recipient_name"]
    size = _fit_font_size(name, fonts["name"], 44, content_width)
    c.setFont(fonts["name"], size)
    c.drawCentredString(cx, 335, name)
    half = min(pdfmetrics.stringWidth(name, fonts["name"], size) / 2 + 30, content_width / 2)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(cx - half, 322, cx + half, 322)

    # "has successfully completed" + event name (wrapped over up to 3 lines)
    c.setFillColor(GREY)
    c.setFont(fonts["body"], 15)
    c.drawCentredString(cx, 290, "has successfully completed")
    c.setFillColor(NAVY)
    c.setFont(fonts["strong"], 22)
    lines = simpleSplit(data["event_name"], fonts["strong"], 22, content_width)
    if len(lines) > 3:
        raise TextTooLongError("Event name is too long to fit on the certificate.")
    y = 252
    for line in lines:
        c.drawCentredString(cx, y, line)
        y -= 28

    # Footer: date (left) and issuer (right), each above a label and under a signature line.
    issue_date = date.fromisoformat(data["issue_date"]).strftime("%d %B %Y")
    c.setStrokeColor(GREY)
    c.setLineWidth(0.8)
    c.line(110, 118, 300, 118)
    c.line(PAGE_WIDTH - 300, 118, PAGE_WIDTH - 110, 118)
    c.setFillColor(NAVY)
    c.setFont(fonts["body"], 13)
    c.drawCentredString(205, 124, issue_date)
    issuer_size = _fit_font_size(data["issued_by"], fonts["body"], 13, 190, min_size=8)
    c.setFont(fonts["body"], issuer_size)
    c.drawCentredString(PAGE_WIDTH - 205, 124, data["issued_by"])
    c.setFillColor(GREY)
    c.setFont(fonts["body"], 10)
    c.drawCentredString(205, 102, "Date")
    c.drawCentredString(PAGE_WIDTH - 205, 102, "Issued by")

    # Certificate ID (lets someone verify/track a certificate later)
    c.setFont(fonts["body"], 8)
    c.drawCentredString(cx, 55, f"Certificate ID: {data['certificate_id']}")

    c.showPage()
    c.save()


def render_certificate(output_path, *, recipient_name, title, event_name, issued_by,
                       issue_date, certificate_id, font_path=None):
    """Create the certificate PDF at `output_path`.

    The file is written to a temporary name and renamed at the end, so a crash half-way
    through never leaves a corrupt PDF that looks like a finished one.
    Raises CertificateError (or a subclass) for problems with this certificate's data.
    """
    data = {
        "recipient_name": recipient_name, "title": title, "event_name": event_name,
        "issued_by": issued_by, "issue_date": issue_date, "certificate_id": certificate_id,
    }
    for label, key in (("Recipient name", "recipient_name"), ("Title", "title"),
                       ("Event name", "event_name"), ("Issuer", "issued_by")):
        _ensure_renderable(label, data[key], font_path)

    fonts = _select_fonts(font_path)
    output_path = Path(output_path)
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        _draw(tmp_path, fonts, data)
        os.replace(tmp_path, output_path)  # atomic on the same filesystem
    finally:
        if tmp_path.exists():  # only true if drawing failed
            tmp_path.unlink()
