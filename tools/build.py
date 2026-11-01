#!/usr/bin/env python3
"""
أضواء — بناء الموقع من ملف PDF لعدد جديد
=========================================
الاستخدام (من مجلد المشروع):
    pip install -r tools/requirements.txt
    python tools/build.py

يقرأ issue/issue.json + ملف الـPDF المذكور فيه، ويولّد كل شيء داخل public/:
صفحات المجلة، الصور المصغّرة، نسخة التكبير، البحث، الروابط، المواضيع، ملف التحميل،
صورة المعاينة، و index.html. بعدها: firebase deploy
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

PAGE_W, HI_W, THUMB_W = 1100, 2200, 200


def log(msg):
    print('  ' + msg, flush=True)


def load_issue():
    p = ROOT / 'issue' / 'issue.json'
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


def make_og(cover_path, out_path):
    W, H = 1200, 630
    bg = Image.new('RGB', (W, H), '#0b1630')
    grad = Image.linear_gradient('L').rotate(-60, expand=True).resize((W, H))
    bg = Image.composite(Image.new('RGB', (W, H), '#13264f'), bg, grad)
    glow = Image.new('L', (W, H), 0)
    ImageDraw.Draw(glow).ellipse((-100, -80, 760, 640), fill=70)
    bg = Image.composite(Image.new('RGB', (W, H), '#3a7bbf'), bg, glow.filter(ImageFilter.GaussianBlur(120)))
    cov = Image.open(cover_path).convert('RGB')
    ch = 520; cw = round(cov.width * ch / cov.height)
    cov = cov.resize((cw, ch), Image.LANCZOS)
    sh = Image.new('L', (cw + 120, ch + 120), 0)
    ImageDraw.Draw(sh).rectangle((60, 75, cw + 60, ch + 75), fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(26))
    cx = 110
    bg.paste((3, 8, 20), (cx - 60, (H - ch) // 2 - 60), sh)
    bg.paste(cov, (cx, (H - ch) // 2))
    if features.check('raqm'):
        try:
            f = ImageFont.truetype(str(PUB / 'fonts' / 'plex-arabic-600.woff2'), 128)
            d = ImageDraw.Draw(bg)
            d.text((W - 96, 250), 'أضواء', font=f, fill='white', anchor='rs', direction='rtl')
            f2 = ImageFont.truetype(str(PUB / 'fonts' / 'plex-arabic-400.woff2'), 34)
            d.text((W - 96, 330), 'تصفّح العدد تفاعلياً', font=f2, fill='#c9d4ea', anchor='rs', direction='rtl')
        except Exception:
            pass
    bg.save(out_path, 'JPEG', quality=88)


def main():
    t0 = time.time()
    cfg_path, cfg, pdf = load_issue()
    print(f'\nأضواء — بناء {cfg["title"]}')
    doc = fitz.open(pdf)
    N = len(doc)
    W, H = doc[0].rect.width, doc[0].rect.height
    names = doc.resolve_names()

    for d in ('pages', 'hi', 'thumbs'):
        shutil.rmtree(PUB / d, ignore_errors=True)
        (PUB / d).mkdir(parents=True)
    for old in PUB.glob('*.pdf'):
        old.unlink()

    log(f'{N} صفحة — تجهيز الصور…')
    pages = []
    for i, p in enumerate(doc):
        pix = p.get_pixmap(matrix=fitz.Matrix(HI_W / p.rect.width, HI_W / p.rect.width), alpha=False)
        im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        n = f'{i + 1:02d}'
        im.save(PUB / 'hi' / f'h{n}.webp', 'WEBP', quality=80, method=4)
        im.resize((PAGE_W, round(PAGE_W * im.height / im.width)), Image.LANCZOS).save(PUB / 'pages' / f'p{n}.webp', 'WEBP', quality=80, method=6)
        im.resize((THUMB_W, round(THUMB_W * im.height / im.width)), Image.LANCZOS).save(PUB / 'thumbs' / f't{n}.webp', 'WEBP', quality=75)
        pages.append({'links': resolve_links(doc, p, W, H, names), 'words': page_words(p, W, H)})
        print(f'\r  صفحة {i + 1}/{N}', end='', flush=True)
    print()
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

    dl = cfg.get('download_name') or f'Adwaa-{cfg["number"]}.pdf'
    log('ضغط ملف التحميل…')
    small = fitz.open(pdf)
    try:
        small.rewrite_images(dpi_threshold=170, dpi_target=150, quality=78)
        small.subset_fonts()
    except Exception as e:
        log(f'(تخطّي الضغط: {e})')
    small.ez_save(PUB / dl, garbage=4, deflate=True)
    log(f'{dl}: {os.path.getsize(PUB / dl) / 1e6:.1f} MB (الأصلي {os.path.getsize(pdf) / 1e6:.1f} MB)')

    make_og(PUB / 'hi' / 'h01.webp', PUB / 'og-cover.jpg')

    site = (cfg.get('site_url') or 'https://PROJECT-ID.web.app').rstrip('/')
    issue = {'id': cfg['id'], 'number': cfg['number'], 'label': cfg['label'], 'topics': topics}
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
    log(f'المواضيع: {len(topics)} · الحجم الكلي: {sum(f.stat().st_size for f in PUB.rglob("*") if f.is_file()) / 1e6:.1f} MB')
    print(f'\n✓ جاهز خلال {time.time() - t0:.0f} ثانية. للنشر:  firebase deploy\n')


if __name__ == '__main__':
    main()
