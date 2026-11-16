"""أرشفة العدد الحالي قبل استبداله بعدد جديد.

    python tools/archive.py              # ينسخ الموقع الحالي (public/) إلى public/archive/<id>/
    python tools/archive.py --from-git <commit>   # يؤرشف عدداً من تاريخ git (لو نسيت تؤرشفه قبل)

بعدها حط العدد الجديد وشغّل البناء: قائمة «الأعداد السابقة» تطلع تلقائياً في درج الصفحات.
السجل محفوظ في issue/archive.json (الأحدث أولاً). لحذف عدد من القائمة احذف سطره من الملف.
"""
import json, re, shutil, subprocess, sys, tarfile, io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUB = ROOT / 'public'
REG = ROOT / 'issue' / 'archive.json'
SKIP = {'archive', 'audio-cache'}

BANNER = '''<a href="../../" id="adwaa-archive-bar" style="position:fixed;z-index:99;left:50%;bottom:calc(14px + env(safe-area-inset-bottom));transform:translateX(-50%);display:flex;gap:10px;align-items:center;padding:9px 16px;border-radius:22px;background:rgba(8,18,40,.86);border:1px solid rgba(255,255,255,.18);color:#fff;font:500 13px 'Plex Arabic',system-ui,sans-serif;text-decoration:none;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:0 10px 30px rgba(0,0,0,.35)" dir="rtl">أرشيف · __LABEL__ <span style="opacity:.6">|</span> <b style="color:#7cc4f5;font-weight:500">العدد الأحدث ←</b></a>
'''


def load_reg():
    return json.loads(REG.read_text(encoding='utf-8')) if REG.exists() else []


def register(meta, dest):
    reg = [r for r in load_reg() if r['id'] != meta['id']]
    rel = dest.relative_to(PUB).as_posix() + '/'
    reg.append({'id': meta['id'], 'number': meta.get('number'), 'label': meta['label'], 'path': rel, 'cover': rel + 'thumbs/t01.webp'})
    reg.sort(key=lambda r: -(r.get('number') or 0))
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding='utf-8')


def finish(dest, meta):
    idx = dest / 'index.html'
    html = idx.read_text(encoding='utf-8')
    if 'adwaa-archive-bar' not in html:
        html = html.replace('</body>', BANNER.replace('__LABEL__', meta['label']) + '</body>', 1)
    # an archived issue must not be indexed as the current one, nor installed as the app
    html = re.sub(r'<link rel="manifest"[^>]*>', '', html)
    if 'name="robots"' not in html:
        html = html.replace('<head>', '<head>\n<meta name="robots" content="noindex">', 1)
    idx.write_text(html, encoding='utf-8')
    register(meta, dest)
    size = sum(f.stat().st_size for f in dest.rglob('*') if f.is_file()) / 1e6
    print(f'✓ أُرشف {meta["label"]} ← public/{dest.relative_to(PUB).as_posix()}/ ({size:.0f} MB)')


def from_public():
    cfg = json.loads((ROOT / 'issue' / 'issue.json').read_text(encoding='utf-8'))
    html = (PUB / 'index.html').read_text(encoding='utf-8')
    m = re.search(r'const CFG = (\{.*?\});\n', html)
    meta = json.loads(m.group(1)) if m else cfg          # what's live, not what's being edited
    dest = PUB / 'archive' / meta['id']
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for p in PUB.iterdir():
        if p.name in SKIP: continue
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, dest / p.name)
    finish(dest, meta)


def from_git(commit):
    meta = json.loads(subprocess.check_output(['git', 'show', f'{commit}:issue/issue.json'], cwd=ROOT))
    dest = PUB / 'archive' / meta['id']
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True)
    raw = subprocess.check_output(['git', 'archive', '--format=tar', commit, 'public'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for mem in tf.getmembers():
            if not mem.isfile(): continue
            rel = Path(mem.name).relative_to('public')
            if rel.parts[0] in SKIP: continue
            out = dest / rel; out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tf.extractfile(mem).read())
    finish(dest, meta)


if __name__ == '__main__':
    if '--from-git' in sys.argv:
        from_git(sys.argv[sys.argv.index('--from-git') + 1])
    else:
        from_public()
