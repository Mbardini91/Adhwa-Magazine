#!/usr/bin/env python3
"""
أضواء — بناء الموقع من ملف PDF لعدد جديد
=========================================
الاستخدام (من مجلد المشروع):
    pip install -r tools/requirements.txt
    python tools/build.py

يقرأ issue/issue.json + ملف الـPDF المذكور فيه، ويولّد كل شيء داخل public/:
صفحات المجلة، الصور المصغّرة، نسخة التكبير، البحث، الروابط، المواضيع، ملف التحميل،
صورة المعاينة، و index.html. بعدها: git push (Vercel ينشر تلقائياً)
"""
import json, os, re, shutil, sys, time
from pathlib import Path

try:
    import pymupdf as fitz
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
except ImportError:
    sys.exit('ثبّت المتطلبات أولاً:  pip install -r tools/requirements.txt')

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'tools'
PUB = ROOT / 'public'
sys.path.insert(0, str(TOOLS))
from words import page_words  # noqa: E402
import speech  # noqa: E402

PAGE_W, HI_W, THUMB_W = 1100, 2200, 200


def log(msg):
    print('  ' + msg, flush=True)


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else None


def load_issue():
    p = Path(arg('--issue')).resolve() if arg('--issue') else ROOT / 'issue' / 'issue.json'
    if not p.exists():
        sys.exit('لم أجد issue/issue.json')
    cfg = json.loads(p.read_text(encoding='utf-8'))
    for k in ('id', 'number', 'label', 'title', 'pdf'):
        if not cfg.get(k):
            sys.exit(f'الحقل "{k}" ناقص في issue/issue.json')
    if not re.fullmatch(r'[a-z0-9-]{1,32}', cfg['id']):
        sys.exit('حقل "id" يجب أن يكون حروف إنجليزية صغيرة وأرقام وشرطة فقط، مثل 2026-q3')
    pdf = ROOT / cfg['pdf']
    if not pdf.exists():
        sys.exit(f'ملف الـPDF غير موجود: {cfg["pdf"]}')
    return p, cfg, pdf


def resolve_links(doc, page, W, H, names):
    def fix(s):
        try:
            return s.encode('latin-1').decode('utf-8')
        except Exception:
            return s
    out = []
    for l in page.get_links():
        r = l['from'] & page.rect
        if r.is_empty:
            continue
        box = [round(r.x0 / W, 4), round(r.y0 / H, 4), round(r.width / W, 4), round(r.height / H, 4)]
        if l.get('uri'):
            u = l['uri']
            out.append({'b': box, 'u': u.replace('%40', '@') if u.startswith('mailto') else u})
        else:
            tgt = None
            nd = l.get('nameddest')
            if nd:
                rr = names.get(fix(nd)) or names.get(nd)
                if rr:
                    tgt = rr['page']
            elif l.get('page', -1) >= 0:
                tgt = l['page']
            if tgt is not None and tgt >= 0:
                out.append({'b': box, 'p': tgt + 1})
    return out


def draft_topics(pages, n_pages):
    """Guess articles from the table of contents (the page with most internal links)."""
    toc = max(range(n_pages), key=lambda i: sum(1 for l in pages[i]['links'] if 'p' in l))
    links = [l for l in pages[toc]['links'] if 'p' in l]
    if len(links) < 3:
        return []
    words = pages[toc]['words']
    by_target = {}
    for l in links:
        x, y, w, h = l['b']
        for wd in words:
            cx, cy = wd[1] + wd[3] / 2, wd[2] + wd[4] / 2
            if x <= cx <= x + w and y <= cy <= y + h:
                by_target.setdefault(l['p'], []).append(wd)
    starts = sorted(p for p in by_target if p > toc + 1)
    topics = []
    for k, s in enumerate(starts):
        e = (starts[k + 1] - 1) if k + 1 < len(starts) else n_pages - 1
        seen, title = set(), []
        for wd in by_target[s]:
            t = re.sub(r'^\d+\.?|\.?\d+$', '', wd[0]).strip(' .')
            if t and id(wd) not in seen:
                seen.add(id(wd)); title.append(t)
        topics.append({'id': f't{k + 1:02d}', 's': s, 'e': max(s, e), 't': ' '.join(title) or f'صفحة {s}'})
    return topics


def page_photos(doc, page, pi, W, H, words, originals, out_dir, seen):
    """Tappable photos of a page: original file when matched (issue/originals), else a sharp crop of the PDF."""
    area_page = W * H; out = []; boxes = []
    for info in page.get_image_info(xrefs=True):
        bb = fitz.Rect(info['bbox']) & page.rect
        if not info['xref'] or bb.is_empty or bb.width < 70 or bb.height < 70: continue   # xref 0 = inline masks/frames
        a = bb.width * bb.height / area_page
        if a > .55 or a < .012: continue                      # full-bleed backgrounds / tiny ornaments
        if any(abs(bb.x0 - b.x0) < 2 and abs(bb.y0 - b.y0) < 2 and abs(bb.x1 - b.x1) < 2 for b in boxes): continue
        boxes.append(bb); x = info['xref']
        name = f'x{x}.webp' if x else f'p{pi + 1}-{len(out)}.webp'
        if x in originals:
            src = ROOT / 'issue' / 'originals' / name
            if name not in seen: shutil.copy(src, out_dir / name)
            o = originals[x]; wpx, hpx, orig = o['w'], o['h'], 1
        else:
            name = f'p{pi + 1}-{len(out)}.webp'
            z = max(1.4, min(3.0, (info.get('width') or bb.width) / bb.width * 1.15))
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=bb, alpha=False)
            im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            im.thumbnail((1800, 1800), Image.LANCZOS); im.save(out_dir / name, 'WEBP', quality=80, method=4)
            wpx, hpx, orig = im.width, im.height, 0
        seen.add(name)
        # caption: short text laid on / just under the photo (names under portraits)
        cap = []
        for w in words:
            cx, cy = (w[1] + w[3] / 2) * W, (w[2] + w[4] / 2) * H
            if bb.x0 - 2 <= cx <= bb.x1 + 2 and bb.y1 - .3 * bb.height <= cy <= bb.y1 + 26: cap.append(w)
        cap = ' '.join(w[0] for w in cap) if 0 < len(cap) <= 9 else ''
        if re.fullmatch(r'[\d\s.|\-–]*', cap): cap = ''
        out.append({'b': [round(bb.x0 / W, 4), round(bb.y0 / H, 4), round(bb.width / W, 4), round(bb.height / H, 4)],
                    's': 'photos/' + name, 'w': wpx, 'h': hpx, 'o': orig, 'c': cap})
    return out


def make_og(cover_path, out_path, label=''):
    """Share card (WhatsApp/LinkedIn/X): issue cover + the أضواء logotype + issue label."""
    import numpy as np
    W, H = 1200, 630
    y, x = np.mgrid[0:H, 0:W].astype('f4'); x /= W; y /= H
    t = np.clip(.55 * x + .45 * (1 - y), 0, 1)[..., None]
    c = (1 - t) * np.array([8, 19, 46]) + t * np.array([26, 58, 126])
    g = np.exp(-(((x - .2) / .45) ** 2 + ((y - .45) / .6) ** 2))[..., None]
    c = c * (1 - .5 * g) + np.array([60, 140, 210]) * .5 * g
    bg = Image.fromarray(c.clip(0, 255).astype('uint8'), 'RGB')
    cov = Image.open(cover_path).convert('RGB')
    ch = 530; cw = round(cov.width * ch / cov.height)
    cov = cov.resize((cw, ch), Image.LANCZOS)
    sh = Image.new('L', (cw + 120, ch + 120), 0)
    ImageDraw.Draw(sh).rectangle((60, 75, cw + 60, ch + 75), fill=160)
    sh = sh.filter(ImageFilter.GaussianBlur(26))
    cx = 100
    bg.paste((3, 8, 20), (cx - 60, (H - ch) // 2 - 60), sh)
    bg.paste(cov, (cx, (H - ch) // 2))
    right = W - 90
    logo = ROOT / 'tools' / 'brand' / 'adwaa-logo.png'
    if logo.exists():
        L = Image.open(logo).convert('RGBA'); L = L.crop(L.getbbox())
        lw = 400; L = L.resize((lw, round(lw * L.height / L.width)), Image.LANCZOS)
        bg.paste(L, (right - lw, 70), L)
        ty = 70 + L.height + 40
    else:
        ty = 260
    if features.check('raqm'):
        try:
            d = ImageDraw.Draw(bg)
            f = ImageFont.truetype(str(PUB / 'fonts' / 'plex-arabic-500.woff2'), 38)
            if label:   # the Arabic web font is subset (no digits): lay runs right-to-left, digits in the Latin face
                fl = ImageFont.truetype(str(PUB / 'fonts' / 'plex-latin-500.woff2'), 38)
                x = right
                for run in re.findall(r'[0-9A-Za-z·.\-–]+|[^0-9A-Za-z·.\-–]+', label):
                    lat = bool(re.match(r'[0-9A-Za-z·.\-–]', run))
                    fnt = fl if lat else f
                    w = d.textlength(run, font=fnt, direction=None if lat else 'rtl')
                    d.text((x, ty + 38), run, font=fnt, fill='white', anchor='rs', direction=None if lat else 'rtl')
                    x -= w
            f2 = ImageFont.truetype(str(PUB / 'fonts' / 'plex-arabic-400.woff2'), 28)
            d.text((right, ty + 92), 'تصفّح العدد تفاعلياً', font=f2, fill='#b9c9e6', anchor='rs', direction='rtl')
        except Exception:
            pass
    bg.save(out_path, 'JPEG', quality=88)


def main():
    global PUB
    t0 = time.time()
    cfg_path, cfg, pdf = load_issue()
    # a past issue rebuilt with the current template lives in public/archive/<id>/
    archived = '--archive' in sys.argv
    if archived:
        PUB = ROOT / 'public' / 'archive' / cfg['id']
        PUB.mkdir(parents=True, exist_ok=True)
        root = ROOT / 'public'
        for f in ('fonts',):
            shutil.rmtree(PUB / f, ignore_errors=True); shutil.copytree(root / f, PUB / f)
        for f in ('supabase-config.js', 'firebase-config.js', 'likes.bundle.js', 'favicon.png', 'icon-180.png'):
            if (root / f).exists(): shutil.copy2(root / f, PUB / f)
        if '--no-audio' not in sys.argv: sys.argv.append('--no-audio')
        global HI_W; HI_W = 1700          # lighter archive: zoom stays sharp, ~40% smaller
    print(f'\nأضواء — بناء {cfg["title"]}')
    doc = fitz.open(pdf)
    N = len(doc)
    W, H = doc[0].rect.width, doc[0].rect.height
    names = doc.resolve_names()

    skip_img = '--skip-images' in sys.argv and (PUB / 'pages' / f'p{N:02d}.webp').exists() and not (PUB / 'pages' / f'p{N + 1:02d}.webp').exists()
    if not skip_img:
        for d in ('pages', 'hi', 'thumbs'):
            shutil.rmtree(PUB / d, ignore_errors=True)
            (PUB / d).mkdir(parents=True)
        for old in PUB.glob('*.pdf'):
            old.unlink()
        log(f'{N} صفحة — تجهيز الصور…')
    else:
        log(f'{N} صفحة — الصور موجودة، تخطّيت إعادة توليدها (--skip-images)')
    orig_path = ROOT / 'issue' / 'originals.json'
    originals = {}
    if orig_path.exists():
        oj = json.loads(orig_path.read_text(encoding='utf-8'))
        if oj.get('pdf') == cfg['pdf']:
            originals = {m['xref']: m for m in oj['matches'] if (ROOT / 'issue' / 'originals' / f"x{m['xref']}.webp").exists()}
        else:
            log('⚠️ issue/originals.json لعدد آخر — شغّل tools/originals.py لهذا العدد')
    shutil.rmtree(PUB / 'photos', ignore_errors=True); (PUB / 'photos').mkdir(parents=True)
    seen_photos = set()
    # topics with "photos": false (e.g. honour-roll portraits) don't open photos full screen
    no_link_pages = {n for tp in cfg.get('topics', []) if tp.get('links') is False for n in range(tp['s'], tp['e'] + 1)}
    no_photo_pages = {n for tp in cfg.get('topics', []) if tp.get('photos') is False for n in range(tp['s'], tp['e'] + 1)}
    pages = []
    for i, p in enumerate(doc):
        if not skip_img:
            pix = p.get_pixmap(matrix=fitz.Matrix(HI_W / p.rect.width, HI_W / p.rect.width), alpha=False)
            im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            n = f'{i + 1:02d}'
            im.save(PUB / 'hi' / f'h{n}.webp', 'WEBP', quality=72 if archived else 80, method=4)
            im.resize((PAGE_W, round(PAGE_W * im.height / im.width)), Image.LANCZOS).save(PUB / 'pages' / f'p{n}.webp', 'WEBP', quality=80, method=6)
            im.resize((THUMB_W, round(THUMB_W * im.height / im.width)), Image.LANCZOS).save(PUB / 'thumbs' / f't{n}.webp', 'WEBP', quality=75)
            print(f'\r  صفحة {i + 1}/{N}', end='', flush=True)
        words = page_words(p, W, H)
        pages.append({'links': [] if (i + 1) in no_link_pages else resolve_links(doc, p, W, H, names), 'words': words, 'say': speech.segments(words),
                      'photos': [] if (i + 1) in no_photo_pages else page_photos(doc, p, i, W, H, words, originals, PUB / 'photos', seen_photos)})
    if not skip_img:
        print()
    nph = sum(len(p['photos']) for p in pages); nor = sum(1 for p in pages for x in p['photos'] if x['o'])
    log(f'الصور القابلة للفتح: {nph} (منها {nor} من الملفات الأصلية)')
    # brand + issue assets
    shutil.rmtree(PUB / 'assets', ignore_errors=True)
    if (ROOT / 'issue' / 'assets').exists(): shutil.copytree(ROOT / 'issue' / 'assets', PUB / 'assets')
    (PUB / 'assets').mkdir(exist_ok=True); shutil.copy(TOOLS / 'brand' / 'adwaa-logo.svg', PUB / 'assets' / 'adwaa-logo.svg')
    nlinks = sum(len(p['links']) for p in pages)
    nwords = sum(len(p['words']) for p in pages)
    log(f'الروابط: {nlinks} · الكلمات القابلة للبحث: {nwords}')
    if nwords < N * 5:
        log('⚠️ النص قليل جداً — يبدو أن الـPDF مصدّر كصور، فالبحث والقراءة الصوتية لن يعملا جيداً.')

    topics = cfg.get('topics') or []
    if not topics:
        topics = draft_topics(pages, N)
        cfg['topics'] = topics
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        log(f'⚠️ لم تكن هناك مواضيع — استخرجت {len(topics)} موضوعاً من الفهرس وحفظتها في issue/issue.json. راجع العناوين ثم أعد البناء.')
    for t in topics:
        if not re.fullmatch(r'[a-z0-9-]{1,32}', t['id']) or not (1 <= t['s'] <= t['e'] <= N):
            sys.exit(f'موضوع غير صالح في issue.json: {t}')

    # ---- read-aloud: studio narration with a neural voice (optional) ----
    nar = cfg.get('narration') or {}
    voice = nar.get('voice', 'ar-BH-LailaNeural')
    creds = None if '--no-audio' in sys.argv else speech.load_azure()
    nseg = sum(len(p['say']) for p in pages); nchar = sum(len(s['t']) for p in pages for s in p['say'])
    narration = None
    if creds:
        log(f'القراءة الصوتية: {nseg} مقطع · {nchar:,} حرف · الصوت {voice}')
        new, reused, chars = speech.narrate(pages, str(PUB / 'audio'), voice, nar.get('rate', '-4%'), nar.get('pitch', '0%'), creds, log)
        log(f'تسجيل جديد: {new} مقطع ({chars:,} حرف) · من الذاكرة: {reused}')
        narration = {'voice': voice, 'name': nar.get('name') or voice.split('-')[-1].replace('Neural', '')}
    elif (PUB / 'audio').exists() and '--no-audio' not in sys.argv:
        log('لا يوجد مفتاح Azure — القراءة الصوتية ستستخدم صوت جهاز القارئ (السابق محفوظ في public/audio لكن لن يُستخدم)')
    else:
        log(f'القراءة الصوتية بصوت جهاز القارئ ({nseg} مقطع). للصوت الاحترافي أضف مفتاح Azure — راجع README.')

    dl = cfg.get('download_name') or f'Adwaa-{cfg["number"]}.pdf'
    if skip_img and (PUB / dl).exists():
        log(f'ملف التحميل موجود: {dl}')
    else:
      log('ضغط ملف التحميل…')
      small = fitz.open(pdf)
      try:
          small.rewrite_images(dpi_threshold=130 if archived else 170, dpi_target=110 if archived else 150, quality=66 if archived else 78)
          small.subset_fonts()
      except Exception as e:
          log(f'(تخطّي الضغط: {e})')
      small.ez_save(PUB / dl, garbage=4, deflate=True)
      log(f'{dl}: {os.path.getsize(PUB / dl) / 1e6:.1f} MB (الأصلي {os.path.getsize(pdf) / 1e6:.1f} MB)')

    make_og(PUB / 'hi' / 'h01.webp', PUB / 'og-cover.jpg', cfg.get('label', ''))

    site = (cfg.get('site_url') or 'https://PROJECT-ID.web.app').rstrip('/')
    if archived: site += f"/archive/{cfg['id']}"
    # guess-the-colleague: the child's photo, cropped once from the page for the game card
    g = cfg.get('guess') or {}
    if g.get('photo') and (PUB / 'hi' / f"h{g['page']:02d}.webp").exists():
        im = Image.open(PUB / 'hi' / f"h{g['page']:02d}.webp"); x, y, w, h = g['photo']
        im.crop((round(x * im.width), round(y * im.height), round((x + w) * im.width), round((y + h) * im.height))).save(PUB / 'photos' / 'guess.webp', 'WEBP', quality=85)
        g = dict(g, img='photos/guess.webp')
    # past issues (tools/archive.py) — only those whose files are really in public/archive
    reg = ROOT / 'issue' / 'archive.json'
    archive = [a for a in (json.loads(reg.read_text(encoding='utf-8')) if reg.exists() else [])
               if a.get('id') != cfg['id'] and (ROOT / 'public' / a['path'] / 'index.html').exists()]
    if archive: log(f'الأعداد السابقة: {len(archive)}')
    issue = {'id': cfg['id'], 'number': cfg['number'], 'label': cfg['label'], 'topics': topics, 'narration': narration, 'sections': cfg.get('sections') or [],
             'feedback_url': cfg.get('feedback_url') or '', 'guess': g or None, 'archive': [] if archived else archive,
             'archived': archived, 'cover': f'pages/p01.webp'}
    data = {'w': W, 'h': H, 'pages': pages}
    tpl = (TOOLS / 'template.html').read_text(encoding='utf-8')
    lib = (TOOLS / 'vendor' / 'page-flip.patched.js').read_text(encoding='utf-8')
    js = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':')).replace('�', '').replace('</', '<\\/')
    html = (tpl.replace('/*PAGEFLIP*/', lib)
               .replace('/*DATA*/', js(data))
               .replace('/*ISSUE*/', js(issue))
               .replace('__ISSUE_TITLE__', cfg['title'])
               .replace('__ISSUE_LABEL__', cfg['label'])
               .replace('__PDF__', dl)
               .replace('__SITE_URL__', site))
    (PUB / 'index.html').write_text(html, encoding='utf-8')
    if archived:   # list it on the library shelf of the current issue
        reg = [a for a in (json.loads(reg.read_text(encoding='utf-8')) if reg.exists() else []) if a['id'] != cfg['id']]
        reg.append({'id': cfg['id'], 'number': cfg['number'], 'label': cfg['label'], 'path': f"archive/{cfg['id']}/", 'cover': f"archive/{cfg['id']}/pages/p01.webp"})
        reg.sort(key=lambda a: -(a.get('number') or 0))
        reg_path = ROOT / 'issue' / 'archive.json'
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding='utf-8')
        log('أُضيف إلى مكتبة الأعداد (issue/archive.json) — أعد بناء العدد الحالي ليظهر على الرف')
    log(f'المواضيع: {len(topics)} · الحجم الكلي: {sum(f.stat().st_size for f in PUB.rglob("*") if f.is_file()) / 1e6:.1f} MB')
    print(f'\n✓ جاهز خلال {time.time() - t0:.0f} ثانية. للنشر: ارفع التغييرات لـGitHub (git push) وVercel ينشرها تلقائياً خلال دقيقة\n')


if __name__ == '__main__':
    main()
