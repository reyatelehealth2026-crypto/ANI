# ChatGPT — สร้างภาพฉากผ่าน Claude in Chrome

ใช้ได้จริงกับ moonpetal-guardian (2026-09): สร้าง character sheet ก่อน แล้วขอฉากต่อในแชทเดียวกัน ตัวละครคงที่ดี; สั่ง "vertical 9:16" ได้ภาพ 941×1672

## 1. เปิดแชท
- `tabs_create_mcp` → `navigate` `https://chatgpt.com/` — แชทใหม่ 1 แชทต่อ 1 เรื่อง
- redo ของเรื่องเดิม → กลับไปแชทเดิม (character sheet อยู่ใน context อยู่แล้ว); หาไม่เจอ → แชทใหม่ที่เริ่มจาก character sheet อีกครั้ง
- ยังไม่ล็อกอิน / มี CAPTCHA → หยุด ให้ผู้ใช้ทำในแท็บนั้น แล้วทำต่อ

## 2. Prompt
เอา prompt เต็มของแต่ละฉากจาก `plan_media(slug, "images")` (style + characters ต่อให้แล้ว) — อย่าแต่งใหม่กลางทาง ถ้าต้องเปลี่ยนเนื้อหา แก้ `image_prompt` ใน project.json ก่อน

1. Character sheet (ข้อความแรก):
   `Character sheet for an animated short film. <CHARACTERS block>. Art style: <STYLE block>. Front view and 3/4 view of each character, full body, plain light background, vertical 9:16, no text.`
2. ฉากละ 1 ข้อความ:
   `Scene 01 of 5. Use the exact character designs from the character sheet above. <full prompt>. Vertical 9:16 portrait.`

ส่งทีละข้อความ รอภาพเสร็จก่อนส่งข้อความถัดไป — ข้อความซ้อนกันทำให้จับคู่ภาพกับฉากพลาด

## 3. พิมพ์และส่ง
- `find` "message composer" → `computer` left_click → `computer` type ข้อความ → `computer` key `Return` (หรือ `find` ปุ่ม send แล้วคลิก)
- ภาพใช้ ~30–90 วินาที: เช็กทุก ~20 วินาทีด้วย `find` "generated image" หรือ screenshot — ห้ามส่งซ้ำระหว่างรอ

## 4. ตรวจ
ขนาดภาพล่าสุด:
```js
const im = [...document.querySelectorAll('main img')].filter(i => i.naturalWidth > 500).at(-1);
[im?.naturalWidth, im?.naturalHeight, im?.alt]
```
- อัตราส่วนควร ≈ 0.5625 (941×1672) ไม่ใช่ → ตอบในแชทเดิม "Regenerate as vertical 9:16, same content."
- ดูภาพด้วย screenshot (zoom ถ้าต้องดูหน้า/ชุด) เทียบ character block + storyboard; ผิด → ตอบในแชทเดิมด้วยการแก้ 1–2 จุดที่เจาะจง เช่น "Regenerate scene 03: Rin holds the lantern in her left hand; keep everything else." ดีกว่าส่ง prompt ทั้งก้อนใหม่
- selector ข้างบนเป็นการเดา — ถ้า `im` เป็น undefined หรือไม่ใช่ภาพที่เพิ่งสร้าง ให้ยืนยันด้วย screenshot แล้วปรับ filter

## 5. ดาวน์โหลด (ชื่อไฟล์ตายตัว)
ทำเฉพาะเมื่ออนุมัติขั้น 1 ของ SKILL ครอบไว้แล้ว ตั้งชื่อตายตัวเพื่อให้ `collect --map` จับคู่ได้แน่นอน:
```js
const im = [...document.querySelectorAll('main img')].filter(i => i.naturalWidth > 500).at(-1);
const blob = await fetch(im.src).then(r => r.blob());
const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
const a = Object.assign(document.createElement('a'),
  { href: URL.createObjectURL(blob), download: `ani-<slug>-scene-01.${ext}` });
document.body.append(a); a.click(); a.remove();
[blob.size, blob.type]
```
- character sheet ใช้ชื่อ `ani-<slug>-reference.<ext>`
- Chrome บันทึกลง Downloads ทันที ถ้าขึ้นหน้าต่าง Save As (เปิด "Ask where to save" ไว้ใน Chrome โปรไฟล์นั้น) → ให้ผู้ใช้กด Save เอง หรือปิดตัวเลือกนั้นเองใน `chrome://settings/downloads` (เป็นการตั้งค่าของผู้ใช้)
- ยืนยันบนดิสก์ว่าขนาดไฟล์ = `blob.size`: `Get-ChildItem $HOME\Downloads\ani-<slug>-*`

## 6. เข้าโปรเจกต์
- reference: คัดลอกเป็น `<slug>/02-reference/reference.<ext>`
- ฉาก: `python tools/ani.py collect images --project <slug> --map 01=<Downloads>/ani-<slug>-scene-01.png 02=…` (dry-run แสดงคู่ฉาก-ไฟล์) → ตรวจคู่ → รันซ้ำพร้อม `--yes`
- ต่อด้วย `run_local_stage(contact)` (SKILL ขั้น 4)
