"""Creates LinkedIn carousel PDFs from slide data using reportlab."""

from __future__ import annotations

import logging
import tempfile

logger = logging.getLogger(__name__)

BG_DARK = (0.04, 0.40, 0.76)    # LinkedIn blue #0A66C2
BG_LIGHT = (0.97, 0.97, 0.97)
TEXT_DARK = (0.10, 0.10, 0.10)
TEXT_WHITE = (1.0, 1.0, 1.0)
ACCENT_YELLOW = (1.0, 0.75, 0.0)

SLIDE_SIZE = (540, 540)


def create_carousel_pdf(slides: list[dict], follow_name: str = "me") -> str:
    """Generate a carousel PDF; returns the temp file path."""
    try:
        from reportlab.pdfgen import canvas
    except ImportError as e:
        raise ImportError("reportlab not installed. Run: pip install reportlab") from e

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="carousel_")
    tmp.close()

    w, h = SLIDE_SIZE
    c = canvas.Canvas(tmp.name, pagesize=SLIDE_SIZE)
    for slide in slides:
        slide_type = slide.get("type", "content")
        title = slide.get("title", "")
        content = slide.get("content", "")
        if slide_type == "hook":
            _draw_hook(c, w, h, title, content)
        elif slide_type == "cta":
            _draw_cta(c, w, h, title, content, follow_name)
        else:
            _draw_content(c, w, h, title, content)
        c.showPage()
    c.save()

    logger.info("Carousel PDF created: %s (%d slides)", tmp.name, len(slides))
    return tmp.name


def _draw_hook(c, w, h, title, content):
    from reportlab.lib.utils import simpleSplit

    c.setFillColorRGB(*BG_DARK)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColorRGB(*ACCENT_YELLOW)
    c.rect(0, 0, w, 8, fill=1, stroke=0)

    c.setFillColorRGB(*TEXT_WHITE)
    c.setFont("Helvetica-Bold", 36)
    y = h - 160
    for line in simpleSplit(title, "Helvetica-Bold", 36, w - 80)[:4]:
        c.drawCentredString(w / 2, y, line)
        y -= 48

    if content:
        c.setFont("Helvetica", 20)
        c.setFillColorRGB(0.85, 0.90, 0.95)
        y -= 20
        for line in simpleSplit(content, "Helvetica", 20, w - 100)[:2]:
            c.drawCentredString(w / 2, y, line)
            y -= 28

    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica", 14)
    c.drawCentredString(w / 2, 30, "Swipe to read more")


def _draw_content(c, w, h, title, content):
    from reportlab.lib.utils import simpleSplit

    c.setFillColorRGB(*BG_LIGHT)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColorRGB(*BG_DARK)
    c.rect(0, h - 10, w, 10, fill=1, stroke=0)
    c.rect(0, 0, 6, h, fill=1, stroke=0)

    c.setFillColorRGB(*BG_DARK)
    c.setFont("Helvetica-Bold", 28)
    y = h - 80
    for line in simpleSplit(title, "Helvetica-Bold", 28, w - 80)[:2]:
        c.drawString(40, y, line)
        y -= 36

    c.setStrokeColorRGB(*BG_DARK)
    c.setLineWidth(2)
    c.line(40, y - 10, w - 40, y - 10)
    y -= 40

    c.setFont("Helvetica", 18)
    for bullet in [b.strip() for b in content.split("\n") if b.strip()][:5]:
        c.setFillColorRGB(*BG_DARK)
        c.circle(30, y + 6, 5, fill=1, stroke=0)
        c.setFillColorRGB(*TEXT_DARK)
        for bl in simpleSplit(bullet, "Helvetica", 18, w - 90)[:2]:
            c.drawString(50, y, bl)
            y -= 24
        y -= 8


def _draw_cta(c, w, h, title, content, follow_name):
    from reportlab.lib.utils import simpleSplit

    c.setFillColorRGB(*BG_DARK)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    c.setFillColorRGB(*ACCENT_YELLOW)
    c.circle(w / 2, h - 120, 35, fill=1, stroke=0)

    c.setFillColorRGB(*TEXT_WHITE)
    c.setFont("Helvetica-Bold", 26)
    y = h - 210
    for line in simpleSplit(title, "Helvetica-Bold", 26, w - 80)[:3]:
        c.drawCentredString(w / 2, y, line)
        y -= 34

    if content:
        c.setFont("Helvetica", 17)
        c.setFillColorRGB(0.85, 0.90, 0.95)
        y -= 20
        for line in simpleSplit(content, "Helvetica", 17, w - 100)[:4]:
            c.drawCentredString(w / 2, y, line)
            y -= 24

    c.setFillColorRGB(*ACCENT_YELLOW)
    c.rect(60, 40, w - 120, 50, fill=1, stroke=0)
    c.setFillColorRGB(0.05, 0.05, 0.05)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(w / 2, 60, f"Follow {follow_name} for weekly insights")
