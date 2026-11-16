#!/usr/bin/env python3
"""
أضواء — ربط صور المجلة بملفاتها الأصلية (مجلد Links في حزمة InDesign)
======================================================================
الاستخدام (على الجهاز اللي فيه حزمة InDesign):
    pip install pymupdf opencv-python-headless numpy pillow
    python tools/originals.py "/path/to/<package>/Links"

يقارن كل صورة داخل ملف الـPDF مع الصور الأصلية (بالملامح البصرية، فيعرف الصورة حتى لو
كانت مقصوصة داخل الإطار)، ويحفظ لكل صورة مطابقة نسخة ويب عالية الدقة بنفس القصّ:
    issue/originals/x<xref>.webp   +   issue/originals.json
بعدها build.py يستخدمها في عارض الصور (اضغط على أي صورة في المجلة).
الصور اللي ما لها أصل تُعرض من ملف الـPDF نفسه.
"""
import json, os, sys, time
from pathlib import Path

import numpy as np, cv2, pymupdf
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None
ROOT = Path(__file__).resolve().parent.parent
MAX_SIDE = 2400


def load_cfg():
    return json.loads((ROOT / 'issue' / 'issue.json').read_text(encoding='utf-8'))


def proxy(path):
    im = Image.open(path); W, H = im.size
    if im.getexif().get(0x0112, 1) in (5, 6, 7, 8): W, H = H, W   # phone photos: honour EXIF rotation
    im.draft('RGB', (768, 768)); im = ImageOps.exif_transpose(im)
    im = im.convert('RGBA'); bg = Image.new('RGB', im.size, 'white'); bg.paste(im, mask=im.split()[3])
    bg.thumbnail((512, 512))
    return cv2.cvtColor(np.asarray(bg), cv2.COLOR_RGB2BGR), (W, H)


def main():
    if len(sys.argv) < 2:
        sys.exit('اكتب مسار مجلد Links:  python tools/originals.py "/path/to/Links"')
    links = Path(sys.argv[1])
    cfg = load_cfg(); pdf = ROOT / cfg['pdf']
    out = ROOT / 'issue' / 'originals'; out.mkdir(parents=True, exist_ok=True)
    orb = cv2.ORB_create(nfeatures=700, fastThreshold=10)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    def feats(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        k, d = orb.detectAndCompute(g, None)
        return k, d, g.shape

    t0 = time.time()
    O = {}
    files = [f for f in sorted(links.iterdir()) if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp')]
    print(f'  {len(files)} صورة أصلية — تجهيز…')
    for f in files:
        try:
            img, size = proxy(f); k, d, sh = feats(img)
            if d is not None and len(k) >= 20:
                O[f.name] = (k, d, sh, size)
        except Exception as e:
            print(f'  تخطّي {f.name}: {e}')

    doc = pymupdf.open(pdf)
    matches, done = [], set()
    for pi, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            x = info['xref']; bb = pymupdf.Rect(info['bbox'])
            if x == 0 or bb.width < 50 or bb.height < 50 or x in done:
                continue
            done.add(x)
            try:
                pix = pymupdf.Pixmap(doc, x)
                if pix.colorspace is None or pix.colorspace.n != 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                if pix.alpha:
                    pix = pymupdf.Pixmap(pix, 0)
                a = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3][:, :, ::-1].copy()
            except Exception:
                continue
            s = 512 / max(a.shape[:2])
            if s < 1:
                a = cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            k1, d1, sh1 = feats(a)
            if d1 is None or len(k1) < 15:
                continue
            best = None
            for name, (k2, d2, sh2, size) in O.items():
                mm = bf.knnMatch(d1, d2, k=2)
                good = [p[0] for p in mm if len(p) == 2 and p[0].distance < .75 * p[1].distance]
                if len(good) < 12:
                    continue
                src = np.float32([k1[g.queryIdx].pt for g in good]); dst = np.float32([k2[g.trainIdx].pt for g in good])
                Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
                if Hm is None:
                    continue
                n = int(inl.sum())
                if n >= 14 and (best is None or n > best[1]):
                    best = (name, n, Hm)
            if not best:
                continue
            name, n, Hm = best
            h1, w1 = sh1; h2, w2 = O[name][2]
            c = cv2.perspectiveTransform(np.float32([[[0, 0]], [[w1, 0]], [[w1, h1]], [[0, h1]]]), Hm).reshape(-1, 2)
            x0, y0 = max(0., float(c[:, 0].min()) / w2), max(0., float(c[:, 1].min()) / h2)
            x1, y1 = min(1., float(c[:, 0].max()) / w2), min(1., float(c[:, 1].max()) / h2)
            area = (x1 - x0) * (y1 - y0)
            # weak or degenerate matches (decorations, tiny crops) are not worth it
            if n < 20 or area < .02 or (n < 25 and area < .05) or x1 <= x0 or y1 <= y0:
                continue
            W, H = O[name][3]
            if W <= pix.w * 1.15:          # the original is not sharper than what the PDF already has
                continue
            matches.append({'xref': x, 'page': pi + 1, 'file': name, 'score': n, 'crop': [round(v, 4) for v in (x0, y0, x1, y1)]})
            print(f'\r  مطابقة {len(matches)} · صفحة {pi + 1}/{len(doc)}', end='', flush=True)
    print()

    # write web versions (cropped like the layout, sharp, small)
    keep = set()
    for m in matches:
        fn = f"x{m['xref']}.webp"; keep.add(fn)
        dst = out / fn
        im = ImageOps.exif_transpose(Image.open(links / m['file'])); W, H = im.size
        x0, y0, x1, y1 = m['crop']
        im = im.crop((int(x0 * W), int(y0 * H), int(round(x1 * W)), int(round(y1 * H))))
        im = im.convert('RGBA') if (im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)) else im.convert('RGB')
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        im.save(dst, 'WEBP', quality=82, method=5)
        m['w'], m['h'] = im.size
    for f in out.glob('x*.webp'):
        if f.name not in keep:
            f.unlink()
    (ROOT / 'issue' / 'originals.json').write_text(json.dumps({'pdf': cfg['pdf'], 'matches': matches}, ensure_ascii=False, indent=1), encoding='utf-8')
    mb = sum(f.stat().st_size for f in out.glob('*.webp')) / 1e6
    print(f'✓ {len(matches)} صورة مرتبطة بأصلها · {mb:.1f} MB · خلال {time.time() - t0:.0f} ثانية')


if __name__ == '__main__':
    main()
