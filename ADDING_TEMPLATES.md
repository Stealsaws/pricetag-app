# วิธีเพิ่มเทมเพลตใหม่ในอนาคต

ป้ายทุกแบบถูกวาดเป็น SVG จากข้อมูลใน `data/templates.json` (รูปพื้นหลัง, รูปทรงจุด/เส้นขีด ":-", ตำแหน่งบรรทัดฐานของทุกข้อความ
ในหน่วย pt ตามหน้ากระดาษ Word) จึงต้องได้ข้อมูลนี้จากไฟล์ Word ตัวจริง ไม่ต้องแก้โค้ดแอป

## ขั้นตอน (ไฟล์ Word ชุดใหม่)

1. ตั้งชื่อไฟล์ให้เป็น `Sign-<หมวด>-<ขนาด>.docx` เช่น `Sign-I-01.docx`
   (ขนาด 01 = A3 ตั้ง, 02 = A3 นอน, 03 = A4 นอน, 04 = A4 1/3 สองป้ายต่อแผ่น)
2. เปิดทุกไฟล์ใน Word แล้ว **Save As → PDF** ใช้ชื่อเดียวกัน (`Sign-I-01.pdf`) เก็บไว้โฟลเดอร์เดียว
   (PDF จาก Word ตัวจริงคือค่าอ้างอิงตำแหน่ง ตรงที่สุด; ถ้าไม่มี Word ใช้ LibreOffice แปลงก็ได้)
3. ติดตั้งแพ็กเกจ: `pip install pdfplumber lxml pillow`
4. สร้างข้อมูล แล้วนำเข้าแอป:

```bash
cd tools
python3 build_templates.py --docx <โฟลเดอร์ docx> --pdfs <โฟลเดอร์ pdf> --fonts ../fonts --out /tmp/built
python3 import_templates.py --built /tmp/built --docx <โฟลเดอร์ docx> --app .. --label I="ชื่อหมวดใหม่"
```

`import_templates.py` เขียน `data/templates.json` (เทมเพลตอื่นที่ไม่ได้อยู่ในชุด เช่น Shelf talker ถูกเก็บไว้) และคัดลอกรูปพื้นหลังไป
`assets/bg/` โดยแปลง CMYK เป็น sRGB ให้ (เบราว์เซอร์แสดงสี CMYK เพี้ยน) ปุ่มเลือกหมวด/ขนาดจะโผล่เองจากข้อมูล

ถ้าใส่ `--label` ไม่ครบ หมวดใหม่จะได้ชื่อ "หมวด X" ก่อน แก้ได้ที่ `CATEGORY_LABELS` ใน `tools/import_templates.py`
(ชื่อภาษาอังกฤษใต้ปุ่มหมวดแก้ได้ที่ `CATEGORY_SUB_LABELS` ต้นไฟล์ `js/app.js` ไม่ใส่ก็ไม่พัง)

## ป้ายที่เป็นงานพร้อมพิมพ์ (ไม่มีช่องกรอก) เช่น Shelf talker

แปลง PDF เป็นรูป `pdftoppm -jpeg -r 220 -singlefile ไฟล์.pdf ชื่อ` ใส่ `assets/bg/` แล้วเพิ่มรายการใน `templates.json` ที่ `boxes: []`
ดูตัวอย่างจาก `S-01` (page เป็น pt, `images` วางรูปเต็มหน้า)

## โครงสร้างหนึ่งรายการใน templates.json

- `page` [กว้าง, สูง] เป็น pt; `images` รูปพื้นหลัง (x,y,w,h เป็น pt)
- `shapes` จุด/เส้นขีด (`kind`: `oval` หรือรูปแคปซูลของ Word, สี `fill`/`stroke`, `z` ลำดับการซ้อน)
- `boxes` กล่องข้อความ `role` = name, desc, price, normal (ราคาปกติ), date, only ("เพียง"), foot (หมายเหตุ) พร้อม `paras`
  (ข้อความตัวอย่าง, ขนาด, สี, ตัวหนา, `baseline` ตำแหน่งบรรทัดฐาน, `jc` การจัดชิด)

role ที่ไม่รู้จักจะถูกวาดตามข้อความในเทมเพลตโดยไม่มีช่องกรอก ถ้าต้องการช่องกรอกใหม่ให้เพิ่มใน `buildForm()` และ `buildSignSvg()` ของ `js/app.js`
