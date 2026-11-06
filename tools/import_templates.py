#!/usr/bin/env python3
"""
import_templates.py — put the output of build_templates.py into this app.

  1. python3 build_templates.py --docx <folder with Sign-X-NN.docx> --pdfs <folder with the PDFs of
        the same files, ideally exported from real Word> --fonts ../fonts --out /tmp/built
  2. python3 import_templates.py --built /tmp/built --docx <same docx folder> --app ..

For every template it (re)writes data/templates.json (existing templates with other ids, e.g. the
shelf talkers, are kept) and copies the background art into assets/bg/. CMYK JPEGs are converted to
sRGB with their embedded ICC profile (browsers show raw CMYK with wrong colours).
New category letters get the label given in CATEGORY_LABELS below (edit it, or pass --label X="ชื่อ").
"""
import argparse, glob, io, json, os, re, zipfile
from PIL import Image, ImageCms

CATEGORY_LABELS = {'A': 'ลดราคา', 'B': 'โปรด่วน', 'C': 'ขายดี', 'D': 'ใหม่', 'E': '1 ซื้อ 1 แถม 1',
                   'F': 'ยกแพ็คสุดคุ้ม', 'G': 'ซื้อคู่ถูกกว่า', 'H': 'ราคาเดียว หมดแล้วหมดเลย'}
SIZE_LABELS = {'01': 'A3 ตั้ง', '02': 'A3 นอน', '03': 'A4 นอน', '04': 'A4 1/3 (2 ใบ/แผ่น A4)'}


def extract_bg(docx, dest_noext):
    z = zipfile.ZipFile(docx)
    media = [n for n in z.namelist() if n.startswith('word/media/')]
    if len(media) != 1:
        print('  [warn]', os.path.basename(docx), 'has', len(media), 'media files; using the first')
    data = z.read(media[0]); ext = os.path.splitext(media[0])[1].lower()
    im = Image.open(io.BytesIO(data))
    if im.mode == 'CMYK':
        icc = im.info.get('icc_profile')
        if icc:
            im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                           ImageCms.createProfile('sRGB'), outputMode='RGB')
        else:
            im = im.convert('RGB')
        im.save(dest_noext + '.jpg', quality=92); return os.path.basename(dest_noext) + '.jpg'
    open(dest_noext + ext, 'wb').write(data); return os.path.basename(dest_noext) + ext


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--built', required=True); ap.add_argument('--docx', required=True)
    ap.add_argument('--app', default='..'); ap.add_argument('--label', action='append', default=[])
    a = ap.parse_args()
    for l in a.label:
        k, v = l.split('=', 1); CATEGORY_LABELS[k] = v
    built = json.load(open(os.path.join(a.built, 'templates.json'), encoding='utf-8'))
    path = os.path.join(a.app, 'data', 'templates.json')
    allt = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
    os.makedirs(os.path.join(a.app, 'assets', 'bg'), exist_ok=True)
    for t in built:
        docx = glob.glob(os.path.join(a.docx, f"Sign-{t['id']}*.docx"))[0]
        fname = extract_bg(docx, os.path.join(a.app, 'assets', 'bg', t['id']))
        t = dict(t); t['category'] = t.pop('set'); t['sizeCode'] = t.pop('size'); t.pop('label', None)
        t['categoryLabel'] = CATEGORY_LABELS.get(t['category'], 'หมวด ' + t['category'])
        t['sizeLabel'] = SIZE_LABELS.get(t['sizeCode'], t['sizeCode'])
        for im in t['images']: im['file'] = 'assets/bg/' + fname
        allt[t['id']] = t
        print('imported', t['id'])
    json.dump(allt, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
