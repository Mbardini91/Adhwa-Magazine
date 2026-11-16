"""Extract reading-order words (with boxes) from an Arabic InDesign PDF.
Per line: glyph clusters sorted by visual x (right→left for Arabic lines), LTR runs
(digits / Latin) restored, lam-alef ligatures repaired, kashida removed."""
import re, unicodedata
AL = 'اأإآ'
PRES = re.compile('[\uFB50-\uFDFF\uFE70-\uFEFF]')
MARK = re.compile('[ً-ٰٟۖ-ۭ]')
AR = re.compile('[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]')
def is_ltr(c):
    return c.isdigit() or ('A' <= c <= 'Z') or ('a' <= c <= 'z') or c in '@&_'
def page_words(p, W, H):
    words = []
    for bi, b in enumerate(p.get_text('rawdict')['blocks']):
        for li, l in enumerate(b.get('lines', [])):
            chars = [c for s in l['spans'] for c in s['chars']]
            if not chars: continue
            arabic = any(AR.match(c['c']) for c in chars)
            # phantom spaces: InDesign sometimes emits a space *inside* a glyph (next to an unmapped
            # ligature, U+FFFD). A real word gap never overlaps a glyph, so drop those.
            glyphs = [c['bbox'] for c in chars if not c['c'].isspace() and c['bbox'][2] - c['bbox'][0] > .05]
            def phantom(c):
                x0, x1 = c['bbox'][0], c['bbox'][2]; w = max(x1 - x0, .01)
                return any(min(x1, g[2]) - max(x0, g[0]) > .5 * w for g in glyphs)
            # clusters: base + following combining marks; a mark goes to the last real letter
            # (never to a kashida, a space or an unmapped glyph)
            cl, last = [], None
            for c in chars:
                ch = c['c']
                if MARK.match(ch):
                    if last is not None: last['t'] += ch
                    continue
                if ch in 'ـ�': continue
                if ch.isspace() and phantom(c): continue
                x0, y0, x1, y1 = c['bbox']
                k = {'t': ch, 'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1, 'cx': (x0 + x1) / 2}
                cl.append(k)
                if not ch.isspace(): last = k
            if arabic:
                cl.sort(key=lambda k: -k['cx'])
                # restore LTR runs (digits/latin, with inner . , : - / % between them)
                out, i = [], 0
                while i < len(cl):
                    if is_ltr(cl[i]['t'][0]):
                        j = i
                        while j + 1 < len(cl) and (is_ltr(cl[j+1]['t'][0]) or (cl[j+1]['t'] in '.,:-/%' and j + 2 < len(cl) and is_ltr(cl[j+2]['t'][0]))):
                            j += 1
                        out.extend(reversed(cl[i:j+1])); i = j + 1
                    else:
                        out.append(cl[i]); i += 1
                cl = out
                # lam-alef ligature: zero-width alef placed before its lam → swap
                i = 0
                while i < len(cl) - 1:
                    a, n = cl[i], cl[i+1]
                    if a['t'][0] in AL and n['t'][0] == 'ل' and a['x1'] - a['x0'] < .05:
                        cl[i], cl[i+1] = n, a; i += 2
                    else: i += 1
            else:
                cl.sort(key=lambda k: k['cx'])
            cur = []
            def flush():
                if not cur: return
                t = ''.join(k['t'] for k in cur).strip()
                if AR.search(t): t = re.sub('[\u0100-\u024F\u02B0-\u02FF]', '', t)   # stray Latin glyph stand-ins inside Arabic words
                t = PRES.sub(lambda m: unicodedata.normalize('NFKC', m.group()), t)   # presentation forms (ﺗﻌﺮف) → letters
                if t:
                    x0 = min(k['x0'] for k in cur); x1 = max(k['x1'] for k in cur)
                    y0 = min(k['y0'] for k in cur); y1 = max(k['y1'] for k in cur)
                    words.append([t, round(x0/W, 4), round(y0/H, 4), round((x1-x0)/W, 4), round((y1-y0)/H, 4), bi*1000 + li])
                cur.clear()
            for k in cl:
                if k['t'].isspace(): flush()
                else: cur.append(k)
            flush()
    return words
