"""Read-aloud script for each page + optional studio narration (Azure AI Speech).

segments(words) → the spoken script of a page: headings, paragraphs and sentences in
reading order, page furniture removed, text cleaned for a voice, with the word index of
every spoken word so the reader can highlight along.

narrate(...) → pre-renders every segment with a neural voice (e.g. ar-BH-LailaNeural),
cached by content hash, so rebuilding an issue costs nothing for unchanged text.
"""
import hashlib, os, re, time, urllib.error, urllib.request
from xml.sax.saxutils import escape

MARKS = re.compile('[\u064B-\u065F\u0670\u0640\u200B-\u200F\uFFFD\u00AD]')
QUOTES = re.compile('[\\[\\]«»“”"„()]')
PUNCT_ONLY = re.compile(r'^[\u060C\u061B\u061F.,:;!?\u2026\-–—]+$')
END = re.compile(r'[.\u061F?!\u061B:\u2026]$')
AR = re.compile('[\u0600-\u06FF]')
LAT = re.compile('[A-Za-z]')


def _bt(words):
    bt = {}
    for w in words:
        bt.setdefault(w[5] // 1000, []).append(w[0])
    return {b: ' '.join(v).strip() for b, v in bt.items()}


def _junk(s):
    s2 = s.replace(' ', '')
    return (re.match(r'^[\[\]]|[\[\]]$', s) and len(s) < 30) or re.fullmatch(r'[\d\s.\-–|/]+', s) or len(s2) < 3


def segments(words):
    bt = _bt(words)
    out, cur, blk, length = [], None, None, 0

    def flush():
        nonlocal cur, length
        if cur and cur['i']:
            text, offs, idx = '', [], []
            for i in cur['i']:
                w = QUOTES.sub('', MARKS.sub('', words[i][0])).strip()
                if not w:
                    continue
                if PUNCT_ONLY.match(w) and text:
                    text += w; continue
                w = re.sub(r'^[\u060C,.:;]+', '', w)          # stray leading punctuation from RTL wrap
                if not w:
                    continue
                if text:
                    text += ' '
                offs.append(len(text)); idx.append(i); text += w
            text = re.sub(r'\s+', ' ', text).strip()
            letters = len(re.findall('[\u0600-\u06FFA-Za-z]', text))
            if letters > 3:
                lat = len(LAT.findall(text)); ar = len(AR.findall(text))
                seg = {'i': idx, 'o': offs, 't': text, 'k': 's'}
                if lat > ar:
                    seg['l'] = 'en'
                out.append(seg)
        cur, length = None, 0

    for i, w in enumerate(words):
        b = w[5] // 1000
        if _junk(bt[b]):
            continue
        if b != blk:
            prev, blk = blk, b
            if cur:
                last = words[cur['i'][-1]][0]
                heading = prev is not None and len(bt[prev]) < 60 and all(words[j][5] // 1000 == prev for j in cur['i'])
                n0 = len(out)
                if heading:
                    flush()
                    if len(out) > n0: out[-1]['k'] = 'h'
                elif END.search(last):
                    flush()
                    if len(out) > n0: out[-1]['k'] = 'p'
            elif out and out[-1]['k'] == 's':
                out[-1]['k'] = 'p'
        if cur is None:
            cur = {'i': []}
        cur['i'].append(i); length += len(w[0]) + 1
        if (END.search(w[0]) and length > 40) or (length > 230 and re.search('[\u060C,]$', w[0])) or length > 320:
            flush()
    flush()
    if out and out[-1]['k'] == 's':
        out[-1]['k'] = 'p'
    return out


# ---------------------------------------------------------------- narration
def load_azure():
    """Key/region from the environment or from azure.env at the project root (never committed)."""
    key, region = os.environ.get('AZURE_SPEECH_KEY'), os.environ.get('AZURE_SPEECH_REGION')
    env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'azure.env')
    if (not key or not region) and os.path.exists(env):
        for line in open(env, encoding='utf-8'):
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1); k, v = k.strip(), v.strip().strip('"\'')
                if k == 'AZURE_SPEECH_KEY': key = key or v
                if k == 'AZURE_SPEECH_REGION': region = region or v
    if key and region and 'PASTE' not in key:
        return key, region
    return None


def _ssml(text, voice, rate, pitch):
    lang = '-'.join(voice.split('-')[:2])
    return (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{lang}'>"
            f"<voice name='{voice}'><prosody rate='{rate}' pitch='{pitch}'>{escape(text)}</prosody></voice></speak>")


def synth(text, voice, rate, pitch, key, region):
    url = f'https://{region}.tts.speech.microsoft.com/cognitiveservices/v1'
    body = _ssml(text, voice, rate, pitch).encode('utf-8')
    for attempt in range(6):
        req = urllib.request.Request(url, data=body, method='POST', headers={
            'Ocp-Apim-Subscription-Key': key,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3',
            'User-Agent': 'adwaa-magazine-build'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = float(e.headers.get('Retry-After') or 0) or (4 * (attempt + 1))
                time.sleep(wait); continue
            if e.code in (401, 403):
                raise SystemExit('مفتاح Azure غير صحيح أو المنطقة (region) غير مطابقة — راجع azure.env')
            raise SystemExit(f'Azure رفض الطلب ({e.code}): {e.read()[:300]!r}')
        except urllib.error.URLError as e:
            time.sleep(3 * (attempt + 1))
    raise SystemExit('تعذّر الاتصال بـ Azure بعد عدة محاولات')


def narrate(pages, out_dir, voice, rate, pitch, creds, log, delay=None):
    """Render every segment to public/audio/<hash>.mp3 and set seg['a']. Returns (new, reused, chars)."""
    key, region = creds
    os.makedirs(out_dir, exist_ok=True)
    delay = float(os.environ.get('AZURE_SPEECH_DELAY', delay if delay is not None else 3.2))  # free tier ≈ 20 req/min
    wanted, new, reused, chars = set(), 0, 0, 0
    todo = [s for p in pages for s in p['say']]
    for k, s in enumerate(todo):
        v = voice
        h = hashlib.sha1(f'{v}|{rate}|{pitch}|{s["t"]}'.encode('utf-8')).hexdigest()[:16]
        name = f'{h}.mp3'; path = os.path.join(out_dir, name); wanted.add(name)
        if not os.path.exists(path) or os.path.getsize(path) < 200:
            data = synth(s['t'], v, rate, pitch, key, region)
            open(path, 'wb').write(data); new += 1; chars += len(s['t'])
            print(f'\r  تسجيل صوتي {k + 1}/{len(todo)}', end='', flush=True)
            if delay: time.sleep(delay)
        else:
            reused += 1
        s['a'] = 'audio/' + name
    print()
    for f in os.listdir(out_dir):
        if f.endswith('.mp3') and f not in wanted:
            os.remove(os.path.join(out_dir, f))
    return new, reused, chars
