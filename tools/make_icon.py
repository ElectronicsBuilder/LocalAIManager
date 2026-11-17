"""Generate the application icon (dev-time only; needs Pillow).

    uv run python tools/make_icon.py

Writes src/local_ai_manager/assets/app.ico (16-256 px) and app.png (256 px).
Design: VS Code-blue rounded tile with a white processor chip labelled "AI".
Small sizes (<= 24 px) use a simplified drawing so they stay legible.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "src" / "local_ai_manager" / "assets"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SS = 1024  # supersampling canvas

TOP = (0x1E, 0x90, 0xE6)
BOTTOM = (0x00, 0x5A, 0x9E)
WHITE = (255, 255, 255, 255)
CHIP = (0x0B, 0x3D, 0x6B, 255)


def _font(px: int) -> ImageFont.FreeTypeFont:
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", px)
        except OSError:
            continue
    return ImageFont.load_default()


def _tile() -> Image.Image:
    """Rounded square with a vertical blue gradient."""
    grad = Image.new("RGBA", (SS, SS))
    gd = ImageDraw.Draw(grad)
    for y in range(SS):
        t = y / (SS - 1)
        gd.line([(0, y), (SS, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SS - 1, SS - 1], radius=int(SS * 0.22), fill=255)
    tile = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)
    return tile


def render(detailed: bool) -> Image.Image:
    img = _tile()
    d = ImageDraw.Draw(img)
    c = SS // 2
    half = int(SS * (0.25 if detailed else 0.31))       # chip half-size
    radius = int(SS * 0.06)
    if detailed:
        # pins: 3 per side
        pin_len, pin_w = int(SS * 0.09), int(SS * 0.045)
        for i in (-1, 0, 1):
            off = c + i * int(half * 0.62)
            d.rounded_rectangle([off - pin_w // 2, c - half - pin_len, off + pin_w // 2, c - half + 4],
                                radius=pin_w // 3, fill=WHITE)
            d.rounded_rectangle([off - pin_w // 2, c + half - 4, off + pin_w // 2, c + half + pin_len],
                                radius=pin_w // 3, fill=WHITE)
            d.rounded_rectangle([c - half - pin_len, off - pin_w // 2, c - half + 4, off + pin_w // 2],
                                radius=pin_w // 3, fill=WHITE)
            d.rounded_rectangle([c + half - 4, off - pin_w // 2, c + half + pin_len, off + pin_w // 2],
                                radius=pin_w // 3, fill=WHITE)
    d.rounded_rectangle([c - half, c - half, c + half, c + half], radius=radius, fill=WHITE)
    inset = int(SS * 0.035)
    d.rounded_rectangle([c - half + inset, c - half + inset, c + half - inset, c + half - inset],
                        radius=max(radius - inset, 4), fill=CHIP)
    font = _font(int(half * (1.05 if detailed else 1.2)))
    d.text((c, c + int(SS * 0.005)), "AI", font=font, fill=WHITE, anchor="mm")
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    detailed, simple = render(True), render(False)
    frames = [(simple if s <= 24 else detailed).resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(OUT_DIR / "app.png")
    # Pillow writes one frame per requested size, picking the matching image.
    frames[-1].save(OUT_DIR / "app.ico", format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"Wrote {OUT_DIR / 'app.ico'} and app.png")


if __name__ == "__main__":
    main()
