"""App icons + favicon from the أضواء logotype (run once per rebrand): python tools/brand/make_icons.py"""
from pathlib import Path
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]; PUB = ROOT / 'public'
L = Image.open(ROOT / 'tools/brand/adwaa-logo.png').convert('RGBA'); L = L.crop(L.getbbox())

def bg(W, H=None):
    H = H or W
    y, x = np.mgrid[0:H, 0:W].astype('f4'); x /= W; y /= H
    t = np.clip(.55 * x + .45 * (1 - y), 0, 1)[..., None]                     # navy → royal diagonal
    c = (1 - t) * np.array([8, 19, 46]) + t * np.array([30, 66, 140])
    g = np.exp(-(((x - .28) / .55) ** 2 + ((y - .22) / .5) ** 2))[..., None]  # soft light from top-left
    c = c * (1 - .55 * g) + np.array([70, 150, 215]) * .55 * g
    return Image.fromarray(c.clip(0, 255).astype('uint8'), 'RGB')

def icon(S, scale):
    b = bg(S).convert('RGBA'); w = int(S * scale); l = L.resize((w, round(w * L.height / L.width)), Image.LANCZOS)
    b.alpha_composite(l, ((S - l.width) // 2, (S - l.height) // 2 + S // 40)); return b.convert('RGB')

if __name__ == '__main__':
    for name, S, sc in (('icon-512', 512, .64), ('icon-192', 192, .64), ('icon-180', 180, .64), ('icon-maskable', 512, .48), ('favicon', 64, .78)):
        icon(S, sc).save(PUB / f'{name}.png', optimize=True)
    print('icons ✓')
