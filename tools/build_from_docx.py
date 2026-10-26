#!/usr/bin/env python3
"""
build_from_docx.py — build data/templates.json entries from RIKIRIKI sign .docx files
using the *rendered* layout instead of Word's XML offsets.

Why: Word stores text-box positions relative to their paragraph/margins, which
turned out unreliable (top-margin, 2-up pages, autofit...). Rendering the docx to PDF
with LibreOffice gives exact page-absolute positions for everything, so this tool:

 1. copies the docx and replaces every text box's placeholder text with a unique
    ASCII token (N1/N2 name, D1/D2 description, O1 old price, T1 date, C1 disclaimer,
    S1 static label; the price digits are kept);
 2. converts it to PDF with LibreOffice (custom fonts must be installed first);
 3. reads token positions / font sizes / colours / baselines from the PDF with
    pdfplumber, plus the page images (background placement) and filled vector
    shapes (the ":-" dash + dot);
 4. writes a template entry in the app's JSON format (mm units, page-absolute for
    single signs, unit-local for 2-up sheets).

Usage:
  python3 build_from_docx.py --docx Sign-E-01.docx --id E-01 \
      --category E --category-label "1 ซื้อ 1 แถม 1" \
      --size-code 01 --size-label "A3 ตั้ง" --app-dir .. --merge
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, zipfile
import lxml.etree as ET
import pdfplumber
from fontTools.ttLib import TTFont

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
NS = {'w': W, 'wp': WP}
PT_MM = 25.4 / 72.0
LINE_H = 1.08   # must match .sign-field line-height in css/style.css
STATIC_LABELS = {'เพียง'}


def classify(text, bold):
    t = text.strip()
    if t in STATIC_LABELS: return 'static'
    if t.startswith('วันที่'): return 'dateRange'
    if t.startswith('ราคาปกติ'): return 'oldPrice'
    if t.startswith('*'): return 'disclaimer'
    if t.replace(' ', '').isdigit(): return 'price'
    return 'productName' if bold else 'description'

TOKEN = {'productName': 'N', 'description': 'D', 'oldPrice': 'O', 'dateRange': 'T',
         'disclaimer': 'C', 'static': 'S'}


def tokenise(docx_in, docx_out):
    """Return list of textbox info dicts (role, lines, align, width_pt) and write tokenised docx."""
    zin = zipfile.ZipFile(docx_in)
    root = ET.fromstring(zin.read('word/document.xml'))
    infos = []
    for tc in root.iter('{%s}txbxContent' % W):
        paras = tc.findall('.//w:p', NS)
        texts = [''.join(t.text or '' for t in p.iter('{%s}t' % W)) for p in paras]
        full = ''.join(texts)
        if not full.strip():
            continue
        bold = any(r.find('w:rPr/w:b', NS) is not None for r in tc.iter('{%s}r' % W))
        role = classify(full, bold)
        jc = paras[0].find('.//w:jc', NS)
        align = jc.get('{%s}val' % W) if jc is not None else 'left'
        anchor = tc
        wpt = None
        while anchor is not None and ET.QName(anchor).localname != 'anchor':
            anchor = anchor.getparent()
        if anchor is not None:
            ext = anchor.find('wp:extent', NS)
            if ext is not None: wpt = int(ext.get('cx')) / 12700.0
        in_fallback = False
        a = tc
        while a is not None:
            if ET.QName(a).localname == 'Fallback': in_fallback = True
            a = a.getparent()
        if role != 'price':
            k = 0
            for p, txt in zip(paras, texts):
                if not txt.strip(): continue
                k += 1
                ts = list(p.iter('{%s}t' % W))
                for i, t in enumerate(ts):
                    t.text = f'{TOKEN[role]}{k}' if i == 0 else ''
        if not in_fallback:
            infos.append({'role': role, 'lines': [t for t in texts if t.strip()],
                          'align': align, 'width_pt': wpt, 'bold': bold})
    xml = ET.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(docx_out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = xml if item.filename == 'word/document.xml' else zin.read(item.filename)
            zout.writestr(item.filename, data)
    return infos, zin


def to_pdf(docx, outdir):
    subprocess.run(['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', outdir, docx],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=True)
    return os.path.join(outdir, os.path.splitext(os.path.basename(docx))[0] + '.pdf')


def hexcol(c):
    if c is None: return '#000000'
    if isinstance(c, (int, float)): c = (c, c, c)
    if len(c) == 1: c = (c[0],) * 3
    if len(c) == 4:
        k = c[3]; c = tuple((1 - min(1, x + k)) for x in c[:3])
    return '#%02X%02X%02X' % tuple(int(round(max(0, min(1, x)) * 255)) for x in c[:3])


def font_ad(path):
    f = TTFont(path)
    upm = f['head'].unitsPerEm
    return f['hhea'].ascent / upm, -f['hhea'].descent / upm


def analyse(pdf_path, fonts_dir):
    pdf = pdfplumber.open(pdf_path)
    pg = pdf.pages[0]
    H = pg.height
    ad = {}
    for nm, fn in (('bold', 'FCVisionRounded-Bold.ttf'), ('reg', 'FCVisionRounded-Regular.ttf')):
        ad[nm] = font_ad(os.path.join(fonts_dir, fn))
    imgs = [(i['x0'], i['top'], i['x1'], i['bottom']) for i in pg.images]
    words = pg.extract_words(extra_attrs=['size', 'fontname', 'non_stroking_color'])
    toks = []
    for w in words:
        m = re.fullmatch(r'([NDOTCS])(\d)', w['text'])
        is_price = w['text'].isdigit() and w['size'] > 100
        if not (m or is_price): continue
        ch = next(c for c in pg.chars if abs(c['x0'] - w['x0']) < 0.5 and abs(c['top'] - w['top']) < 0.5)
        base = H - ch['matrix'][5]
        toks.append({'tok': w['text'] if m else 'PRICE', 'x0': w['x0'], 'x1': w['x1'], 'base': base,
                     'size': w['size'], 'bold': 'Bold' in w['fontname'] or 'Heavy' in w['fontname'],
                     'color': hexcol(w['non_stroking_color'])})
    shapes = []
    seen = set()
    for c in pg.curves:
        if not c.get('fill') or c['x1'] - c['x0'] > pg.width * 0.6: continue
        key = tuple(round(v) for v in (c['x0'], c['top'], c['x1'], c['bottom']))
        if key in seen: continue
        seen.add(key)
        shapes.append({'x0': c['x0'], 'y0': c['top'], 'x1': c['x1'], 'y1': c['bottom'],
                       'color': hexcol(c['non_stroking_color'])})
    return {'W': pg.width, 'H': H, 'images': imgs, 'tokens': toks, 'shapes': shapes, 'ad': ad}


def build_units(info, textboxes, bg_rel):
    W_, H_ = info['W'], info['H']
    imgs = sorted(info['images'], key=lambda b: b[1])
    page_is_single = len(imgs) == 1 and imgs[0][2] - imgs[0][0] > W_ * 0.9 and imgs[0][3] - imgs[0][1] > H_ * 0.9
    if page_is_single:
        frames = [(0.0, 0.0, W_, H_)]
    else:
        frames = [(b[0], b[1], b[2], b[3]) for b in imgs]
    units = []
    for (fx0, fy0, fx1, fy1) in frames:
        def inside(cy): return fy0 - 8 <= cy <= fy1 + 8
        toks = [t for t in info['tokens'] if inside(t['base'] - t['size'] * 0.3)]
        fields, statics = [], []
        # group tokens by role letter; multi-line (N1,N2 / D1,D2) share one box
        groups = {}
        for t in toks:
            key = 'PRICE' if t['tok'] == 'PRICE' else t['tok'][0]
            groups.setdefault(key, []).append(t)
        role_of = {'N': 'productName', 'D': 'description', 'O': 'oldPrice', 'T': 'dateRange',
                   'C': 'disclaimer', 'S': 'static', 'PRICE': 'price'}
        for key, ts in groups.items():
            ts.sort(key=lambda t: t['base'])
            role = role_of[key]
            tb = next((b for b in textboxes if b['role'] == role), None)
            align = (tb['align'] if tb else 'right')
            align = {'right': 'right', 'end': 'right', 'center': 'center', 'both': 'left'}.get(align, 'left')
            size = ts[0]['size']
            A, D = info['ad']['bold' if ts[0]['bold'] else 'reg']
            n = len(ts)
            top_pt = ts[0]['base'] - size * (LINE_H / 2 + (A - D) / 2)
            h_pt = n * LINE_H * size
            x0 = min(t['x0'] for t in ts); x1 = max(t['x1'] for t in ts)
            wbox = (tb['width_pt'] - 14.4) if (tb and tb.get('width_pt')) else (x1 - x0) * 1.5
            wbox = max(wbox, x1 - x0 + 4)
            if align == 'right': left = x1 - wbox
            elif align == 'center': left = (x0 + x1) / 2 - wbox / 2
            else: left = x0
            item = {
                'role': role,
                'x_mm': round((left - fx0) * PT_MM, 2), 'y_mm': round((top_pt - fy0) * PT_MM, 2),
                'w_mm': round(wbox * PT_MM, 2), 'h_mm': round(h_pt * PT_MM, 2),
                'fontSizePt': round(size, 1), 'color': ts[0]['color'], 'bold': ts[0]['bold'],
                'align': align,
                'sampleText': ''.join(tb['lines']) if tb else '',
                'lines': tb['lines'] if tb else [],
            }
            (statics if role == 'static' else fields).append(item)
        decos = []
        for s in info['shapes']:
            cx, cy = (s['x0'] + s['x1']) / 2, (s['y0'] + s['y1']) / 2
            if not (fx0 <= cx <= fx1 and inside(cy)): continue
            w_, h_ = s['x1'] - s['x0'], s['y1'] - s['y0']
            decos.append({'shape': 'ellipse' if abs(w_ - h_) / max(w_, h_) < 0.18 else 'roundRect',
                          'x_mm': round((s['x0'] - fx0) * PT_MM, 2), 'y_mm': round((s['y0'] - fy0) * PT_MM, 2),
                          'w_mm': round(w_ * PT_MM, 2), 'h_mm': round(h_ * PT_MM, 2), 'color': s['color']})
        decos.sort(key=lambda d: d['y_mm'])
        bx0, by0, bx1, by1 = imgs[0] if page_is_single else (fx0, fy0, fx1, fy1)
        units.append({
            'background': bg_rel,
            'bg_x_mm': round((bx0 - fx0) * PT_MM, 2) + (round(fx0 * PT_MM, 2)),
            'bg_y_mm': round(by0 * PT_MM, 2), 'bg_w_mm': round((bx1 - bx0) * PT_MM, 2),
            'bg_h_mm': round((by1 - by0) * PT_MM, 2),
            'offset_x_mm': round(fx0 * PT_MM, 2), 'offset_y_mm': round(fy0 * PT_MM, 2),
            'fields': fields, 'statics': statics, 'decorations': decos,
        })
    return units


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--docx', required=True); ap.add_argument('--id', required=True)
    ap.add_argument('--category', required=True); ap.add_argument('--category-label', required=True)
    ap.add_argument('--size-code', required=True); ap.add_argument('--size-label', required=True)
    ap.add_argument('--app-dir', default='..'); ap.add_argument('--merge', action='store_true')
    a = ap.parse_args()
    tmp = tempfile.mkdtemp()
    tok_docx = os.path.join(tmp, 'tok.docx')
    textboxes, zin = tokenise(a.docx, tok_docx)
    info = analyse(to_pdf(tok_docx, tmp), os.path.join(a.app_dir, 'fonts'))
    media = [n for n in zin.namelist() if n.startswith('word/media/')]
    if len(media) != 1:
        print('[warn] expected exactly 1 media file, found', media, file=sys.stderr)
    ext = os.path.splitext(media[0])[1]
    bg_rel = f'assets/bg/{a.id}{ext}'
    os.makedirs(os.path.join(a.app_dir, 'assets/bg'), exist_ok=True)
    open(os.path.join(a.app_dir, bg_rel), 'wb').write(zin.read(media[0]))
    units = build_units(info, textboxes, bg_rel)
    tpl = {'id': a.id, 'category': a.category, 'categoryLabel': a.category_label,
           'sizeCode': a.size_code, 'sizeLabel': a.size_label,
           'page_w_mm': round(info['W'] * PT_MM, 2), 'page_h_mm': round(info['H'] * PT_MM, 2),
           'isPair': len(units) > 1, 'units': units}
    if a.merge:
        p = os.path.join(a.app_dir, 'data', 'templates.json')
        allt = json.load(open(p, encoding='utf-8')); allt[a.id] = tpl
        json.dump(allt, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('[ok] merged', a.id)
    else:
        json.dump(tpl, open(f'{a.id}.template.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('[ok] wrote', f'{a.id}.template.json')
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
