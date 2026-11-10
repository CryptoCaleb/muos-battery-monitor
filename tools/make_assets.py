#!/usr/bin/env python3
"""Regenerate Battery Monitor's UI assets (run on a PC with Pillow installed).

    pip install pillow
    python tools/make_assets.py [font-bold.ttf] [font-regular.ttf]

Writes BatteryMonitor/assets/{font,logo_small,icon_big}.png plus fast-loading .bin
copies (zlib-compressed raw pixels), and the launcher glyph.
"""
import json, os, struct, sys, zlib
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "BatteryMonitor")
ASSETS = os.path.join(ROOT, "assets")
FB = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = sys.argv[2] if len(sys.argv) > 2 else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG = (9, 11, 18); ACC = (84, 104, 227)
GREEN = (72, 199, 116); YELLOW = (244, 184, 40); RED = (236, 64, 52)


def save(name, im):
    im.save(os.path.join(ASSETS, name + ".png"))
    ch = 1 if im.mode == "L" else 3
    im = im.convert("L" if ch == 1 else "RGB")
    with open(os.path.join(ASSETS, name + ".bin"), "wb") as f:
        f.write(struct.pack(">4sHHB", b"CAB1", im.width, im.height, ch) + zlib.compress(im.tobytes(), 6))


def font_atlas():
    chars = [chr(c) for c in range(32, 127)] + list("✓•…·°←↑→↓–")
    specs = [("s", FR, 15), ("m", FB, 18), ("l", FB, 24), ("x", FB, 40)]
    pad = 8; rows = []; meta = {}
    for key, path, size in specs:
        f = ImageFont.truetype(path, size); asc, desc = f.getmetrics(); lh = asc + desc
        xs, x = {}, pad
        for c in chars:
            w = max(1, int(round(f.getlength(c)))); xs[c] = [x, w]; x += w + pad
        im = Image.new("L", (x, lh), 0); d = ImageDraw.Draw(im)
        for c in chars: d.text((xs[c][0], 0), c, font=f, fill=255)
        rows.append((key, im, xs, lh))
    Wd = max(r[1].width for r in rows); Ht = sum(r[3] for r in rows) + 4 * len(rows)
    atlas = Image.new("L", (Wd, Ht), 0); y = 0
    for key, im, xs, lh in rows:
        atlas.paste(im, (0, y)); meta[key] = {"y": y, "h": lh, "chars": {str(ord(c)): v for c, v in xs.items()}}; y += lh + 4
    save("font", atlas)
    json.dump(meta, open(os.path.join(ASSETS, "font.json"), "w"))


def battery(sz, bg=None):
    """battery icon: outline + three coloured cells, sz = height"""
    w = int(sz * 1.75); im = Image.new("RGBA", (w + sz // 6, sz), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    t = max(2, sz // 12); r = max(3, sz // 6)
    d.rounded_rectangle([0, 0, w - 1, sz - 1], radius=r, outline=(255, 255, 255, 255), width=t)
    d.rounded_rectangle([w - 1, sz // 3, w + sz // 6 - 1, sz - sz // 3], radius=max(1, t // 2), fill=(255, 255, 255, 255))
    pad = t * 2; cw = (w - pad * 2 - t * 2) / 3
    for i, c in enumerate((RED, YELLOW, GREEN)):
        x0 = pad + i * (cw + t)
        d.rounded_rectangle([x0, pad, x0 + cw - 1, sz - pad - 1], radius=max(1, r // 2), fill=c + (255,))
    if bg is not None:
        base = Image.new("RGB", im.size, bg); base.paste(im, (0, 0), im); return base
    return im


def logo_small():
    f1 = ImageFont.truetype(FB, 20); f2 = ImageFont.truetype(FR, 9)
    ic = battery(22)
    t1, t2 = "Battery Monitor", "BATTERY STATS FOR muOS"
    Wd = ic.width + 10 + int(max(f1.getlength(t1), f2.getlength(t2))) + 4
    im = Image.new("RGB", (Wd, 38), BG); im.paste(ic, (0, 8), ic); d = ImageDraw.Draw(im)
    d.text((ic.width + 10, 0), t1, font=f1, fill=(255, 255, 255))
    d.text((ic.width + 11, 26), t2, font=f2, fill=ACC)
    return im


def main():
    os.makedirs(ASSETS, exist_ok=True)
    font_atlas()
    save("logo_small", logo_small())
    big = Image.new("RGB", (120, 120), BG); b = battery(54); big.paste(b, ((120 - b.width) // 2, 33), b)
    save("icon_big", big)
    # launcher glyph: white silhouette (the theme recolours it)
    g = Image.new("RGBA", (24, 24), (0, 0, 0, 0)); d = ImageDraw.Draw(g)
    d.rounded_rectangle([1, 6, 20, 18], radius=3, outline=(255, 255, 255, 255), width=2)
    d.rectangle([21, 10, 23, 14], fill=(255, 255, 255, 255))
    d.rectangle([4, 9, 14, 15], fill=(255, 255, 255, 255))
    os.makedirs(os.path.join(ROOT, "glyph"), exist_ok=True)
    g.save(os.path.join(ROOT, "glyph", "batterymonitor.png"))
    print("assets written to", os.path.normpath(ASSETS))


if __name__ == "__main__":
    main()
