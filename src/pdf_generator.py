"""
pdf_generator.py — Creates LinkedIn carousel PDFs from slide data.
Uses reportlab to generate clean, professional slides.
"""

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# LinkedIn carousel colors
BG_DARK = (0.04, 0.40, 0.76)    # LinkedIn blue #0A66C2
BG_LIGHT = (0.97, 0.97, 0.97)   # Near-white
TEXT_DARK = (0.10, 0.10, 0.10)
TEXT_WHITE = (1.0, 1.0, 1.0)
ACCENT = (0.04, 0.40, 0.76)

SLIDE_SIZE = (540, 540)  # 540x540 pts = ~7.5x7.5 inches (square)


def create_carousel_pdf(slides: list[dict]) -> str:
    """
    Generate a PDF carousel from slide data.
    Returns path to temp PDF file.
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import simpleSplit
    except ImportError:
        raise ImportError("reportlab not installed. Run: pip install reportlab")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="carousel_")
    tmp.close()
    pdf_path = tmp.name

    W, H = SLIDE_SIZE
    c = canvas.Canvas(pdf_path, pagesize=SLIDE_SIZE)

    for slide in slides:
        slide_type = slide.get("type", "content")
        title = slide.get("title", "")
        content = slide.get("content", "")

        if slide_type == "hook":
            _draw_hook_slide(c, W, H, title, content)
        elif slide_type == "cta":
            _draw_cta_slide(c, W, H, title, content)
        else:
            _draw_content_slide(c, W, H, title, content)

        c.showPage()

    c.save()
    logger.info(f"Carousel PDF created: {pdf_path} ({len(slides)} slides)")
    return pdf_path


def _draw_hook_slide(c, W, H, title, content):
    """Slide 1 — dark background, big bold title."""
    from reportlab.lib.utils import simpleSplit

    # Dark background
    c.setFillColorRGB(*BG_DARK)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Accent bar at bottom
    c.setFillColorRGB(1.0, 0.75, 0.0)  # yellow accent
    c.rect(0, 0, W, 8, fill=1, stroke=0)

    # Title
    c.setFillColorRGB(*TEXT_WHITE)
    c.setFont("Helvetica-Bold", 36)
    lines = simpleSplit(title, "Helvetica-Bold", 36, W - 80)
    y = H - 160
    for line in lines[:4]:
        c.drawCentredString(W / 2, y, line)
        y -= 48

    # Content / teaser
    if content:
        c.setFont("Helvetica", 20)
        c.setFillColorRGB(0.85, 0.90, 0.95)
        lines2 = simpleSplit(content, "Helvetica", 20, W - 100)
        y -= 20
        for line in lines2[:2]:
            c.drawCentredString(W / 2, y, line)
            y -= 28

    # Swipe indicator
    c.setFillColorRGB(1, 1, 1, 0.5)
    c.setFont("Helvetica", 14)
    c.drawCentredString(W / 2, 30, "Swipe → to read more")


def _draw_content_slide(c, W, H, title, content):
    """Content slides — white background, title + bullets."""
    from reportlab.lib.utils import simpleSplit

    # White background
    c.setFillColorRGB(*BG_LIGHT)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Top color bar
    c.setFillColorRGB(*BG_DARK)
    c.rect(0, H - 10, W, 10, fill=1, stroke=0)

    # Left accent stripe
    c.setFillColorRGB(*BG_DARK)
    c.rect(0, 0, 6, H, fill=1, stroke=0)

    # Title
    c.setFillColorRGB(*BG_DARK)
    c.setFont("Helvetica-Bold", 28)
    lines = simpleSplit(title, "Helvetica-Bold", 28, W - 80)
    y = H - 80
    for line in lines[:2]:
        c.drawString(40, y, line)
        y -= 36

    # Divider
    c.setStrokeColorRGB(*BG_DARK)
    c.setLineWidth(2)
    c.line(40, y - 10, W - 40, y - 10)
    y -= 40

    # Bullet points
    c.setFillColorRGB(*TEXT_DARK)
    c.setFont("Helvetica", 18)
    bullets = [b.strip() for b in content.split("\n") if b.strip()]
    for bullet in bullets[:5]:
        c.setFillColorRGB(*BG_DARK)
        c.circle(30, y + 6, 5, fill=1, stroke=0)
        c.setFillColorRGB(*TEXT_DARK)
        bullet_lines = simpleSplit(bullet, "Helvetica", 18, W - 90)
        for bl in bullet_lines[:2]:
            c.drawString(50, y, bl)
            y -= 24
        y -= 8


def _draw_cta_slide(c, W, H, title, content):
    """Last slide — dark background, takeaway + follow CTA."""
    from reportlab.lib.utils import simpleSplit

    c.setFillColorRGB(*BG_DARK)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Star/checkmark icon area
    c.setFillColorRGB(1.0, 0.75, 0.0)
    c.circle(W / 2, H - 120, 35, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(W / 2, H - 130, "✓")

    # Title
    c.setFillColorRGB(*TEXT_WHITE)
    c.setFont("Helvetica-Bold", 26)
    lines = simpleSplit(title, "Helvetica-Bold", 26, W - 80)
    y = H - 210
    for line in lines[:3]:
        c.drawCentredString(W / 2, y, line)
        y -= 34

    # Content
    if content:
        c.setFont("Helvetica", 17)
        c.setFillColorRGB(0.85, 0.90, 0.95)
        lines2 = simpleSplit(content, "Helvetica", 17, W - 100)
        y -= 20
        for line in lines2[:4]:
            c.drawCentredString(W / 2, y, line)
            y -= 24

    # Bottom CTA
    c.setFillColorRGB(1.0, 0.75, 0.0)
    c.rect(60, 40, W - 120, 50, fill=1, stroke=0, radius=8)
    c.setFillColorRGB(0.05, 0.05, 0.05)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(W / 2, 60, "Follow Jatin for weekly insights →")
