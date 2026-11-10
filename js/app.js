/* ==========================================================================
   RIKIRIKI Price Tag Printer — app.js  (SVG renderer)
   Every sign is drawn as an SVG whose coordinate system is the Word page in
   points. Background art, the ":-" dash/dot shapes and every text baseline come
   from data/templates.json (measured from the Word files), so the preview and
   the printed page are identical to the Word design.
   ========================================================================== */

const PT_PX = 96 / 72;
const SVG_NS = 'http://www.w3.org/2000/svg';
const FONT = '"FC Vision Rounded"';

// Optional English sub-labels under the Thai category name (decorative only).
const CATEGORY_SUB_LABELS = {
  A: 'SALE', B: 'FLASH DEAL', C: 'BEST SELLER', D: 'NEW',
  E: 'BUY 1 GET 1', F: 'BULK PACK', G: 'PAIR DEAL', H: 'ONE PRICE',
};

let TEMPLATES = {};
let state = { category: 'A', size: '01', data: null, touched: {} };
let queue = []; // [{ templateId, data }]

/* ---------------------------- category / size discovery ---------------------------- */

function listCategories() {
  const seen = new Map();
  Object.values(TEMPLATES).forEach((t) => { if (!seen.has(t.category)) seen.set(t.category, t.categoryLabel); });
  return [...seen.entries()].sort((a, b) => a[0].localeCompare(b[0]))
    .map(([code, label]) => ({ code, label, sub: CATEGORY_SUB_LABELS[code] || '' }));
}
function listSizes() {
  const seen = new Map();
  Object.values(TEMPLATES).forEach((t) => { if (!seen.has(t.sizeCode)) seen.set(t.sizeCode, t.sizeLabel); });
  return [...seen.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([code, label]) => ({ code, label }));
}

/* ---------------------------- values ---------------------------- */

const fmtPrice = (s) => String(s ?? '').replace(/[^\d]/g, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
function fmtMoney(s) {
  const n = parseFloat(String(s).replace(/,/g, ''));
  if (isNaN(n)) return '0.00';
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function thaiDate(dateStr) {            // yyyy-mm-dd (date input) -> dd/mm/yy in Buddhist Era
  if (!dateStr) return '00/00/00';
  const d = new Date(dateStr + 'T00:00:00');
  if (isNaN(d)) return '00/00/00';
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getFullYear() + 543).slice(-2)}`;
}
function boxOf(t, role) { return t.boxes.find((b) => b.role === role); }
function hasRole(t, role) { return t.boxes.some((b) => b.role === role); }

// default texts that come from the Word design itself
function designDefaults(t) {
  const d = { only: '', foot: '' };
  const o = boxOf(t, 'only'); if (o) d.only = o.paras[0].text;
  const f = boxOf(t, 'foot'); if (f) d.foot = f.paras[0].text;
  return d;
}
function newData(t) {
  return { name: 'ชื่อสินค้า', d1: 'รายละเอียดสินค้า', d2: '', price: '199', oldPrice: '299.00',
           dateStart: '', dateEnd: '', ...designDefaults(t) };
}
function withDesignDefaults(data, t) {   // keep what the user typed; take only/foot from this design unless edited
  const d = designDefaults(t);
  const out = { ...data };
  ['only', 'foot'].forEach((k) => { if (!state.touched[k]) out[k] = d[k]; });
  return out;
}

/* ---------------------------- SVG rendering ---------------------------- */

let measureSvg = null;
function measure(str, size, bold) {
  if (!measureSvg) {
    measureSvg = document.createElementNS(SVG_NS, 'svg');
    measureSvg.setAttribute('style', 'position:absolute;left:-99999px;top:0;width:10px;height:10px;visibility:hidden');
    document.body.appendChild(measureSvg);
  }
  const t = document.createElementNS(SVG_NS, 'text');
  t.setAttribute('font-size', size); t.setAttribute('font-weight', bold ? 700 : 400);
  t.setAttribute('style', `font-family:${FONT};white-space:pre;font-kerning:normal;text-rendering:geometricPrecision`);
  t.textContent = str; measureSvg.appendChild(t);
  const w = t.getComputedTextLength(); measureSvg.removeChild(t); return w;
}
function mk(tag, attrs, parent) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function textEl(parent, str, x, y, size, bold, color, anchor) {
  const e = mk('text', { x, y, 'font-size': size, 'font-weight': bold ? 700 : 400, fill: '#' + color, 'text-anchor': anchor,
    style: `font-family:${FONT};white-space:pre;font-kerning:normal;text-rendering:geometricPrecision` }, parent);
  e.textContent = str; return e;
}

function buildSignSvg(t, v) {
  const [W, H] = t.page;
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('width', W + 'pt'); svg.setAttribute('height', H + 'pt');
  svg.setAttribute('class', 'sign-svg');
  mk('rect', { x: 0, y: 0, width: W, height: H, fill: '#fff' }, svg);
  for (const im of t.images) {
    const e = mk('image', { x: im.x, y: im.y, width: im.w, height: im.h, preserveAspectRatio: 'none' }, svg);
    e.setAttribute('href', im.file);
  }
  // Word's own z-order: shapes and text boxes interleaved
  const items = [...t.shapes.map((s) => ({ z: s.z, s })), ...t.boxes.map((b) => ({ z: b.z, b }))].sort((a, b) => a.z - b.z);
  // dash/dot belong to the nearest price box (they are scaled together with long prices)
  const prices = t.boxes.filter((b) => b.role === 'price');
  const owner = new Map();
  for (const s of t.shapes) {
    const cy = s.y + s.h / 2; let best = null, bd = 1e9;
    for (const p of prices) { const d = cy < p.y ? p.y - cy : (cy > p.y + p.h ? cy - (p.y + p.h) : 0); if (d < bd) { bd = d; best = p; } }
    owner.set(s, best);
  }
  const groups = new Map(prices.map((p) => [p, mk('g', {}, null)]));
  for (const it of items) {
    if (it.s) {
      const s = it.s; const host = groups.get(owner.get(s)) || svg;
      if (s.kind === 'oval') {
        mk('ellipse', { cx: s.x + s.w / 2, cy: s.y + s.h / 2, rx: s.w / 2, ry: s.h / 2, fill: '#' + s.fill, stroke: '#' + s.stroke, 'stroke-width': s.stroke_w }, host);
      } else { // Word "flowChartTerminator" geometry
        const rx = s.w * 3475 / 21600, ry = s.h / 2, x = s.x, y = s.y, w = s.w, h = s.h;
        mk('path', { d: `M${x + rx},${y} L${x + w - rx},${y} A${rx},${ry} 0 0 1 ${x + w - rx},${y + h} L${x + rx},${y + h} A${rx},${ry} 0 0 1 ${x + rx},${y} Z`,
          fill: '#' + s.fill, stroke: '#' + s.stroke, 'stroke-width': s.stroke_w, 'stroke-linejoin': 'miter' }, host);
      }
      continue;
    }
    const b = it.b; const [l, , r] = b.ins;
    if (b.role === 'price') {
      const g = groups.get(b); svg.appendChild(g);
      const p = b.paras[0]; const str = fmtPrice(v.price) || '0';
      const xr = b.x + b.w - r;
      textEl(g, str, xr, p.baseline, p.size, p.bold, p.color, 'end');
      let Ax = xr; for (const s of t.shapes) if (owner.get(s) === b) Ax = Math.max(Ax, s.x + s.w + s.stroke_w / 2);
      const wt = measure(str, p.size, p.bold);
      const left = Math.max(b.x + l, xr - measure(p.text, p.size, p.bold));  // where the design's own digits start
      const k = Math.min(1, (Ax - left) / Math.max(1, (Ax - (xr - wt))));
      if (k < 1) {
        g.setAttribute('transform', `translate(${Ax} ${p.baseline}) scale(${k}) translate(${-Ax} ${-p.baseline})`);
        g.dataset.ax = Ax; g.dataset.by = p.baseline; g.dataset.k = k;
      }
      continue;
    }
    let lines;
    if (b.role === 'name') lines = [v.name];
    else if (b.role === 'desc') lines = [v.d1, v.d2];
    else if (b.role === 'normal') lines = [b.paras[0].text.replace(/[\d,.]+/, fmtMoney(v.oldPrice))];
    else if (b.role === 'date') lines = [b.paras[0].text.replace(/\d\d\/\d\d\/\d\d(\D+)\d\d\/\d\d\/\d\d/, thaiDate(v.dateStart) + '$1' + thaiDate(v.dateEnd))];
    else if (b.role === 'only') lines = [v.only];
    else if (b.role === 'foot') lines = [v.foot];
    else lines = b.paras.map((p) => p.text);
    b.paras.forEach((p, i) => {
      const str = (lines[i] ?? p.text).replace(/\s+$/, ''); if (!str) return;
      const right = p.jc === 'right'; const x = right ? b.x + b.w - r : b.x + l;
      let size = p.size; const maxW = b.w - l - r; const w = measure(str, size, p.bold);
      if (w > maxW && w > 0) size = size * Math.max(0.35, maxW / w);      // long text shrinks to fit the original box
      textEl(svg, str, x, p.baseline, size, p.bold, p.color, right ? 'end' : 'start');
    });
  }
  return svg;
}

const CATEGORY_ICONS = {
  A: '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41 11 3.83A2 2 0 0 0 9.59 3.24L3.24 9.59A2 2 0 0 0 3.83 11l9.58 9.59a2 2 0 0 0 2.83 0l4.35-4.35a2 2 0 0 0 0-2.83Z"></path><circle cx="8.5" cy="8.5" r="1.5"></circle></svg>',
  B: '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 11 18-5v12L3 14v-3z"></path><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"></path></svg>',
  C: '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"></polygon></svg>',
  D: '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"></path></svg>',
};
const DEFAULT_CATEGORY_ICON = '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"></rect><path d="M8 12h8M12 8v8"></path></svg>';
const SIZE_ICONS = {
  '01': '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="3" width="10" height="18" rx="1.5"></rect></svg>',
  '02': '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="7" width="18" height="10" rx="1.5"></rect></svg>',
  '03': '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="8" width="18" height="8" rx="1.5"></rect></svg>',
  '04': '<svg class="pick-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="6" rx="1"></rect><rect x="3" y="13" width="18" height="6" rx="1"></rect></svg>',
};

function renderCategoryPicker() {
  const el = document.getElementById('categoryPicker');
  el.innerHTML = '';
  listCategories().forEach((c) => {
    const card = document.createElement('div');
    card.className = 'pick-card' + (state.category === c.code ? ' active' : '');
    card.innerHTML = (CATEGORY_ICONS[c.code] || DEFAULT_CATEGORY_ICON) + c.label + (c.sub ? `<small>${c.sub}</small>` : '');
    card.onclick = () => { state.category = c.code; ensureValidSize(); onTemplateChange(); };
    el.appendChild(card);
  });
}
function renderSizePicker() {
  const el = document.getElementById('sizePicker');
  el.innerHTML = '';
  const available = new Set(Object.values(TEMPLATES).filter((t) => t.category === state.category).map((t) => t.sizeCode));
  listSizes().filter((s) => available.has(s.code)).forEach((s) => {
    const card = document.createElement('div');
    card.className = 'pick-card' + (state.size === s.code ? ' active' : '');
    card.innerHTML = (SIZE_ICONS[s.code] || '') + s.label;
    card.onclick = () => { state.size = s.code; onTemplateChange(); };
    el.appendChild(card);
  });
}
function ensureValidSize() {
  const has = Object.values(TEMPLATES).some((t) => t.category === state.category && t.sizeCode === state.size);
  if (!has) { const f = Object.values(TEMPLATES).find((t) => t.category === state.category); if (f) state.size = f.sizeCode; }
}
function currentTemplate() { return Object.values(TEMPLATES).find((t) => t.category === state.category && t.sizeCode === state.size); }
function currentTemplateId() { const t = currentTemplate(); return t ? t.id : `${state.category}-${state.size}`; }

/* ---------------------------- form ---------------------------- */

function bareInput(key, placeholder, value, type = 'text', fmt = null) {
  const input = document.createElement('input');
  input.type = type; input.placeholder = placeholder; input.dataset.field = key; input.value = value || '';
  if (key === 'price') input.inputMode = 'numeric';
  input.oninput = () => {
    if (fmt) { input.value = fmt(input.value); }
    state.data[key] = input.value; state.touched[key] = true; renderPreview();
  };
  return input;
}
function row(label, ...inputs) {
  const r = document.createElement('div'); r.className = 'field-row';
  const l = document.createElement('label'); l.textContent = label; r.appendChild(l);
  if (inputs.length > 1) { const p = document.createElement('div'); p.className = 'field-pair'; inputs.forEach((i) => p.appendChild(i)); r.appendChild(p); }
  else r.appendChild(inputs[0]);
  return r;
}
function buildForm() {
  const t = currentTemplate(); const d = state.data;
  const form = document.getElementById('signForm'); form.innerHTML = '';
  if (hasRole(t, 'name')) form.appendChild(row('ชื่อสินค้า', bareInput('name', '', d.name)));
  if (hasRole(t, 'desc')) form.appendChild(row('รายละเอียดสินค้า', bareInput('d1', 'เช่น ผลิตภัณฑ์น้ำยาล้างจาน', d.d1), bareInput('d2', 'เช่น 3200 มล.', d.d2)));
  if (hasRole(t, 'price')) form.appendChild(row('ราคาใหม่ (บาท) — ใส่ , ให้อัตโนมัติ', bareInput('price', '', fmtPrice(d.price), 'text', fmtPrice)));
  if (hasRole(t, 'normal')) form.appendChild(row('ราคาปกติ (บาท)', bareInput('oldPrice', '', d.oldPrice)));
  if (hasRole(t, 'date')) form.appendChild(row('ช่วงวันที่โปรโมชั่น', bareInput('dateStart', '', d.dateStart, 'date'), bareInput('dateEnd', '', d.dateEnd, 'date')));
  if (hasRole(t, 'only')) form.appendChild(row('ข้อความ "เพียง"', bareInput('only', '', d.only)));
  if (hasRole(t, 'foot')) form.appendChild(row('หมายเหตุท้ายป้าย', bareInput('foot', '', d.foot)));
  if (!form.children.length) {
    const note = document.createElement('div'); note.className = 'static-note';
    note.textContent = 'ป้ายแบบนี้เป็นงานพร้อมพิมพ์ ไม่มีช่องให้กรอก — กด "พิมพ์ป้ายนี้ทันที" หรือเพิ่มลงคิวได้เลย (1 แผ่น A4 ได้ 2 ใบ)';
    form.appendChild(note);
  }
}

/* ---------------------------- preview ---------------------------- */

function renderPreview() {
  const t = currentTemplate(); if (!t) return;
  const stage = document.getElementById('previewStage');
  stage.innerHTML = '';
  const svg = buildSignSvg(t, state.data);
  svg.style.maxWidth = (t.page[0] * PT_PX) + 'px';
  stage.appendChild(svg);
  document.getElementById('previewMeta').textContent = `— ${t.categoryLabel} / ${t.sizeLabel}`;
  const n = document.getElementById('approxNotice'); if (n) n.hidden = true;
}
function onTemplateChange() {
  const t = currentTemplate();
  state.data = withDesignDefaults(state.data || newData(t), t);
  renderCategoryPicker(); renderSizePicker(); buildForm(); renderPreview();
}

/* ---------------------------- queue ---------------------------- */

function updateQueueBadges() {
  document.getElementById('queueCount').textContent = queue.length;
  document.getElementById('queueCount2').textContent = queue.length;
}
function renderQueueList() {
  const list = document.getElementById('queueList'); list.innerHTML = '';
  if (queue.length === 0) { list.innerHTML = '<div class="queue-empty">ยังไม่มีป้ายในคิว<br>กด "เพิ่มลงคิวพิมพ์" จากป้ายที่กรอกไว้</div>'; return; }
  queue.forEach((item, idx) => {
    const t = TEMPLATES[item.templateId];
    const r = document.createElement('div'); r.className = 'queue-item';
    const info = document.createElement('div'); info.className = 'queue-item-info';
    const b = document.createElement('b'); b.textContent = item.data.name || '(ไม่มีชื่อ)';
    const sp = document.createElement('span'); sp.textContent = `${t.categoryLabel} · ${t.sizeLabel}`;
    info.append(b, sp); r.appendChild(info);
    const del = document.createElement('button'); del.className = 'btn btn-ghost btn-sm btn-danger-text'; del.textContent = 'ลบ';
    del.onclick = () => { queue.splice(idx, 1); renderQueueList(); updateQueueBadges(); };
    r.appendChild(del); list.appendChild(r);
  });
}
function addCurrentToQueue() {
  queue.push({ templateId: currentTemplateId(), data: { ...state.data } });
  updateQueueBadges(); renderQueueList(); showToast('เพิ่มลงคิวพิมพ์แล้ว');
}
let toastTimer = null;
function showToast(message, ms = 1800) {
  const el = document.getElementById('toast');
  el.textContent = message; el.hidden = false;
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.classList.remove('show'); setTimeout(() => { el.hidden = true; }, 200); }, ms);
}

/* ---------------------------- printing ---------------------------- */

function printPages(items) {
  const area = document.getElementById('printArea'); area.innerHTML = '';
  items.forEach((item) => {
    const t = TEMPLATES[item.templateId];
    const wrap = document.createElement('div'); wrap.className = 'print-page';
    wrap.appendChild(buildSignSvg(t, item.data)); area.appendChild(wrap);
  });
  let tag = document.getElementById('dynamicPageSize');
  if (!tag) { tag = document.createElement('style'); tag.id = 'dynamicPageSize'; document.head.appendChild(tag); }
  const first = TEMPLATES[items[0].templateId];
  tag.textContent = `@page { size: ${first.page[0]}pt ${first.page[1]}pt; margin: 0; }`;
  setTimeout(() => window.print(), 50);
}

/* ---------------------------- save as PDF (works on phones where window.print() does nothing) ----------------------------
   Each sign is painted onto a canvas (same SVG data, ~216 dpi), turned into a JPEG and written into a small
   hand-made PDF (one page per sign, page size = the Word page). No external library, works offline.        */

const imgCache = new Map();
function loadImg(href) {
  if (!imgCache.has(href)) imgCache.set(href, new Promise((res, rej) => {
    const im = new Image(); im.onload = () => res(im); im.onerror = () => rej(new Error('image ' + href)); im.src = href;
  }));
  return imgCache.get(href);
}
async function paintNode(ctx, node) {
  for (const c of node.children) {
    const tag = c.tagName.toLowerCase();
    if (tag === 'rect') { ctx.fillStyle = c.getAttribute('fill'); ctx.fillRect(+c.getAttribute('x'), +c.getAttribute('y'), +c.getAttribute('width'), +c.getAttribute('height')); }
    else if (tag === 'image') { const im = await loadImg(c.getAttribute('href')); ctx.drawImage(im, +c.getAttribute('x'), +c.getAttribute('y'), +c.getAttribute('width'), +c.getAttribute('height')); }
    else if (tag === 'ellipse' || tag === 'path') {
      ctx.fillStyle = c.getAttribute('fill'); ctx.strokeStyle = c.getAttribute('stroke'); ctx.lineWidth = +c.getAttribute('stroke-width') || 0;
      if (tag === 'ellipse') { ctx.beginPath(); ctx.ellipse(+c.getAttribute('cx'), +c.getAttribute('cy'), +c.getAttribute('rx'), +c.getAttribute('ry'), 0, 0, Math.PI * 2); ctx.fill(); if (ctx.lineWidth) ctx.stroke(); }
      else { const p = new Path2D(c.getAttribute('d')); ctx.fill(p); if (ctx.lineWidth) { ctx.lineJoin = 'miter'; ctx.stroke(p); } }
    } else if (tag === 'text') {
      ctx.fillStyle = c.getAttribute('fill');
      ctx.font = `${c.getAttribute('font-weight')} ${c.getAttribute('font-size')}px ${FONT}`;
      ctx.textAlign = c.getAttribute('text-anchor') === 'end' ? 'right' : 'left'; ctx.textBaseline = 'alphabetic';
      ctx.fillText(c.textContent, +c.getAttribute('x'), +c.getAttribute('y'));
    } else if (tag === 'g') {
      ctx.save();
      if (c.dataset.k) { const ax = +c.dataset.ax, by = +c.dataset.by, k = +c.dataset.k; ctx.translate(ax, by); ctx.scale(k, k); ctx.translate(-ax, -by); }
      await paintNode(ctx, c); ctx.restore();
    }
  }
}
async function signToJpeg(t, data) {
  const svg = buildSignSvg(t, data); const [W, H] = t.page;
  const scale = Math.min(3.0, 3600 / Math.max(W, H));            // ≈216 dpi, long edge ≤ 3600 px (phone canvas limit)
  const cv = document.createElement('canvas'); cv.width = Math.round(W * scale); cv.height = Math.round(H * scale);
  const ctx = cv.getContext('2d'); ctx.scale(scale, scale);
  await paintNode(ctx, svg);
  const blob = await new Promise((r) => cv.toBlob(r, 'image/jpeg', 0.93));
  const bytes = new Uint8Array(await blob.arrayBuffer());
  cv.width = cv.height = 1;                                       // release memory
  return { w: W, h: H, iw: Math.round(W * scale), ih: Math.round(H * scale), bytes };
}
function makePdf(pages) {
  const enc = new TextEncoder(); const parts = []; const offs = []; let len = 0;
  const push = (x) => { const u = typeof x === 'string' ? enc.encode(x) : x; parts.push(u); len += u.length; };
  const obj = (n, body) => { offs[n] = len; push(`${n} 0 obj\n`); body(); push('\nendobj\n'); };
  push('%PDF-1.4\n');
  const kids = pages.map((_, i) => 3 + i * 3);
  obj(1, () => push('<< /Type /Catalog /Pages 2 0 R >>'));
  obj(2, () => push(`<< /Type /Pages /Kids [${kids.map((k) => k + ' 0 R').join(' ')}] /Count ${pages.length} >>`));
  pages.forEach((pg, i) => {
    const pn = 3 + i * 3, cn = pn + 1, im = pn + 2, w = pg.w.toFixed(2), h = pg.h.toFixed(2);
    obj(pn, () => push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] /Contents ${cn} 0 R /Resources << /XObject << /Im0 ${im} 0 R >> >> >>`));
    const content = `q ${w} 0 0 ${h} 0 0 cm /Im0 Do Q`;
    obj(cn, () => push(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`));
    obj(im, () => { push(`<< /Type /XObject /Subtype /Image /Width ${pg.iw} /Height ${pg.ih} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${pg.bytes.length} >>\nstream\n`); push(pg.bytes); push('\nendstream'); });
  });
  const xref = len, n = 3 + pages.length * 3;
  push(`xref\n0 ${n}\n0000000000 65535 f \n`);
  for (let i = 1; i < n; i++) push(String(offs[i]).padStart(10, '0') + ' 00000 n \n');
  push(`trailer\n<< /Size ${n} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`);
  return new Blob(parts, { type: 'application/pdf' });
}
async function savePdf(items) {
  try {
    showToast('กำลังสร้าง PDF…', 60000);
    await fontsReady;
    const pages = [];
    for (const item of items) pages.push(await signToJpeg(TEMPLATES[item.templateId], item.data));
    const blob = makePdf(pages);
    const d = new Date(); const pad = (x) => String(x).padStart(2, '0');
    const name = `price-sign-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.pdf`;
    const file = new File([blob], name, { type: 'application/pdf' });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {      // phones: share sheet -> Save to Files, print, LINE...
      try { await navigator.share({ files: [file], title: 'ป้ายราคา' }); showToast('เรียบร้อย'); return; }
      catch (e) { if (e && e.name === 'AbortError') { showToast('ยกเลิก'); return; } }
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    showToast('บันทึกไฟล์ PDF แล้ว');
  } catch (err) {
    console.error(err); showToast('สร้าง PDF ไม่สำเร็จ ลองใหม่อีกครั้ง');
  }
}

/* ---------------------------- wiring ---------------------------- */

function init() {
  fetch('data/templates.json').then((r) => r.json()).then((json) => {
    TEMPLATES = json;
    const cats = listCategories();
    if (!currentTemplate() && cats.length) { state.category = cats[0].code; ensureValidSize(); }
    state.data = newData(currentTemplate());
    onTemplateChange();
  });
  document.getElementById('btnAddQueue').onclick = addCurrentToQueue;
  document.getElementById('btnSavePdf').onclick = () => savePdf([{ templateId: currentTemplateId(), data: { ...state.data } }]);
  document.getElementById('btnSaveQueuePdf').onclick = () => { if (!queue.length) { alert('คิวพิมพ์ยังไม่มีป้ายเลย'); return; } savePdf(queue); };
  document.getElementById('btnPrintNow').onclick = () => printPages([{ templateId: currentTemplateId(), data: { ...state.data } }]);
  document.getElementById('btnPrintQueue').onclick = () => { if (!queue.length) { alert('คิวพิมพ์ยังไม่มีป้ายเลย'); return; } printPages(queue); };
  document.getElementById('btnClearQueue').onclick = () => { queue = []; renderQueueList(); updateQueueBadges(); };
  document.getElementById('btnShowQueue').onclick = () => { document.getElementById('queueDrawer').hidden = false; };
  document.getElementById('btnCloseQueue').onclick = () => { document.getElementById('queueDrawer').hidden = true; };
  document.querySelectorAll('.mobile-tab').forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll('.mobile-tab').forEach((x) => x.classList.remove('active')); tab.classList.add('active');
      const target = tab.dataset.tab;
      document.querySelector('.panel-controls').classList.toggle('pane-active', target === 'edit');
      document.querySelector('.panel-preview').classList.toggle('pane-active', target === 'preview');
    };
  });
  document.querySelector('.panel-controls').classList.add('pane-active');
}

// wait for the sign font so text measuring (auto-shrink) is correct
const fontsReady = (document.fonts && document.fonts.load)
  ? Promise.all([document.fonts.load('400 20px "FC Vision Rounded"'), document.fonts.load('700 20px "FC Vision Rounded"')]).catch(() => {})
  : Promise.resolve();
document.addEventListener('DOMContentLoaded', () => fontsReady.then(init));
