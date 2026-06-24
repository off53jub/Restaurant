"""
Generate PWA + iOS home-screen icons for 外食メモ.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / 'web' / 'public' / 'icons'
OUT.mkdir(parents=True, exist_ok=True)

# Color palette pulls from the app's amber accent against neutral-950 background.
BG_TOP = (245, 158, 11)      # amber-500
BG_BOTTOM = (180, 83, 9)     # amber-700
FG = (255, 255, 255)
FONT_PATH = '/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf'


def gradient(size: int) -> Image.Image:
    img = Image.new('RGB', (size, size), BG_TOP)
    px = img.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def rounded_mask(size: int, radius_ratio: float) -> Image.Image:
    mask = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    return mask


def draw_text_center(img: Image.Image, text: str, font_size: int):
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, font_size)
    # textbbox returns (left, top, right, bottom)
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    cx = (img.width - tw) / 2 - bbox[0]
    cy = (img.height - th) / 2 - bbox[1]
    d.text((cx, cy), text, font=font, fill=FG)


def make_icon(size: int, *, rounded: bool, text: str = '外食', text_ratio: float = 0.52,
              radius_ratio: float = 0.22) -> Image.Image:
    base = gradient(size)
    draw_text_center(base, text, int(size * text_ratio))
    if rounded:
        out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        out.paste(base, (0, 0), rounded_mask(size, radius_ratio))
        return out
    return base.convert('RGBA')


def make_maskable(size: int = 512) -> Image.Image:
    # Maskable icons need their safe zone in the central 80%. Fill the whole
    # canvas (no rounding) and shrink the text so it stays inside the safe area.
    img = gradient(size).convert('RGBA')
    draw_text_center(img, '外食', int(size * 0.42))
    return img


def save(img: Image.Image, name: str):
    p = OUT / name
    img.save(p, 'PNG', optimize=True)
    print(f'  wrote {p.relative_to(OUT.parent.parent)} ({p.stat().st_size // 1024} KB)')


def main():
    # Apple touch icon — iOS home screen. Square with subtle rounding (iOS
    # rounds it again, but a small radius keeps it from looking flat in
    # contexts that don't mask).
    save(make_icon(180, rounded=False), 'apple-touch-icon.png')

    # PWA standard icons. 192 + 512.
    save(make_icon(192, rounded=True, radius_ratio=0.22), '192.png')
    save(make_icon(512, rounded=True, radius_ratio=0.22), '512.png')

    # Maskable (Android adaptive). Fills canvas; safe zone honored.
    save(make_maskable(512), 'maskable.png')

    # Favicon-sized fallback for the browser tab.
    save(make_icon(64, rounded=True, radius_ratio=0.22, text_ratio=0.56), 'favicon-64.png')


if __name__ == '__main__':
    main()
