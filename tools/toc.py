"""استخراج مواضيع العدد من صفحة «في هذا العدد» (نص الفهرس نفسه، مو الروابط).

    python tools/toc.py issue/archive/2024-q2/issue.json          # يعرض المواضيع
    python tools/toc.py issue/archive/2024-q2/issue.json --write  # ويحفظها في issue.json

يقرأ كل سطر فيه «العنوان.رقم الصفحة»، يتجاهل عناوين الأقسام (عن الهيئة، فريقنا…)، يضم الأسطر المكملة
للعنوان، ويحوّل رقم الصفحة المطبوع إلى رقم صفحة الـPDF بقراءة أرقام التذييل في الصفحات.
"""
import json, re, sys
from collections import Counter
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from words import page_words  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = {'في هذا العدد', 'عن الهيئة', 'فريقنا', 'مقالات', 'من البحرين', 'نتواصل', 'أصداء المنتدى', 'المساهمون'}
STOP = ('فريق العمل', 'المساهمون', 'رئيس التحرير', 'هيئة التحرير')
NUM = re.compile(r'^\.?(\d{1,3})\.?$')


def lines_of(page):
    w = page_words(page, page.rect.width, page.rect.height)
    out, cur, lid = [], [], None
    for t, x, y, ww, hh, l in w:
        if l != lid and cur:
            out.append(cur); cur = []
        lid = l; cur.append(t)
    if cur: out.append(cur)
    return out


def norm(s):
    return re.sub(r'\s+', ' ', s.replace('ـ', '')).strip(' .:،')


def printed_offset(doc):
    """pdf page number − printed page number, read from footers (most common value)."""
    c = Counter()
    for i in range(2, len(doc) - 1):
        p = doc[i]
        for b in p.get_text('words'):
            if b[1] > p.rect.height * .93 and re.fullmatch(r'\d{1,3}', b[4]):
                c[(i + 1) - int(b[4])] += 1
    return c.most_common(1)[0][0] if c else 3


def toc(cfg_path):
    cfg = json.loads(Path(cfg_path).read_text(encoding='utf-8'))
    doc = fitz.open(ROOT / cfg['pdf'])
    N = len(doc)
    page = next(p for p in doc if 'في هذا العدد' in norm(' '.join(' '.join(l) for l in lines_of(p))) or 'هذا العدد' in p.get_text())
    off = printed_offset(doc)
    entries = []
    for toks in lines_of(page):
        text = norm(' '.join(toks))
        if not text: continue
        if any(text.startswith(s) for s in STOP): break
        nums = [m.group(1) for t in toks for m in [NUM.match(t.strip())] if m]
        rest = norm(' '.join(t for t in toks if not NUM.match(t.strip())))
        if nums:
            entries.append({'p': int(nums[0]), 't': rest})
        elif rest in SECTIONS or not entries:
            continue
        else:
            entries[-1]['t'] = norm(entries[-1]['t'] + ' ' + rest)     # wrapped title line
    # same printed page → one topic; printed → pdf page
    topics = []
    for e in entries:
        s = e['p'] + off
        if not 2 < s < N: continue
        t = e['t']
        if len(t) > 48 and '..' in t: t = t.split('..')[0]
        if len(t) > 64: t = t[:62].rsplit(' ', 1)[0] + '…'
        if topics and topics[-1]['s'] == s:
            topics[-1]['t'] += ' · ' + t
        elif not topics or s > topics[-1]['s']:
            topics.append({'s': s, 't': t})
    if topics and topics[0]['s'] > 3:
        topics.insert(0, {'s': 3, 't': 'كلمة الرئيس التنفيذي'})
    for i, tp in enumerate(topics):
        tp['e'] = (topics[i + 1]['s'] - 1) if i + 1 < len(topics) else N - 1
        tp['id'] = 'ceo-word' if tp['t'] == 'كلمة الرئيس التنفيذي' else f't{i + 1:02d}'
    return cfg, [{'id': t['id'], 's': t['s'], 'e': t['e'], 't': t['t']} for t in topics], off


if __name__ == '__main__':
    path = sys.argv[1]
    cfg, topics, off = toc(path)
    print(f'{cfg["label"]} · فرق الترقيم {off}')
    for t in topics: print(f"  {t['s']:>3}–{t['e']:<3} {t['t']}")
    if '--write' in sys.argv:
        cfg['topics'] = topics
        Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        print('✓ حُفظت')
