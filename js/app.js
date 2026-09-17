/* ==========================================================================
   RIKIRIKI Price Tag Printer — app.js
   Renders 16 sign templates (extracted from the original Word designs) as
   mm-accurate HTML overlays on top of each template's background image, so
   the on-screen preview and the printed page match the original design.
   ========================================================================== */

const PX_PER_MM = 96 / 25.4; // CSS reference pixel conversion

// Optional English sub-labels shown under the Thai category name. Purely
// decorative — a brand-new category code that isn't listed here just won't
// get a sub-label, no code change required. Add to this map any time.
const CATEGORY_SUB_LABELS = {
  A: 'SALE',
  B: 'PROMOTION',
  C: 'BEST SELLER',
  D: 'NEW',
};

// Sensible starting values so the preview is never blank
const DEFAULTS = {
  productName: 'ชื่อสินค้า',
  desc1: 'รายละเอียดสินค้า',
  desc2: '',
  price: '199',
  oldPrice: '299.00',
  dateStart: '',
  dateEnd: '',
};

/* ---------------------------- category/size discovery ----------------------------
   Categories and sizes are NOT hardcoded — they're derived from whatever is
   actually present in data/templates.json. To add a brand-new category or
   size in the future, just add template entries with a new `category`/
   `categoryLabel` or `sizeCode`/`sizeLabel` — the pickers below update
   automatically, no app.js edit needed. See ADDING_TEMPLATES.md.
------------------------------------------------------------------------------- */

function listCategories() {
  const seen = new Map();
  Object.values(TEMPLATES).forEach((t) => {
    if (!seen.has(t.category)) seen.set(t.category, t.categoryLabel);
  });
  return [...seen.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([code, label]) => ({ code, label, sub: CATEGORY_SUB_LABELS[code] || '' }));
}

function listSizes() {
  const seen = new Map();
  Object.values(TEMPLATES).forEach((t) => {
    if (!seen.has(t.sizeCode)) seen.set(t.sizeCode, t.sizeLabel);
  });
  return [...seen.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([code, label]) => ({ code, label }));
}

// Roles the form already knows how to render dedicated inputs for.
// Any OTHER role found in a template's fields still gets a plain generic
// text input automatically (see buildForm) — so a future template that
// introduces a new field role works right away without touching this file.
const KNOWN_ROLES = new Set(['productName', 'description', 'price', 'oldPrice', 'dateRange', 'disclaimer', 'static']);

let TEMPLATES = {};
let state = {
  category: 'A',
  size: '01',
  data: { ...DEFAULTS },
};
let queue = []; // [{ templateId, data }]

/* ---------------------------- utilities ---------------------------- */

function mm(v) { return v + 'mm'; }
function ptToMm(pt) { return pt * 0.352778; }

function thaiDate(dateStr) {
  if (!dateStr) return '00/00/00';
  const d = new Date(dateStr + 'T00:00:00');
  if (isNaN(d)) return '00/00/00';
  const dd = String(d.getDate()).padStart(2, '0');
  const mmn = String(d.getMonth() + 1).padStart(2, '0');
  const beYear = d.getFullYear() + 543;
  const yy = String(beYear).slice(-2);
  return `${dd}/${mmn}/${yy}`;
}

function fieldValueText(field, data) {
  switch (field.role) {
    case 'productName':
      return data.productName || '';
    case 'description':
      return [data.desc1 || '', data.desc2 || ''].filter(Boolean).join('\n');
    case 'price': {
      const p = (data.price ?? '').toString().trim();
      return p;
    }
    case 'oldPrice': {
      const n = parseFloat(data.oldPrice);
      const val = isNaN(n) ? '0.00' : n.toFixed(2);
      return `ราคาปกติ ${val} บาท`;
    }
    case 'dateRange':
      return `วันที่ ${thaiDate(data.dateStart)} – ${thaiDate(data.dateEnd)}`;
    case 'disclaimer':
    case 'static':
      return field.sampleText;
    default:
      // Unknown/future role: if the form collected a value for it (see
      // buildForm's generic-role fallback), use that; otherwise show the
      // template's original sample text so new templates never render blank.
      return (data[field.role] !== undefined && data[field.role] !== '')
        ? data[field.role]
        : (field.sampleText || '');
  }
}

function alignToCss(a) {
  if (a === 'right' || a === 'end') return 'right';
  if (a === 'center' || a === 'both') return 'center';
  return 'left';
}

/* ---------------------------- DOM building ---------------------------- */

function buildSignPageEl(template, data) {
  const page = document.createElement('div');
  page.className = 'sign-page';
  page.style.width = mm(template.page_w_mm);
  page.style.height = mm(template.page_h_mm);

  template.units.forEach((unit) => {
    const unitEl = document.createElement('div');
    unitEl.className = 'sign-unit';
    unitEl.style.left = mm(unit.offset_x_mm);
    unitEl.style.top = mm(unit.offset_y_mm);
    unitEl.style.width = mm(unit.bg_w_mm);
    unitEl.style.height = mm(unit.bg_h_mm);

    const img = document.createElement('img');
    img.className = 'sign-bg';
    img.src = unit.background;
    img.style.left = mm(unit.bg_x_mm - unit.offset_x_mm);
    img.style.top = mm(unit.bg_y_mm - unit.offset_y_mm);
    img.style.width = mm(unit.bg_w_mm);
    img.style.height = mm(unit.bg_h_mm);
    img.draggable = false;
    unitEl.appendChild(img);

    (unit.decorations || []).forEach((dec) => {
      const d = document.createElement('div');
      d.className = 'sign-deco deco-' + dec.shape;
      d.style.left = mm(dec.x_mm);
      d.style.top = mm(dec.y_mm);
      d.style.width = mm(dec.w_mm);
      d.style.height = mm(dec.h_mm);
      d.style.background = dec.color;
      unitEl.appendChild(d);
    });

    const allFields = [...(unit.fields || []), ...(unit.statics || [])];
    allFields.forEach((field) => {
      const f = document.createElement('div');
      f.className = 'sign-field';
      f.style.left = mm(field.x_mm);
      f.style.top = mm(field.y_mm);
      f.style.width = mm(field.w_mm);
      f.style.height = mm(field.h_mm);
      f.style.fontSize = mm(ptToMm(field.fontSizePt));
      f.style.color = field.color;
      f.style.fontWeight = field.bold ? '700' : '400';
      f.style.textAlign = alignToCss(field.align);
      f.style.alignItems = field.align === 'right' ? 'flex-end' : (field.align === 'center' ? 'center' : 'flex-start');
      f.textContent = fieldValueText(field, data);
      unitEl.appendChild(f);
    });

    page.appendChild(unitEl);
  });

  return page;
}

/* ---------------------------- pickers ---------------------------- */

function renderCategoryPicker() {
  const el = document.getElementById('categoryPicker');
  el.innerHTML = '';
  listCategories().forEach((c) => {
    const card = document.createElement('div');
    card.className = 'pick-card' + (state.category === c.code ? ' active' : '');
    card.innerHTML = c.sub ? `${c.label}<small>${c.sub}</small>` : c.label;
    card.onclick = () => { state.category = c.code; ensureValidSize(); onTemplateChange(); };
    el.appendChild(card);
  });
}

function renderSizePicker() {
  const el = document.getElementById('sizePicker');
  el.innerHTML = '';
  // Only offer sizes that actually exist for the selected category.
  const availableSizes = new Set(
    Object.values(TEMPLATES).filter(t => t.category === state.category).map(t => t.sizeCode)
  );
  listSizes().filter(s => availableSizes.has(s.code)).forEach((s) => {
    const card = document.createElement('div');
    card.className = 'pick-card' + (state.size === s.code ? ' active' : '');
    card.innerHTML = s.label;
    card.onclick = () => { state.size = s.code; onTemplateChange(); };
    el.appendChild(card);
  });
}

// If the current category doesn't offer the currently-selected size
// (e.g. a new category was added without a "04" size yet), fall back to
// whatever size that category does have.
function ensureValidSize() {
  const has = Object.values(TEMPLATES).some(t => t.category === state.category && t.sizeCode === state.size);
  if (!has) {
    const fallback = Object.values(TEMPLATES).find(t => t.category === state.category);
    if (fallback) state.size = fallback.sizeCode;
  }
}

function currentTemplateId() { return `${state.category}-${state.size}`; }
function currentTemplate() { return TEMPLATES[currentTemplateId()]; }

/* ---------------------------- form ---------------------------- */

function rolesInTemplate(template) {
  const roles = new Set();
  template.units[0].fields.forEach((f) => roles.add(f.role));
  return roles;
}

function buildForm() {
  const template = currentTemplate();
  const roles = rolesInTemplate(template);
  const form = document.getElementById('signForm');
  form.innerHTML = '';

  if (roles.has('productName')) {
    form.appendChild(makeTextRow('productName', 'ชื่อสินค้า', state.data.productName));
  }
  if (roles.has('description')) {
    const wrap = document.createElement('div');
    wrap.className = 'field-row';
    wrap.innerHTML = `<label>รายละเอียดสินค้า</label>`;
    const pair = document.createElement('div');
    pair.className = 'field-pair';
    pair.appendChild(makeBareInput('desc1', 'เช่น ผลิตภัณฑ์น้ำยาล้างจาน', state.data.desc1));
    pair.appendChild(makeBareInput('desc2', 'เช่น 3200 มล.', state.data.desc2));
    wrap.appendChild(pair);
    form.appendChild(wrap);
  }
  if (roles.has('price')) {
    form.appendChild(makeTextRow('price', 'ราคาใหม่ (บาท)', state.data.price, 'number'));
  }
  if (roles.has('oldPrice')) {
    form.appendChild(makeTextRow('oldPrice', 'ราคาปกติ (บาท)', state.data.oldPrice, 'number'));
  }
  if (roles.has('dateRange')) {
    const wrap = document.createElement('div');
    wrap.className = 'field-row';
    wrap.innerHTML = `<label>ช่วงวันที่โปรโมชั่น</label>`;
    const pair = document.createElement('div');
    pair.className = 'field-pair';
    pair.appendChild(makeBareInput('dateStart', '', state.data.dateStart, 'date'));
    pair.appendChild(makeBareInput('dateEnd', '', state.data.dateEnd, 'date'));
    wrap.appendChild(pair);
    form.appendChild(wrap);
  }
  if (roles.has('disclaimer')) {
    const note = document.createElement('div');
    note.className = 'static-note';
    const sample = template.units[0].fields.find(f => f.role === 'disclaimer').sampleText;
    note.textContent = `ข้อความคงที่บนป้าย: "${sample}"`;
    form.appendChild(note);
  }

  // Generic fallback: any role this template uses that the form doesn't
  // have a dedicated input for yet gets a plain labeled text box. This is
  // what makes adding a future template with a new field type ("sku",
  // "barcode", whatever) work immediately, with no app.js changes.
  roles.forEach((role) => {
    if (KNOWN_ROLES.has(role)) return;
    const sample = template.units[0].fields.find(f => f.role === role)?.sampleText || '';
    if (state.data[role] === undefined) state.data[role] = sample;
    form.appendChild(makeTextRow(role, `${role} (ฟิลด์ใหม่จากเทมเพลต)`, state.data[role]));
  });
}

function makeBareInput(key, placeholder, value, type = 'text') {
  const input = document.createElement('input');
  input.type = type;
  input.placeholder = placeholder;
  input.dataset.field = key;
  input.value = value || '';
  input.oninput = () => { state.data[key] = input.value; renderPreview(); };
  return input;
}

function makeTextRow(key, label, value, type = 'text') {
  const row = document.createElement('div');
  row.className = 'field-row';
  const lab = document.createElement('label');
  lab.textContent = label;
  const input = document.createElement('input');
  input.type = type;
  input.dataset.field = key;
  input.value = value || '';
  input.oninput = () => { state.data[key] = input.value; renderPreview(); };
  row.appendChild(lab);
  row.appendChild(input);
  return row;
}

/* ---------------------------- preview ---------------------------- */

function renderPreview() {
  const template = currentTemplate();
  const stage = document.getElementById('previewStage');
  stage.innerHTML = '';
  const pageEl = buildSignPageEl(template, state.data);
  stage.appendChild(pageEl);

  document.getElementById('previewMeta').textContent =
    `— ${template.categoryLabel} / ${template.sizeLabel} (${template.page_w_mm}×${template.page_h_mm} มม.)`;
  document.getElementById('approxNotice').hidden = !template.approximated;

  // scale to fit the outer stage area
  requestAnimationFrame(() => {
    const outer = document.getElementById('previewStageOuter');
    const naturalWidthPx = template.page_w_mm * PX_PER_MM;
    const naturalHeightPx = template.page_h_mm * PX_PER_MM;
    const availW = outer.clientWidth - 20;
    const scale = Math.min(1, availW / naturalWidthPx);
    stage.style.transform = `scale(${scale})`;
    stage.style.width = naturalWidthPx + 'px';
    stage.style.height = naturalHeightPx + 'px';
    outer.style.minHeight = (naturalHeightPx * scale + 48) + 'px';
  });
}

function onTemplateChange() {
  renderCategoryPicker();
  renderSizePicker();
  // reset field defaults sensibly when structure differs but keep what user already typed
  buildForm();
  renderPreview();
}

/* ---------------------------- queue ---------------------------- */

function updateQueueBadges() {
  document.getElementById('queueCount').textContent = queue.length;
  document.getElementById('queueCount2').textContent = queue.length;
}

function renderQueueList() {
  const list = document.getElementById('queueList');
  list.innerHTML = '';
  if (queue.length === 0) {
    list.innerHTML = '<div class="queue-empty">ยังไม่มีป้ายในคิว<br>กด "เพิ่มลงคิวพิมพ์" จากป้ายที่กรอกไว้</div>';
    return;
  }
  queue.forEach((item, idx) => {
    const t = TEMPLATES[item.templateId];
    const row = document.createElement('div');
    row.className = 'queue-item';
    row.innerHTML = `
      <div class="queue-item-info">
        <b>${item.data.productName || '(ไม่มีชื่อ)'}</b>
        <span>${t.categoryLabel} · ${t.sizeLabel}</span>
      </div>`;
    const del = document.createElement('button');
    del.className = 'btn btn-ghost btn-sm btn-danger-text';
    del.textContent = 'ลบ';
    del.onclick = () => { queue.splice(idx, 1); renderQueueList(); updateQueueBadges(); };
    row.appendChild(del);
    list.appendChild(row);
  });
}

function addCurrentToQueue() {
  queue.push({ templateId: currentTemplateId(), data: { ...state.data } });
  updateQueueBadges();
  renderQueueList();
}

/* ---------------------------- printing ---------------------------- */

function printPages(items) {
  const printArea = document.getElementById('printArea');
  printArea.innerHTML = '';
  items.forEach((item) => {
    const t = TEMPLATES[item.templateId];
    const pageEl = buildSignPageEl(t, item.data);
    printArea.appendChild(pageEl);
  });

  // set @page size dynamically based on the (first) page's dimensions.
  // Different page sizes within one print job aren't reliably supported by
  // browsers via a single @page rule, so we inject one rule per distinct size.
  let styleTag = document.getElementById('dynamicPageSize');
  if (!styleTag) {
    styleTag = document.createElement('style');
    styleTag.id = 'dynamicPageSize';
    document.head.appendChild(styleTag);
  }
  const sizes = new Set(items.map(i => {
    const t = TEMPLATES[i.templateId];
    return `${t.page_w_mm}mm ${t.page_h_mm}mm`;
  }));
  const primarySize = sizes.values().next().value || 'A4';
  styleTag.textContent = `@page { size: ${primarySize}; margin: 0; }`;

  setTimeout(() => window.print(), 50);
}

/* ---------------------------- wiring ---------------------------- */

function init() {
  fetch('data/templates.json')
    .then((r) => r.json())
    .then((json) => {
      TEMPLATES = json;
      // Default to the first category/size actually present in the data,
      // instead of assuming 'A'/'01' exist.
      const cats = listCategories();
      if (cats.length && !TEMPLATES[currentTemplateId()]) {
        state.category = cats[0].code;
        ensureValidSize();
      }
      onTemplateChange();
    });

  document.getElementById('btnAddQueue').onclick = addCurrentToQueue;
  document.getElementById('btnPrintNow').onclick = () => {
    printPages([{ templateId: currentTemplateId(), data: { ...state.data } }]);
  };
  document.getElementById('btnPrintQueue').onclick = () => {
    if (queue.length === 0) { alert('คิวพิมพ์ยังไม่มีป้ายเลย'); return; }
    printPages(queue);
  };
  document.getElementById('btnClearQueue').onclick = () => {
    queue = []; renderQueueList(); updateQueueBadges();
  };
  document.getElementById('btnShowQueue').onclick = () => {
    document.getElementById('queueDrawer').hidden = false;
  };
  document.getElementById('btnCloseQueue').onclick = () => {
    document.getElementById('queueDrawer').hidden = true;
  };

  window.addEventListener('resize', () => renderPreview());
}

document.addEventListener('DOMContentLoaded', init);
