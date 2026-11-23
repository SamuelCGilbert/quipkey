"""The app icon, drawn in code (used for the tray and, by the build, for the .ico file)."""
from __future__ import annotations

BG = (28, 28, 31, 255)
FG = (242, 242, 243, 255)
REC = (255, 77, 79, 255)


def make_icon(size: int = 256, recording: bool = False):
    from PIL import Image, ImageDraw

    s = 4 * size  # draw large, then downsample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, s - 1, s - 1), fill=REC if recording else BG)
    u = s / 32
    # mic capsule
    d.rounded_rectangle((12.5 * u, 6 * u, 19.5 * u, 19 * u), radius=3.5 * u, fill=FG)
    # holder arc, stem and base
    w = max(1, round(1.8 * u))
    d.arc((9 * u, 10 * u, 23 * u, 23.5 * u), start=0, end=180, fill=FG, width=w)
    d.line((16 * u, 23.5 * u, 16 * u, 26.5 * u), fill=FG, width=w)
    d.line((12 * u, 26.5 * u, 20 * u, 26.5 * u), fill=FG, width=w)
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path, recording: bool = False):
    img = make_icon(256, recording)
    img.save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
