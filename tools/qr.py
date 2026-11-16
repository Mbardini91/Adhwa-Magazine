"""رمز QR للنسخة المطبوعة — يفتح المجلة ويُحسب في الإحصائيات كمصدر «qr».

    python tools/qr.py                 # يستخدم site_url من issue/issue.json
    python tools/qr.py --page 72       # يفتح على صفحة محددة (مثلاً لعبة «هل تستطيع التعرف على زميلك؟»)
    python tools/qr.py --via poster    # مصدر مختلف (ملصق، شاشة استقبال…) يطلع منفصل في الإحصائيات

الناتج في issue/print/: SVG (للطباعة، متجه) و PNG (للمعاينة). اللون كحلي الهوية على أبيض.
"""
import argparse, json
from pathlib import Path
import segno

ROOT = Path(__file__).resolve().parent.parent
cfg = json.loads((ROOT / 'issue' / 'issue.json').read_text(encoding='utf-8'))
ap = argparse.ArgumentParser()
ap.add_argument('--via', default='qr'); ap.add_argument('--page', type=int); ap.add_argument('--url')
a = ap.parse_args()
site = (a.url or cfg.get('site_url') or '').rstrip('/')
if not site or 'PROJECT-ID' in site:
    raise SystemExit('⚠️ اكتب رابط الموقع الحقيقي في site_url داخل issue/issue.json (أو مرّره: --url https://…)')
url = f'{site}/?via={a.via}' + (f'#page-{a.page}' if a.page else '')
out = ROOT / 'issue' / 'print'; out.mkdir(parents=True, exist_ok=True)
name = f"qr-{cfg['id']}-{a.via}" + (f'-p{a.page}' if a.page else '')
q = segno.make(url, error='q')
q.save(out / f'{name}.svg', dark='#0b1630', light='#ffffff', border=2, scale=10, xmldecl=False)
q.save(out / f'{name}.png', dark='#0b1630', light='#ffffff', border=2, scale=20)
print(f'✓ {url}\n  ← issue/print/{name}.svg  (+ png)')
