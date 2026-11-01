"""Extract reading-order words (with boxes) from an Arabic InDesign PDF.
Per line: glyph clusters sorted by visual x (right→left for Arabic lines), LTR runs
(digits / Latin) restored, lam-alef ligatures repaired, kashida removed."""
import re, unicodedata
AL = 'اأإآ'
MARK = re.compile('[ً-ٰٟۖ-ۭ]')
AR = re.compile('[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]')
def is_ltr(c):
    return c.isdigit() or ('A' <= c <= 'Z') or ('a' <= c <= 'z') or c in '@&_'
def page_words(p, W, H):
    words = []
    for bi, b in enumerate(p.get_text('rawdict')['blocks']):
        for li, l in enumerate(b.get('lines', [])):
            chars = [c for s in l['spans'] for c in s['chars'] if c['c'] != 'ـ']
            if not chars: continue
            arabic = any(AR.match(c['c']) for c in chars)
            # clusters: base + following combining marks (stream order)
            cl = []
            for c in chars:
                if MARK.match(c['c']) and cl: cl[-1]['t'] += c['c']; continue
                x0, y0, x1, y1 = c['bbox']
                cl.append({'t': c['c'], 'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1, 'cx': (x0 + x1) / 2})
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
