#!/usr/bin/env python3
"""
build_templates.py  --  RikiRiki price-sign template builder
------------------------------------------------------------
Reads the Word files (Sign-A-01.docx ... Sign-H-04.docx) and produces
    out/templates.json   exact geometry / sizes / colours of every sign
    out/assets/*.jpg     background art pulled out of each .docx
    out/fonts/*.ttf      FC Vision Rounded (copied from --fonts)
    out/sign_template.html   web template (fill in data -> print at true size)

Exact positions of text boxes depend on how the word processor lays out the
page (paragraph tops, line spacing), so the script is *calibrated* from a PDF
of each .docx (--pdfs).  To calibrate against real Microsoft Word, export each
.docx to PDF from Word (File > Save As > PDF, same file names) and point
--pdfs at that folder.

usage:
  python build_templates.py --docx "<folder with .docx>" --pdfs <folder with .pdf> \
         --fonts <folder with FCVisionRounded-*.ttf> --out out
"""
import argparse, glob, io, json, os, re, shutil, statistics, zipfile
from lxml import etree
import pdfplumber

NS = {
 'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
 'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
 'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
 'wps':'http://schemas.microsoft.com/office/word/2010/wordprocessingShape',
 'mc':'http://schemas.openxmlformats.org/markup-compatibility/2006',
 'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
EMU_PT = 12700.0          # 1 pt = 12700 EMU
TW_PT  = 1/20.0           # 1 twip = 1/20 pt
THEME  = {'text1':'000000','bg1':'FFFFFF','tx1':'000000','dk1':'000000','lt1':'FFFFFF'}
SIZE_LABEL = {'01':'A3 แนวตั้ง','02':'A3 แนวนอน','03':'A4 แนวนอน','04':'A4 1/3 (2 ป้ายต่อแผ่น A4)'}
Q = lambda e,p: e.xpath(p, namespaces=NS)
rnd = lambda v: round(v, 3)

# ---------------------------------------------------------------- docx parse
def para_info(p):
    runs=[]
    for r in Q(p,'w:r'):
        t=''.join(Q(r,'w:t/text()'))
        if t=='' : continue
        rp=Q(r,'w:rPr'); rp=rp[0] if rp else None
        g=(lambda x:Q(rp,x)) if rp is not None else (lambda x:[])
        sz=g('w:sz/@w:val') or g('w:szCs/@w:val')
        col=g('w:color/@w:val'); thm=g('w:color/@w:themeColor')
        c=col[0] if col else None
        if thm and thm[0] in THEME: c=THEME[thm[0]]
        if c in (None,'auto'): c='000000'
        runs.append(dict(t=t,size=(int(sz[0])/2 if sz else 12.0),bold=bool(g('w:b')),color=c))
    pp=Q(p,'w:pPr'); jc=None
    if pp: jc=(Q(pp[0],'w:jc/@w:val') or [None])[0]
    return dict(jc=jc or 'left', runs=runs)

def read_anchors(root, kind):
    out=[]
    paras=Q(root,'.//w:p[not(ancestor::w:txbxContent)]')
    for anc in Q(root,'.//wp:anchor[not(ancestor::mc:Fallback)]'):
        d={}
        pidx=0
        for i,p in enumerate(paras):
            if anc in p.iterdescendants(): pidx=i; break
        d['para_index']=pidx
        for k in ('positionH','positionV'):
            p=Q(anc,'wp:'+k)[0]
            off=Q(p,'wp:posOffset'); al=Q(p,'wp:align')
            d[k]=dict(rel=p.get('relativeFrom'), off=(int(off[0].text)/EMU_PT if off else None), align=(al[0].text if al else None))
        ext=Q(anc,'wp:extent')[0]
        d['w']=int(ext.get('cx'))/EMU_PT; d['h']=int(ext.get('cy'))/EMU_PT
        d['name']=(Q(anc,'wp:docPr/@name') or [''])[0]
        blip=Q(anc,'.//a:blip/@r:embed'); d['blip']=blip[0] if blip else None
        geom=Q(anc,'.//wps:spPr/a:prstGeom/@prst'); d['geom']=geom[0] if geom else None
        fill=Q(anc,'.//wps:spPr/a:solidFill/*/@val'); d['fill']=THEME.get(fill[0],fill[0]) if fill else None
        ln=Q(anc,'.//wps:spPr/a:ln/a:solidFill/*/@val'); d['line']=THEME.get(ln[0],ln[0]) if ln else None
        lnw=Q(anc,'.//wps:spPr/a:ln/@w'); d['line_w']=int(lnw[0])/EMU_PT if lnw else None
        bp=Q(anc,'.//wps:bodyPr')
        d['ins']=[int(bp[0].get(k,def_))/EMU_PT for k,def_ in (('lIns',91440),('tIns',45720),('rIns',91440),('bIns',45720))] if bp else [7.2,3.6,7.2,3.6]
        d['paras']=[para_info(p) for p in Q(anc,'.//wps:txbx//w:p')]
        d['z']=int(anc.get('relativeHeight') or 0)
        out.append(d)
    return out

def parse_docx(path):
    z=zipfile.ZipFile(path)
    doc=etree.fromstring(z.read('word/document.xml'))
    sect=Q(doc,'//w:sectPr')[-1]
    pg=Q(sect,'w:pgSz')[0]; mar=Q(sect,'w:pgMar')[0]
    W=lambda e,k:int(e.get('{%s}%s'%(NS['w'],k)))*TW_PT
    res=dict(page=[W(pg,'w'),W(pg,'h')],
             margin={k:W(mar,k) for k in ('top','left','right','bottom','header')},
             body=read_anchors(doc,'body'),header=[],images={})
    rels=etree.fromstring(z.read('word/_rels/document.xml.rels'))
    hdr=[r.get('Target') for r in rels if r.get('Type').endswith('/header')]
    for h in hdr:
        hp='word/'+h
        hroot=etree.fromstring(z.read(hp))
        hrels=etree.fromstring(z.read('word/_rels/%s.rels'%os.path.basename(h)))
        rmap={r.get('Id'):r.get('Target') for r in hrels}
        for a in read_anchors(hroot,'header'):
            a['media']='word/'+rmap[a['blip']] if a['blip'] in rmap else None
            res['header'].append(a)
    # theme line widths (shape outline referenced by <wps:style><a:lnRef idx>)
    res['_zip']=z
    return res

# ------------------------------------------------------- PDF calibration
def calibrate(spec, pdf_path):
    """absolute positions as laid out by the word processor (taken from a PDF of the docx)"""
    page=pdfplumber.open(pdf_path).pages[0]
    ml=spec['margin']['left']; mt=spec['margin']['top']
    boxes=[(c['x0'],c['top'],c['x1'],c['bottom']) for c in page.curves]
    tops=[]
    def ax(a):
        h=a['positionH']
        if h['off'] is None:
            return 0 if h['align']=='left' else spec['page'][0]-a['w']
        return (0 if h['rel']=='page' else ml)+h['off']
    for a in spec['body']:
        cand=[b for b in boxes if abs((b[2]-b[0])-a['w'])<1.5 and abs((b[3]-b[1])-a['h'])<1.5 and abs(b[0]-ax(a))<1.5]
        if cand:
            b=min(cand,key=lambda b:abs(b[0]-ax(a)))
            a['_pdf_y']=b[1]; a['_para_top']=b[1]-a['positionV']['off']
            tops.append(a['_para_top'])
    body_top=statistics.median(tops) if tops else mt
    # background images exactly as placed in the PDF
    imgs=[dict(x=i['x0'],y=i['top'],w=i['x1']-i['x0'],h=i['bottom']-i['top']) for i in page.images]
    # baselines of every text line of every text box
    H=page.height
    for a in spec['body']:
        if not a['paras']: continue
        x=ax(a); y=a['_pdf_y'] if '_pdf_y' in a else body_top+a['positionV']['off']
        sizes={p['runs'][0]['size'] for p in a['paras'] if p['runs']}
        bolds={p['runs'][0]['bold'] for p in a['paras'] if p['runs']}
        inside=[c for c in page.chars if x-4<=(c['x0']+c['x1'])/2<=x+a['w']+4 and y-4<=c['top']+c['size']*0.5<=y+a['h']+4
                and any(abs(c['size']-z)<0.2 for z in sizes) and (('Bold' in c['fontname']) in bolds)]
        bl=sorted({round(H-c['matrix'][5],1) for c in inside})
        a['_baselines']=bl
        a['_pdf_text_right']=max((c['x1'] for c in inside),default=None)
    return body_top, imgs

# ------------------------------------------------- JPEG: drop ICC profile
def strip_icc(data):
    """Word/LibreOffice show the raw RGB numbers of a JPEG and ignore its embedded ICC profile,
    browsers colour-manage it (-> duller colours).  Remove the ICC (APP2) segment losslessly so the
    browser shows exactly what Word shows.  Pixel data is not touched / re-encoded."""
    if data[:2]!=b'\xff\xd8': return data
    out=bytearray(data[:2]); i=2
    while i<len(data)-1:
        if data[i]!=0xFF: out+=data[i:]; break
        m=data[i+1]
        if m==0xDA: out+=data[i:]; break                      # start of scan: copy the rest
        if m in (0x01,)+tuple(range(0xD0,0xD9)): out+=data[i:i+2]; i+=2; continue
        ln=int.from_bytes(data[i+2:i+4],'big'); seg=data[i:i+2+ln]
        if not (m==0xE2 and seg[4:16]==b'ICC_PROFILE\x00'): out+=seg
        i+=2+ln
    return bytes(out)

# ------------------------------------------------------------ assemble
def role_of(box):
    txt=[''.join(r['t'] for r in p['runs']) for p in box['paras']]
    t0=txt[0].replace(' ','') if txt else ''
    size=max((r['size'] for p in box['paras'] for r in p['runs']),default=0)
    if re.fullmatch(r'[\d,]+',t0) and size>100: return 'price'
    if '299' in t0 and 'ราคาปกติ' in t0: return 'normal'
    if re.search(r'\d\d/\d\d/\d\d',t0): return 'date'
    if len(txt)>=2 and 'มล' in txt[1]: return 'desc'
    if t0.startswith('*'): return 'foot'
    if t0.startswith('เพียง'): return 'only'
    if any(r['bold'] for p in box['paras'] for r in p['runs']): return 'name'
    return 'text'

def build_sign(docx, pdf, set_id, size_id, assets_dir):
    spec=parse_docx(docx)
    body_top, imgs = calibrate(spec,pdf)
    ml=spec['margin']['left']
    sid='%s-%s'%(set_id,size_id)
    # background image(s)
    media=[a['media'] for a in spec['header'] if a['media']][0]
    ext=os.path.splitext(media)[1].lower().replace('.jpeg','.jpg')
    fn='%s%s'%(sid,ext); open(os.path.join(assets_dir,fn),'wb').write(strip_icc(spec['_zip'].read(media)))
    out=dict(id=sid,set=set_id,size=size_id,label=SIZE_LABEL[size_id],page=[rnd(v) for v in spec['page']],
             images=[dict(file=fn,**{k:rnd(v) for k,v in i.items()}) for i in imgs],shapes=[],boxes=[])
    def ax(a):
        h=a['positionH']
        if h['off'] is None: return 0 if h['align']=='left' else spec['page'][0]-a['w']
        return (0 if h['rel']=='page' else ml)+h['off']
    for a in sorted(spec['body'],key=lambda a:a['z']):
        x=ax(a); y=a.get('_pdf_y', body_top+a['positionV']['off'])
        if a['geom'] in ('ellipse','flowChartTerminator'):
            out['shapes'].append(dict(kind='oval' if a['geom']=='ellipse' else 'terminator',x=rnd(x),y=rnd(y),w=rnd(a['w']),h=rnd(a['h']),
                                       fill=a['fill'],stroke=a['line'] or a['fill'],stroke_w=1.5 if a['line_w'] is None else a['line_w'],z=a['z']))
        elif a['paras']:
            b=dict(x=rnd(x),y=rnd(y),w=rnd(a['w']),h=rnd(a['h']),ins=[rnd(v) for v in a['ins']],z=a['z'],
                   paras=[dict(jc=p['jc'],text=''.join(r['t'] for r in p['runs']),size=p['runs'][0]['size'],bold=p['runs'][0]['bold'],color=p['runs'][0]['color']) for p in a['paras'] if p['runs']])
            bl=a.get('_baselines',[])
            if len(bl)!=len(b['paras']): raise SystemExit('baseline/paragraph mismatch in %s box %s: %s vs %d'%(docx,a['name'],bl,len(b['paras'])))
            for p,v in zip(b['paras'],bl): p['baseline']=rnd(v)
            b['role']=role_of(a)
            out['boxes'].append(b)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--docx',required=True); ap.add_argument('--pdfs',required=True)
    ap.add_argument('--fonts',required=True); ap.add_argument('--out',default='out')
    ap.add_argument('--html-template',default=os.path.join(os.path.dirname(os.path.abspath(__file__)),'sign_template.src.html'))
    a=ap.parse_args()
    os.makedirs(a.out+'/assets',exist_ok=True); os.makedirs(a.out+'/fonts',exist_ok=True)
    for f in glob.glob(os.path.join(a.fonts,'FCVisionRounded-*.ttf')): shutil.copy(f,a.out+'/fonts/')
    signs=[]
    for f in sorted(glob.glob(os.path.join(a.docx,'Sign-*-*.docx'))):
        m=re.match(r'Sign-([A-Z])-(\d\d)\.docx',os.path.basename(f))
        pdf=os.path.join(a.pdfs,os.path.basename(f)[:-5]+'.pdf')
        signs.append(build_sign(f,pdf,m.group(1),m.group(2),a.out+'/assets'))
        print('ok',signs[-1]['id'])
    json.dump(signs,open(a.out+'/templates.json','w'),ensure_ascii=False,indent=1)
    if os.path.exists(a.html_template):
        html=open(a.html_template,encoding='utf8').read().replace('/*__TEMPLATES__*/null',json.dumps(signs,ensure_ascii=False))
        open(a.out+'/sign_template.html','w',encoding='utf8').write(html)
    print('done',len(signs),'signs')
if __name__=='__main__': main()
