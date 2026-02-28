"""Generate album cover for Friday at Murphy's.

Dark pub aesthetic with neon-style title, Irish green accents,
and track listing. Uses numpy for fast rendering.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

OUTPUT = "_output/murphys/final/cover.png"
SIZE = 3000


def make_gradient(size, colors_stops):
    """Create vertical gradient from color stops [(pos, (r,g,b)), ...]."""
    arr = np.zeros((size, size, 3), dtype=np.uint8)
    for i in range(len(colors_stops) - 1):
        y0, c0 = colors_stops[i]
        y1, c1 = colors_stops[i + 1]
        py0, py1 = int(y0 * size), int(y1 * size)
        for ch in range(3):
            arr[py0:py1, :, ch] = np.linspace(c0[ch], c1[ch], py1 - py0).reshape(-1, 1)
    return arr


def add_noise(arr, amount=8):
    """Add subtle noise for texture."""
    rng = np.random.default_rng(42)
    noise = rng.integers(-amount, amount + 1, arr.shape, dtype=np.int16)
    return np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def radial_glow(size, cx, cy, radius, color, intensity=0.3):
    """Create radial glow overlay."""
    y, x = np.ogrid[:size, :size]
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2).astype(np.float32)
    mask = np.clip(1.0 - dist / radius, 0, 1) ** 2.5 * intensity
    glow = np.zeros((size, size, 3), dtype=np.float32)
    for ch in range(3):
        glow[:, :, ch] = mask * color[ch]
    return glow


def draw_cover():
    # === Dark pub gradient background ===
    bg = make_gradient(SIZE, [
        (0.00, (15, 40, 20)),    # Dark green top
        (0.06, (30, 20, 10)),    # Dark wood
        (0.35, (50, 30, 15)),    # Warm wood center
        (0.65, (45, 28, 14)),    # Wood
        (0.94, (25, 15, 8)),     # Dark bottom
        (1.00, (10, 35, 18)),    # Dark green bottom
    ])

    # Add texture noise
    bg = add_noise(bg, 10)

    # === Horizontal wood grain lines ===
    for y in range(0, SIZE, 3):
        wave = int(3 * np.sin(y * 0.008))
        brightness = int(8 * np.sin(y * 0.03 + wave))
        bg[y, :, :] = np.clip(bg[y, :, :].astype(np.int16) + brightness, 0, 255).astype(np.uint8)

    # === Warm amber glow behind title ===
    glow1 = radial_glow(SIZE, SIZE // 2, SIZE // 2 - 150, 1200, (255, 170, 40), 0.25)
    # Secondary green glow at top
    glow2 = radial_glow(SIZE, SIZE // 2, 0, 800, (0, 120, 60), 0.12)

    bg_f = bg.astype(np.float32) + glow1 + glow2
    bg = np.clip(bg_f, 0, 255).astype(np.uint8)

    img = Image.fromarray(bg)
    draw = ImageDraw.Draw(img)

    # === Irish green bars (top and bottom) ===
    bar = Image.new("RGBA", (SIZE, 80), (0, 130, 65, 200))
    img.paste((0, 100, 50), (0, 0, SIZE, 80), bar.split()[3])
    img.paste((0, 100, 50), (0, SIZE - 80, SIZE, SIZE), bar.split()[3])

    # Gold pinstripes
    draw = ImageDraw.Draw(img)
    draw.line([(0, 80), (SIZE, 80)], fill=(200, 160, 60), width=4)
    draw.line([(0, SIZE - 80), (SIZE, SIZE - 80)], fill=(200, 160, 60), width=4)

    # === Fonts ===
    try:
        font_title = ImageFont.truetype("arialbd.ttf", 260)
        font_artist = ImageFont.truetype("arialbd.ttf", 100)
        font_sub = ImageFont.truetype("ariali.ttf", 55)
        font_track = ImageFont.truetype("arial.ttf", 55)
        font_track_b = ImageFont.truetype("arialbd.ttf", 55)
        font_small = ImageFont.truetype("arial.ttf", 42)
    except OSError:
        font_title = ImageFont.truetype("arial.ttf", 260)
        font_artist = ImageFont.truetype("arial.ttf", 100)
        font_sub = ImageFont.truetype("arial.ttf", 55)
        font_track = ImageFont.truetype("arial.ttf", 55)
        font_track_b = ImageFont.truetype("arial.ttf", 55)
        font_small = ImageFont.truetype("arial.ttf", 42)

    # === Title ===
    title_lines = ["FRIDAY", "AT MURPHY'S"]
    y_pos = SIZE // 2 - 420

    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        tw = bbox[2] - bbox[0]
        tx = (SIZE - tw) // 2

        # Outer glow (draw blurred behind)
        for offset in [(0, -3), (0, 3), (-3, 0), (3, 0), (-2, -2), (2, 2), (-2, 2), (2, -2)]:
            draw.text((tx + offset[0] * 3, y_pos + offset[1] * 3), line,
                       fill=(180, 120, 20), font=font_title)
        # Shadow
        draw.text((tx + 8, y_pos + 8), line, fill=(15, 8, 3), font=font_title)
        # Main text — bright gold
        draw.text((tx, y_pos), line, fill=(255, 210, 70), font=font_title)

        y_pos += 280

    # === Decorative line ===
    line_y = y_pos + 30
    line_w = 800
    lx = (SIZE - line_w) // 2
    draw.line([(lx, line_y), (lx + line_w, line_y)], fill=(200, 160, 60), width=3)
    # Center diamond
    dx = SIZE // 2
    diamond_size = 12
    draw.polygon([
        (dx, line_y - diamond_size),
        (dx + diamond_size, line_y),
        (dx, line_y + diamond_size),
        (dx - diamond_size, line_y),
    ], fill=(0, 160, 70))

    # === Artist name ===
    artist_y = line_y + 50
    artist = "FLEX0R"
    bbox = draw.textbbox((0, 0), artist, font=font_artist)
    aw = bbox[2] - bbox[0]
    ax = (SIZE - aw) // 2
    draw.text((ax + 5, artist_y + 5), artist, fill=(15, 8, 3), font=font_artist)
    draw.text((ax, artist_y), artist, fill=(220, 185, 110), font=font_artist)

    # === Track listing ===
    tracks = [
        ("1", "Tom's Third Pub", "Speed Punk"),
        ("2", "Pub Quiz Tuesday", "Indie Rock"),
        ("3", "Die beste Pizza", "Comedy Rock"),
        ("4", "Prost!", "Deutschpunk"),
        ("5", "Friday at Murphy's", "Pop Punk"),
        ("6", "Meine Schicht", "German Rap"),
    ]

    # Dark overlay bar at bottom
    overlay = Image.new("RGBA", (SIZE, 480), (10, 6, 3, 190))
    img.paste(Image.new("RGB", (SIZE, 480), (10, 6, 3)), (0, SIZE - 560),
              overlay.split()[3])

    draw = ImageDraw.Draw(img)

    # Gold separator line above track list
    draw.line([(200, SIZE - 560), (SIZE - 200, SIZE - 560)], fill=(160, 130, 50), width=2)

    track_y = SIZE - 520
    for num, title, genre in tracks:
        # Number
        draw.text((350, track_y), f"{num}.", fill=(160, 130, 50), font=font_track_b)
        # Title
        draw.text((420, track_y), title, fill=(220, 190, 130), font=font_track)
        # Genre tag (right-aligned)
        bbox = draw.textbbox((0, 0), genre, font=font_small)
        gw = bbox[2] - bbox[0]
        draw.text((SIZE - 350 - gw, track_y + 8), genre, fill=(120, 100, 65), font=font_small)
        track_y += 72

    # === Year centered at very bottom ===
    year = "ERLANGEN 2026"
    bbox = draw.textbbox((0, 0), year, font=font_small)
    yw = bbox[2] - bbox[0]
    draw.text(((SIZE - yw) // 2, SIZE - 55), year, fill=(100, 80, 50), font=font_small)
    # Green bar text
    pub = "MURPHY'S IRISH PUB"
    bbox = draw.textbbox((0, 0), pub, font=font_small)
    pw = bbox[2] - bbox[0]
    draw.text(((SIZE - pw) // 2, 20), pub, fill=(200, 180, 120), font=font_small)

    # === Save ===
    img.save(OUTPUT, "PNG")
    print(f"Cover saved to {OUTPUT} ({SIZE}x{SIZE})")

    small = img.resize((600, 600), Image.LANCZOS)
    small.save(OUTPUT.replace(".png", "_thumb.png"), "PNG")
    print(f"Thumbnail saved")


if __name__ == "__main__":
    draw_cover()
