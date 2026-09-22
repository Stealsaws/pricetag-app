#!/usr/bin/env python3
"""
extract_template.py — pull a template config (background image + text-box
positions/styles) out of a RIKIRIKI sign .docx file, in the same format
used by data/templates.json.

WHY THIS EXISTS
----------------
When this app was first built, 16 .docx sign templates were converted by
hand-in-code into data/templates.json. This script packages that same
logic so a FUTURE batch of new templates can be processed the same way,
instead of starting from scratch. It is NOT fully hands-off for every
possible layout — see the "KNOWN LIMITATION" note below — but it gets you
90% of the way for any template that follows the same pattern as the
original 16 (one design, text boxes anchored with `positionV
relativeFrom="paragraph"`, all in a single body paragraph).

WHAT IT DOES
------------
1. Unzips the .docx into a scratch folder.
2. Reads the page size (mm) from <w:sectPr>/<w:pgSz>.
3. Walks every <wp:anchor> in the document body (and its header/footer, for
   the background picture) and pulls out:
     - pictures  -> the background image + its position/size
     - text boxes -> position/size/font-size/color/bold/alignment/text
     - simple shapes (ellipse/rect/etc) -> decorations (e.g. the ":-" mark)
4. Auto-classifies each text box into a `role` (productName, description,
   price, oldPrice, dateRange, disclaimer, static, or an UNKNOWN-* role if
   nothing matches) using the same text-pattern heuristics the original 16
   templates used. Adjust CLASSIFY_RULES below if a new template's
   placeholder text doesn't fit the existing patterns.
5. Copies the background image into <app>/assets/bg/<template-id>.<ext>.
6. Writes a single-template JSON snippet you can merge into
   data/templates.json by hand (or pass --merge to do it automatically).

USAGE
-----
    python3 extract_template.py path/to/Sign-E-01_A3_....docx \
        --template-id E-01 \
        --category E --category-label "หมวดใหม่" \
        --size-code 01 --size-label "A3 ตั้ง" \
        --app-dir ../pricetag-app \
        --merge

Run with --help for all options.

KNOWN LIMITATION — "2-up" / multi-copy layouts (e.g. A5 printing 2 signs
per A4 sheet)
----------------------------------------------------------------------
Word stores a text box's vertical position as an offset from its OWN
paragraph, not from the page. That's fine when the whole design lives in
ONE paragraph (true for most single-sign templates). But a template that
repeats the same design twice on one page usually puts each copy in its
OWN paragraph, and this script has no way to know how tall the first
paragraph rendered on screen — so the offsets it extracts for the second
copy will be wrong (they were for the A5 pair templates in this project
too). If `--units 2` is passed, the script will still extract field
metadata (font/color/text/role) correctly, but WARN you that positions
need to be fixed manually using `grid_overlay.py` (see
ADDING_TEMPLATES.md, step "Manual measurement").
"""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile

import lxml.etree as ET

NSMAP = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wps': 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
}
EMU_PER_MM = 36000.0

# --------------------------------------------------------------------------
# Role classification — edit/extend this if a new template's placeholder
# text doesn't match any existing pattern. Order matters: first match wins.
# --------------------------------------------------------------------------
STATIC_LABELS = {'เพียง'}  # exact-match static (non-editable) design labels


def classify(text, is_bold, n_paragraphs):
    text = text.strip()
    if text in STATIC_LABELS:
        return 'static'
    if text.startswith('วันที่'):
        return 'dateRange'
    if text.startswith('ราคาปกติ'):
        return 'oldPrice'
    if text.startswith('*'):
        return 'disclaimer'
    if text.replace(' ', '').isdigit():
        return 'price'
    if is_bold:
        return 'productName'
    if n_paragraphs >= 1:
        return 'description'
    return 'UNKNOWN-' + re.sub(r'\W+', '', text)[:16]


# --------------------------------------------------------------------------
# OOXML walking (same approach used for the original 16 templates)
# --------------------------------------------------------------------------

def get_rel_map(rels_path):
    rel_map = {}
    if os.path.exists(rels_path):
        for rel in ET.parse(rels_path).getroot():
            rel_map[rel.get('Id')] = rel.get('Target')
    return rel_map


def in_fallback(el):
    p = el.getparent()
    while p is not None:
        if ET.QName(p).localname == 'Fallback':
            return True
        p = p.getparent()
    return False


def extract_shapes(root, rel_map):
    pictures, textboxes, decorations = [], [], []
    for anchor in root.iter('{%s}anchor' % NSMAP['wp']):
        if in_fallback(anchor):
            continue
        posH = anchor.find('wp:positionH/wp:posOffset', NSMAP)
        posV = anchor.find('wp:positionV/wp:posOffset', NSMAP)
        extent = anchor.find('wp:extent', NSMAP)
        if extent is None:
            continue
        x_mm = (int(posH.text) if posH is not None else 0) / EMU_PER_MM
        y_mm = (int(posV.text) if posV is not None else 0) / EMU_PER_MM
        w_mm = int(extent.get('cx')) / EMU_PER_MM
        h_mm = int(extent.get('cy')) / EMU_PER_MM

        blip = anchor.find('.//a:blip', NSMAP)
        txbx = anchor.find('.//wps:txbx', NSMAP)
        prstGeom = anchor.find('.//a:prstGeom', NSMAP)

        if blip is not None:
            rid = blip.get('{%s}embed' % NSMAP['r'])
            pictures.append({'media': rel_map.get(rid), 'x_mm': x_mm, 'y_mm': y_mm, 'w_mm': w_mm, 'h_mm': h_mm})
            continue

        if txbx is not None:
            paras = []
            for p in txbx.findall('.//w:p', NSMAP):
                jc = p.find('.//w:jc', NSMAP)
                align = jc.get('{%s}val' % NSMAP['w']) if jc is not None else 'left'
                runs = []
                for r in p.findall('w:r', NSMAP):
                    rpr = r.find('w:rPr', NSMAP)
                    sz = rpr.find('w:sz', NSMAP) if rpr is not None else None
                    color = rpr.find('w:color', NSMAP) if rpr is not None else None
                    b = rpr.find('w:b', NSMAP) if rpr is not None else None
                    t = r.find('w:t', NSMAP)
                    runs.append({
                        'text': t.text if t is not None else '',
                        'sz_half_pt': int(sz.get('{%s}val' % NSMAP['w'])) if sz is not None else None,
                        'color': color.get('{%s}val' % NSMAP['w']) if color is not None else None,
                        'bold': b is not None,
                    })
                full_text = ''.join(r['text'] for r in runs)
                if runs:
                    paras.append({'align': align, 'runs': runs, 'text': full_text})
            textboxes.append({'x_mm': x_mm, 'y_mm': y_mm, 'w_mm': w_mm, 'h_mm': h_mm, 'paragraphs': paras})
            continue

        if prstGeom is not None:
            fill = anchor.find('.//a:solidFill/a:srgbClr', NSMAP)
            decorations.append({
                'shape': prstGeom.get('prst'), 'x_mm': x_mm, 'y_mm': y_mm, 'w_mm': w_mm, 'h_mm': h_mm,
                'color': fill.get('val') if fill is not None else None,
            })
    return pictures, textboxes, decorations


def parse_docx(path, extract_dir):
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        z.extractall(extract_dir)
    doc_xml = os.path.join(extract_dir, 'word', 'document.xml')
    rels_xml = os.path.join(extract_dir, 'word', '_rels', 'document.xml.rels')
    root = ET.parse(doc_xml).getroot()
    rel_map = get_rel_map(rels_xml)

    sectPr = root.find('.//w:sectPr', NSMAP)
    pgSz = sectPr.find('w:pgSz', NSMAP)
    pgW_mm = int(pgSz.get('{%s}w' % NSMAP['w'])) / 1440 * 25.4
    pgH_mm = int(pgSz.get('{%s}h' % NSMAP['w'])) / 1440 * 25.4

    body_pics, textboxes, decorations = extract_shapes(root, rel_map)

    all_pics = list(body_pics)
    for href in sectPr.findall('w:headerReference', NSMAP) + sectPr.findall('w:footerReference', NSMAP):
        rid = href.get('{%s}id' % NSMAP['r'])
        target = rel_map.get(rid)
        if not target:
            continue
        hpath = os.path.join(extract_dir, 'word', target)
        if not os.path.exists(hpath):
            continue
        hroot = ET.parse(hpath).getroot()
        hrels_path = os.path.join(extract_dir, 'word', '_rels', os.path.basename(target) + '.rels')
        hp, _, _ = extract_shapes(hroot, get_rel_map(hrels_path))
        all_pics.extend(hp)

    return {
        'page_w_mm': pgW_mm, 'page_h_mm': pgH_mm,
        'pictures': all_pics, 'textboxes': textboxes, 'decorations': decorations,
        'extract_dir': extract_dir,
    }


def build_template_json(data, template_id, category, category_label, size_code, size_label, n_units, bg_dest_rel):
    fields, statics = [], []
    for tb in data['textboxes']:
        text = ''.join(p['text'] for p in tb['paragraphs']).strip()
        is_bold = any(r['bold'] for p in tb['paragraphs'] for r in p['runs'])
        role = classify(text, is_bold, len(tb['paragraphs']))
        r0 = tb['paragraphs'][0]['runs'][0] if tb['paragraphs'] and tb['paragraphs'][0]['runs'] else {}
        item = {
            'role': role,
            'x_mm': round(tb['x_mm'], 2), 'y_mm': round(tb['y_mm'], 2),
            'w_mm': round(tb['w_mm'], 2), 'h_mm': round(tb['h_mm'], 2),
            'fontSizePt': (r0.get('sz_half_pt') or 24) / 2,
            'color': '#' + (r0.get('color') or '000000'),
            'bold': is_bold,
            'align': tb['paragraphs'][0]['align'] if tb['paragraphs'] else 'left',
            'sampleText': text,
            'lines': [p['text'] for p in tb['paragraphs']],
        }
        (statics if role == 'static' else fields).append(item)

    price_color = next((f['color'] for f in fields if f['role'] == 'price'), '#EE0000')
    decos = [{
        'shape': d['shape'], 'x_mm': round(d['x_mm'], 2), 'y_mm': round(d['y_mm'], 2),
        'w_mm': round(d['w_mm'], 2), 'h_mm': round(d['h_mm'], 2),
        'color': ('#' + d['color']) if d['color'] else price_color,
    } for d in data['decorations']]

    bg = data['pictures'][0] if data['pictures'] else {'x_mm': 0, 'y_mm': 0, 'w_mm': data['page_w_mm'], 'h_mm': data['page_h_mm']}

    unit = {
        'background': bg_dest_rel,
        'bg_x_mm': round(bg['x_mm'], 2), 'bg_y_mm': round(bg['y_mm'], 2),
        'bg_w_mm': round(bg['w_mm'], 2), 'bg_h_mm': round(bg['h_mm'], 2),
        'offset_x_mm': 0, 'offset_y_mm': 0,
        'fields': fields, 'statics': statics, 'decorations': decos,
    }

    template = {
        'id': template_id, 'category': category, 'categoryLabel': category_label,
        'sizeCode': size_code, 'sizeLabel': size_label,
        'page_w_mm': round(data['page_w_mm'], 2), 'page_h_mm': round(data['page_h_mm'], 2),
        'isPair': n_units > 1,
        'units': [unit] * n_units,  # placeholder copies; fix offsets by hand if n_units>1 (see docstring)
    }
    return template


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('docx', help='Path to the source .docx template')
    ap.add_argument('--template-id', required=True, help='e.g. E-01')
    ap.add_argument('--category', required=True, help='Category code, e.g. E')
    ap.add_argument('--category-label', required=True, help='Thai label shown in the picker')
    ap.add_argument('--size-code', required=True, help='e.g. 01')
    ap.add_argument('--size-label', required=True, help='e.g. "A3 ตั้ง"')
    ap.add_argument('--units', type=int, default=1, help='How many sign copies per page (2 for an A5 pair-style sheet)')
    ap.add_argument('--app-dir', default='../pricetag-app', help='Path to the pricetag-app folder')
    ap.add_argument('--scratch-dir', default='/tmp/extract_template_scratch')
    ap.add_argument('--merge', action='store_true', help='Merge the result straight into data/templates.json')
    args = ap.parse_args()

    data = parse_docx(args.docx, os.path.join(args.scratch_dir, args.template_id))

    bg_src = os.path.join(data['extract_dir'], 'word', data['pictures'][0]['media']) if data['pictures'] else None
    bg_dest_rel = None
    if bg_src and os.path.exists(bg_src):
        ext = os.path.splitext(bg_src)[1]
        bg_dest_rel = f'assets/bg/{args.template_id}{ext}'
        dest_path = os.path.join(args.app_dir, bg_dest_rel)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy(bg_src, dest_path)
        print(f'[ok] background copied -> {dest_path}')
    else:
        print('[warn] no background picture found — check the docx structure', file=sys.stderr)

    template = build_template_json(
        data, args.template_id, args.category, args.category_label,
        args.size_code, args.size_label, args.units, bg_dest_rel,
    )

    unknown_roles = [f['role'] for f in template['units'][0]['fields'] if f['role'].startswith('UNKNOWN-')]
    if unknown_roles:
        print(f'[warn] {len(unknown_roles)} text box(es) did not match any known role: {unknown_roles}', file=sys.stderr)
        print('       -> add a rule to classify() in this script, or rename the role by hand in the JSON.', file=sys.stderr)

    if args.units > 1:
        print('[warn] --units > 1: field Y-positions for copies after the first are almost certainly', file=sys.stderr)
        print('       wrong (see the docstring\'s "KNOWN LIMITATION" section). Measure them manually', file=sys.stderr)
        print('       with grid_overlay.py against a LibreOffice-rendered PNG, then edit the JSON.', file=sys.stderr)

    out_path = f'{args.template_id}.template.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    print(f'[ok] wrote {out_path}')

    if args.merge:
        templates_path = os.path.join(args.app_dir, 'data', 'templates.json')
        with open(templates_path, encoding='utf-8') as f:
            all_templates = json.load(f)
        all_templates[args.template_id] = template
        with open(templates_path, 'w', encoding='utf-8') as f:
            json.dump(all_templates, f, ensure_ascii=False, indent=2)
        print(f'[ok] merged into {templates_path}')


if __name__ == '__main__':
    main()
