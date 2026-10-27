"""Loom's drawing board: turns a slogan into print-ready shirt art, free, with Pillow and the fonts in ./fonts.

Every design gets two print files at 4500 x 5400 pixels with a transparent background (Printify's size for the front
of a tee at 300 dpi): dark ink for light shirts and light ink for dark shirts. It also gets a preview of both on a
shirt, for the approval card. If the design has a picture (made by images.py), it goes above the words.

The fonts are free for commercial use (SIL Open Font License, and Apache 2.0 for Permanent Marker); their licenses
are next to them.
"""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "fonts"
W, H = 4500, 5400
MARGIN = 300

INK = {"dark": (29, 29, 31, 255), "light": (247, 243, 234, 255)}
SHIRT = {"dark": (246, 245, 241), "light": (30, 30, 34)}   # the shirt each ink goes on, for the preview

STYLES = {
    # name: (main font, second font, uppercase, accent colours for dark ink, for light ink)
    "bold": ("Anton-Regular.ttf", "BebasNeue-Regular.ttf", True, [(214, 69, 65)], [(242, 165, 65)]),
    "retro": ("Bungee-Regular.ttf", "Righteous-Regular.ttf", True,
              [(232, 93, 58), (242, 165, 65), (246, 213, 92)], [(232, 93, 58), (242, 165, 65), (246, 213, 92)]),
    "script": ("Pacifico-Regular.ttf", "ArchivoBlack-Regular.ttf", False, [(196, 74, 103)], [(255, 160, 180)]),
    "marker": ("PermanentMarker-Regular.ttf", "PermanentMarker-Regular.ttf", False, [(46, 125, 160)], [(120, 200, 230)]),
    "badge": ("AbrilFatface-Regular.ttf", "BebasNeue-Regular.ttf", False, [(46, 107, 74)], [(150, 210, 160)]),
}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _fit(text: str, face: str, width: int, top: int) -> ImageFont.FreeTypeFont:
    """The biggest size (up to `top`) at which `text` fits `width`."""
    lo, hi = 40, top
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=font(face, mid)) <= width:
            lo = mid
        else:
            hi = mid - 1
    return font(face, lo)


def _lines(slogan: str, upper: bool) -> list[str]:
    text = " ".join(slogan.split())
    text = text.upper() if upper else text
    if "/" in text:   # Quill can mark its own line breaks with /
        return [p.strip() for p in text.split("/") if p.strip()]
    width = 10 if len(text) > 18 else 9
    return textwrap.wrap(text, width=width) or [text]


def _draw_text_block(img: Image.Image, lines: list[str], subline: str | None, style: str, ink: str, top: int) -> int:
    """Draws the words from `top` down, centred. Returns where they end."""
    face, second, upper, accents_dark, accents_light = STYLES[style]
    accents = accents_dark if ink == "dark" else accents_light
    color = INK[ink]
    d = ImageDraw.Draw(img)
    y = top
    inner = W - 2 * MARGIN
    for i, line in enumerate(lines):
        if style == "script" and i == 0:
            f = _fit(line, face, inner, 1100)
        elif style == "script":
            f = _fit(line, second, int(inner * 0.86), 700)
        else:
            f = _fit(line, face, inner, 1300 if style == "bold" else 900)
        box = d.textbbox((0, 0), line, font=f)
        lw, lh = box[2] - box[0], box[3] - box[1]
        x = (W - lw) // 2 - box[0]
        if style == "retro":
            for k, acc in enumerate(reversed(accents)):   # stacked drop shadows in sunset colours
                off = (len(accents) - k) * max(6, f.size // 30)
                d.text((x + off, y - box[1] + off), line, font=f, fill=acc + (255,))
        line_fill = accents[0] + (255,) if style == "script" and i == 0 else color
        d.text((x, y - box[1]), line, font=f, fill=line_fill)
        y += lh + (90 if style != "bold" else 70)
    if subline:
        sub = subline.upper() if upper or style in ("bold", "badge") else subline
        f = _fit(sub, second, int(inner * 0.8), 420)
        box = d.textbbox((0, 0), sub, font=f)
        x = (W - (box[2] - box[0])) // 2 - box[0]
        y += 40
        d.text((x, y - box[1]), sub, font=f, fill=(accents[0] + (255,)) if style != "marker" else color)
        y += box[3] - box[1]
    return y


def _sunset(img: Image.Image, top: int, accents: list) -> int:
    """A retro striped sun above the words."""
    d = ImageDraw.Draw(img)
    r = 1050
    cx, cy = W // 2, top + r
    d.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=accents[1] + (255,))
    for k in range(5):   # stripes cut through the sun, thicker toward the bottom
        y = cy - r * 0.55 + k * r * 0.12
        d.rectangle([cx - r, y, cx + r, y + 18 + k * 14], fill=(0, 0, 0, 0))
    d.rectangle([cx - r, cy - 40, cx + r, cy], fill=accents[0] + (255,))
    return cy + 60


def _badge(img: Image.Image, ink: str, top: int, bottom: int, accents: list):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([MARGIN - 80, top - 160, W - MARGIN + 80, bottom + 160], radius=260,
                        outline=INK[ink], width=70)
    d.rounded_rectangle([MARGIN + 20, top - 60, W - MARGIN - 20, bottom + 60], radius=200,
                        outline=accents[0] + (255,), width=26)


def render(design: dict, out_dir: Path, art: Path | None = None) -> dict:
    """Draws the design and saves dark.png, light.png and preview.png in out_dir. Returns their paths."""
    style = design.get("style") if design.get("style") in STYLES else "bold"
    out_dir.mkdir(parents=True, exist_ok=True)
    upper = STYLES[style][2]
    lines = _lines(design["slogan"], upper)
    subline = (design.get("subline") or "").strip() or None
    files = {}
    for ink in ("dark", "light"):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        top = 380
        accents = STYLES[style][3] if ink == "dark" else STYLES[style][4]
        if art and Path(art).is_file():
            pic = Image.open(art).convert("RGBA")
            pic.thumbnail((W - 2 * MARGIN, 2600), Image.LANCZOS)
            if pic.width < W - 2 * MARGIN:   # images come in at 1024 px: scale up to fill the space
                scale = min((W - 2 * MARGIN) / pic.width, 2600 / pic.height)
                pic = pic.resize((int(pic.width * scale), int(pic.height * scale)), Image.LANCZOS)
            img.alpha_composite(pic, ((W - pic.width) // 2, top))
            top += pic.height + 160
        elif style == "retro":
            top = _sunset(img, top, accents)
        text_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        start = top + (240 if style == "badge" else 0)
        end = _draw_text_block(text_img, lines, subline, style, ink, start)
        if style == "badge":
            _badge(text_img, ink, start, end, accents)
        img.alpha_composite(text_img)
        bbox = img.getbbox()
        if bbox and bbox[3] > H - 120:   # too tall: shrink everything to fit the print area
            content = img.crop((0, 0, W, bbox[3]))
            content.thumbnail((W, H - 240), Image.LANCZOS)
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            img.alpha_composite(content, ((W - content.width) // 2, 120))
        path = out_dir / f"{ink}.png"
        img.save(path, dpi=(300, 300))
        files[ink] = str(path)
    files["preview"] = str(preview(Path(files["dark"]), Path(files["light"]), out_dir / "preview.png"))
    return files


def _shirt(color: tuple, size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = w / 100
    body = [(29, 6), (40, 3), (60, 3), (71, 6), (96, 23), (87, 39), (77, 33), (78, 97), (22, 97), (23, 33),
            (13, 39), (4, 23)]
    d.polygon([(x * s, y * h / 100) for x, y in body], fill=color + (255,))
    d.chord([40 * s, -2 * h / 100, 60 * s, 12 * h / 100], 0, 180, fill=(0, 0, 0, 0))   # neckline
    edge = tuple(max(0, c - 18) for c in color) if sum(color) > 380 else tuple(min(255, c + 22) for c in color)
    d.line([(x * s, y * h / 100) for x, y in body + body[:1]], fill=edge + (255,), width=max(2, w // 200))
    return img


def preview(dark: Path, light: Path, out: Path) -> Path:
    """Both versions on a shirt, side by side: what you see on the approval card."""
    cw, ch = 1200, 720
    canvas = Image.new("RGB", (cw, ch), (238, 233, 224))
    for i, (ink, path) in enumerate((("dark", dark), ("light", light))):
        tee = _shirt(SHIRT[ink], (560, 660))
        art = Image.open(path).convert("RGBA")
        art.thumbnail((250, 300), Image.LANCZOS)
        tee.alpha_composite(art, ((560 - art.width) // 2, 120))
        canvas.paste(tee, (20 + i * 600, 40), tee)
    canvas.save(out)
    return out
