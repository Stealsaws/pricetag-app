#!/usr/bin/env python3
"""
grid_overlay.py — draw a millimetre grid over a rendered sign image so you
can read off field positions by eye and type them straight into
data/templates.json.

This is the fallback for anything extract_template.py can't get right
automatically — most commonly a "2-up" layout (two copies of the same sign
printed on one sheet, e.g. the A5 pair templates in this project), where
Word's own coordinate system doesn't give a reliable page-absolute position.

HOW TO GET A RENDERED IMAGE FROM A .docx
-----------------------------------------
If you have LibreOffice installed:

    libreoffice --headless --convert-to png --outdir ./preview path/to/Sign-....docx

(Install any custom fonts the template uses into ~/.fonts and run
`fc-cache -f` first, or text will render in a fallback font and look
wrong — this doesn't affect print output from real Word/browsers, only
this preview step.)

USAGE
-----
    python3 grid_overlay.py preview/Sign-E-01....png \
        --page-w-mm 297 --page-h-mm 420 --step-mm 10 \
        --out grid_E01.png

Open grid_E01.png, read the mm coordinates directly off the ruled lines
for each field's top-left corner and size, and type those numbers into
the corresponding field's x_mm/y_mm/w_mm/h_mm in templates.json.

For a 2-up sheet, crop first to just one copy with --crop-y-mm (see
--help), so the grid's 0mm lines up with that copy's own top edge —
that's the "unit-local" coordinate templates.json expects for
`offset_x_mm`/`offset_y_mm` plus each field's x_mm/y_mm.
"""
import argparse
from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('image', help='Rendered PNG of the template (e.g. from LibreOffice)')
    ap.add_argument('--page-w-mm', type=float, required=True)
    ap.add_argument('--page-h-mm', type=float, required=True)
    ap.add_argument('--step-mm', type=float, default=10, help='Grid line spacing in mm (default 10)')
    ap.add_argument('--crop-y-mm', type=float, nargs=2, metavar=('TOP', 'BOTTOM'),
                     help='Crop to this mm range first (e.g. one copy of a 2-up sheet). '
                          '0mm in the output grid = TOP.')
    ap.add_argument('--upscale', type=float, default=1.0, help='Resize factor for a bigger, easier-to-read grid')
    ap.add_argument('--out', default='grid_overlay_output.png')
    args = ap.parse_args()

    im = Image.open(args.image).convert('RGB')
    sx = im.size[0] / args.page_w_mm
    sy = im.size[1] / args.page_h_mm

    y_top_mm = 0.0
    if args.crop_y_mm:
        top_mm, bottom_mm = args.crop_y_mm
        y_top_mm = top_mm
        im = im.crop((0, round(top_mm * sy), im.size[0], round(bottom_mm * sy)))

    if args.upscale != 1.0:
        im = im.resize((round(im.width * args.upscale), round(im.height * args.upscale)))
        sx *= args.upscale
        sy *= args.upscale

    draw = ImageDraw.Draw(im)
    w, h = im.size
    mm_w = w / sx
    mm_h = h / sy

    step = args.step_mm
    mm = 0.0
    while mm <= mm_w + 1e-6:
        x = round(mm * sx)
        bold = abs(mm % (step * 2)) < 1e-6
        draw.line([(x, 0), (x, h)], fill=(0, 120, 255), width=2 if bold else 1)
        draw.text((x + 2, 2), str(round(mm)), fill=(0, 0, 160))
        mm += step

    mm = 0.0
    while mm <= mm_h + 1e-6:
        y = round(mm * sy)
        bold = abs(mm % (step * 2)) < 1e-6
        draw.line([(0, y), (w, y)], fill=(0, 200, 0), width=2 if bold else 1)
        draw.text((2, y + 1), str(round(mm + y_top_mm)), fill=(0, 110, 0))
        mm += step

    im.save(args.out)
    print(f'[ok] wrote {args.out}  ({round(mm_w)}mm x {round(mm_h)}mm visible, '
          f'grid every {step}mm, y-labels offset by +{y_top_mm}mm)')


if __name__ == '__main__':
    main()
