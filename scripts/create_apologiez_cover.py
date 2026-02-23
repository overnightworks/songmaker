"""Generate the Apologiez album cover — street art / graffiti style.

Uses Pillow to create a 3000x3000 album cover with:
- Dark grungy background with spray paint texture
- Bold graffiti-style title "APOLOGIEZ"
- Subtitle "Flex0r → MC Tobbisch"
- Raw, hip-hop inspired aesthetic

Run: .venv/Scripts/python scripts/create_apologiez_cover.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 3000
OUTPUT_DIR = Path("_output/apologiez")
OUTPUT_FILE = OUTPUT_DIR / "cover_apologiez.png"


def random_color(base: tuple[int, int, int], variance: int = 30) -> tuple[int, int, int]:
    """Return a color close to base with some random variance."""
    return tuple(
        max(0, min(255, c + random.randint(-variance, variance)))
        for c in base
    )


def draw_spray_dots(
    draw: ImageDraw.ImageDraw,
    cx: int, cy: int,
    color: tuple[int, int, int],
    radius: int = 80,
    density: int = 300,
) -> None:
    """Simulate spray paint splatter around a center point."""
    for _ in range(density):
        angle = random.uniform(0, 2 * math.pi)
        r = random.gauss(0, radius / 2.5)
        x = int(cx + r * math.cos(angle))
        y = int(cy + r * math.sin(angle))
        size = random.randint(1, 4)
        alpha_color = random_color(color, 20)
        draw.ellipse([x - size, y - size, x + size, y + size], fill=alpha_color)


def draw_drip(
    draw: ImageDraw.ImageDraw,
    x: int, y_start: int,
    color: tuple[int, int, int],
    length: int = 150,
) -> None:
    """Draw a paint drip running down from a point."""
    width = random.randint(3, 8)
    drip_length = random.randint(length // 2, length)
    for dy in range(drip_length):
        fade = max(0, 255 - int(dy * 255 / drip_length))
        c = tuple(min(255, ch) for ch in color)
        wobble = int(math.sin(dy * 0.1) * 2)
        draw.rectangle(
            [x + wobble - width // 2, y_start + dy,
             x + wobble + width // 2, y_start + dy + 1],
            fill=c,
        )


def create_grungy_background(img: Image.Image) -> None:
    """Create a dark, textured background."""
    draw = ImageDraw.Draw(img)

    # Base dark gradient
    for y in range(SIZE):
        gray = int(25 + 15 * (y / SIZE))
        noise = random.randint(-8, 8)
        val = max(0, min(255, gray + noise))
        draw.line([(0, y), (SIZE, y)], fill=(val, val, val))

    # Concrete/wall texture — random noise patches
    for _ in range(50000):
        x = random.randint(0, SIZE - 1)
        y = random.randint(0, SIZE - 1)
        gray = random.randint(20, 50)
        size = random.randint(1, 3)
        draw.rectangle([x, y, x + size, y + size], fill=(gray, gray, gray))

    # Dark scratches
    for _ in range(200):
        x1 = random.randint(0, SIZE)
        y1 = random.randint(0, SIZE)
        length = random.randint(50, 400)
        angle = random.uniform(0, 2 * math.pi)
        x2 = int(x1 + length * math.cos(angle))
        y2 = int(y1 + length * math.sin(angle))
        gray = random.randint(15, 45)
        draw.line([(x1, y1), (x2, y2)], fill=(gray, gray, gray), width=1)


def draw_graffiti_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int, y: int,
    font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int],
    shadow_offset: int = 8,
    outline_width: int = 4,
) -> None:
    """Draw text with graffiti-style shadow and outline."""
    # Shadow
    shadow_color = (0, 0, 0)
    for sx in range(shadow_offset, shadow_offset + 3):
        for sy in range(shadow_offset, shadow_offset + 3):
            draw.text((x + sx, y + sy), text, font=font, fill=shadow_color)

    # Outline
    for ox in range(-outline_width, outline_width + 1):
        for oy in range(-outline_width, outline_width + 1):
            if ox * ox + oy * oy <= outline_width * outline_width:
                draw.text((x + ox, y + oy), text, font=font, fill=(0, 0, 0))

    # Main text
    draw.text((x, y), text, font=font, fill=color)


def get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Try to load a good font, fall back to default."""
    font_paths = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    if not bold:
        font_paths = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
        ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def main() -> None:
    random.seed(42)  # Reproducible
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (SIZE, SIZE))
    draw = ImageDraw.Draw(img)

    # === Background ===
    create_grungy_background(img)

    # === Spray paint splatters (background decoration) ===
    spray_colors = [
        (220, 40, 40),    # red
        (255, 165, 0),    # orange
        (255, 220, 0),    # yellow
        (0, 180, 255),    # blue
        (180, 0, 255),    # purple
    ]

    # Background spray clusters
    for _ in range(15):
        cx = random.randint(100, SIZE - 100)
        cy = random.randint(100, SIZE - 100)
        color = random.choice(spray_colors)
        draw_spray_dots(draw, cx, cy, color, radius=200, density=500)

    # === Main title: APOLOGIEZ ===
    title_font = get_font(380)
    title = "APOLOGIEZ"
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    title_x = (SIZE - tw) // 2
    title_y = 750

    # Red/orange graffiti color
    title_color = (255, 50, 30)
    draw_graffiti_text(draw, title, title_x, title_y, title_font, title_color,
                       shadow_offset=12, outline_width=6)

    # Drips from title
    for i in range(0, tw, 60):
        if random.random() > 0.5:
            drip_x = title_x + i + random.randint(-10, 10)
            draw_drip(draw, drip_x, title_y + 340, title_color, length=200)

    # === Spray paint around title for emphasis ===
    for _ in range(8):
        sx = title_x + random.randint(-100, tw + 100)
        sy = title_y + random.randint(-50, 350)
        draw_spray_dots(draw, sx, sy, (255, 80, 30), radius=120, density=150)

    # === Subtitle: FLEX0R → MC TOBBISCH ===
    sub_font = get_font(140)
    subtitle = "FLEX0R  →  MC TOBBISCH"
    bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
    sw = bbox[2] - bbox[0]
    sub_x = (SIZE - sw) // 2
    sub_y = title_y + 420

    draw_graffiti_text(draw, subtitle, sub_x, sub_y, sub_font, (255, 220, 0),
                       shadow_offset=6, outline_width=3)

    # === Tagline: "sorry for the robot voice" ===
    tag_font = get_font(80, bold=False)
    tagline = '"sorry for the robot voice"'
    bbox = draw.textbbox((0, 0), tagline, font=tag_font)
    tag_w = bbox[2] - bbox[0]
    tag_x = (SIZE - tag_w) // 2
    tag_y = sub_y + 200

    draw_graffiti_text(draw, tagline, tag_x, tag_y, tag_font, (200, 200, 200),
                       shadow_offset=4, outline_width=2)

    # === Bottom: track listing spray-painted ===
    tracks_font = get_font(55, bold=False)
    tracks = [
        "01 HAPPY BIRTHDAY TOBBISCH",
        "02 SORRY (NOT SORRY)",
        "03 RAP BATTLE PART 2",
        "04 DIE KI SINGT FÜR DICH",
        "05 BRUDER",
        "BONUS: FIRE IN THE HOLE",
    ]

    track_y = 1900
    for i, track in enumerate(tracks):
        color = random_color((180, 180, 180), 20)
        tx = 250
        draw_graffiti_text(draw, track, tx, track_y + i * 90, tracks_font, color,
                           shadow_offset=3, outline_width=2)

    # === Corner tag: "AI GENERATED • 2026" ===
    corner_font = get_font(50, bold=False)
    corner_text = "AI GENERATED • 2026"
    draw_graffiti_text(draw, corner_text, SIZE - 750, SIZE - 120, corner_font,
                       (120, 120, 120), shadow_offset=2, outline_width=1)

    # === X marks / crosses (graffiti detail) ===
    for _ in range(5):
        cx = random.randint(200, SIZE - 200)
        cy = random.randint(200, SIZE - 200)
        size = random.randint(30, 80)
        color = random.choice(spray_colors)
        draw.line([(cx - size, cy - size), (cx + size, cy + size)], fill=color, width=4)
        draw.line([(cx + size, cy - size), (cx - size, cy + size)], fill=color, width=4)

    # === Save ===
    img.save(str(OUTPUT_FILE), "PNG")
    print(f"Cover saved: {OUTPUT_FILE}")
    print(f"Size: {SIZE}x{SIZE} px")


if __name__ == "__main__":
    main()
