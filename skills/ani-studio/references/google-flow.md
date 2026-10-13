# Google Flow — ภาพฉาก → คลิป ผ่าน Claude in Chrome

ใช้ได้จริงกับ moonpetal-guardian (2026-09) + ป้ายปุ่มจาก flow-playbook v2 (2026-09-27)
UI ของ Flow เปลี่ยนบ่อยและอาจเป็นไทยหรืออังกฤษ — หาด้วย `find` ตามความหมาย ไม่จำตำแหน่งพิกัด

| สิ่งที่หา | ไทย | อังกฤษ |
|---|---|---|
| popover ตั้งค่า | `ทริกเกอร์การตั้งค่า` | settings |
| ประเภท / โหมดย่อย | `วิดีโอ` → `เฟรม` | Video → Frames |
| เฟรมเริ่ม / จบ | `เริ่ม` / `สิ้นสุด` | Start / End |
| ค้น asset | `ค้นหาเนื้อหา` | Search |
| ล้างพรอมต์ | `ล้างพรอมต์` | Clear prompt |
| สร้าง | `เริ่มสร้าง` | Generate / Create |
| ดาวน์โหลด | `ดาวน์โหลดสื่อ` → `… ขนาดดั้งเดิม` | Download media → 720p Original size |
| เครดิตหมด | `คุณใช้เครดิต Google Flow หมดแล้ว`, ปุ่มเป็น `คำเตือนเครดิตไม่เพียงพอ` | out of credits |

## 0. ก่อนเริ่ม
- ใช้ Chrome ที่ผู้ใช้เลือกในขั้น 0 — แต่ละบัญชี Google มีเครดิต Flow ของตัวเอง (เคยเห็น 50 เครดิต/วัน)
- เปิดแท็บใหม่: `provider_config.flow.project_url` ถ้ามีใน project.json, ไม่มี → `https://labs.google/fx/tools/flow` แล้วเปิด/สร้างโปรเจกต์ชื่อ slug — ไม่แตะโปรเจกต์อื่น
- ยังไม่ล็อกอิน → ผู้ใช้ล็อกอินเอง
- ตรวจว่า `tools/flow.py` ไม่ได้รันอยู่ (หน้าต่าง Flow มีผู้คุมได้ทีละตัว)

## 1. ตั้งโหมด + อ่านราคา
เปิด popover ตั้งค่า: Agent ปิด → วิดีโอ → เฟรม → 9:16 → model ที่อนุมัติ (ค่าเริ่มต้น Veo 3.1 Lite) → x1
ข้อความราคา (`การสร้างจะใช้ N เครดิต` หรือคำอังกฤษเทียบเท่า) เห็นเฉพาะตอน popover เปิด — อ่านซ้ำจนค่านิ่ง เพราะค่าอาจค้างจากโหมดภาพ; ใช้ตัวเลขนี้ในจุดตรวจขั้น 5 ของ SKILL (2026-09: Veo 3.1 Lite = 10 เครดิต/คลิป 8 s 720p — ใช้เทียบเท่านั้น ไม่ใช้แทนการอ่านจริง)

## 2. อัปโหลดภาพฉาก (รวดเดียวหลังได้รับอนุมัติ)
`file_upload` รับเฉพาะไฟล์ที่แชร์กับ session:
- Claude Code / desktop: path ใน ANI repo ที่เชื่อมไว้ เช่น `<ANI>/<slug>/03-images/scene-01.png`
- แชทคลาวด์: stage ไฟล์จากเครื่องผู้ใช้เข้า uploads ของ session ก่อน (เครื่องมือ stage ของ device bridge) แล้วใช้ path นั้น
- รวม ≤10 MB ต่อการเรียก (ภาพ ChatGPT ~2–3 MB → ได้ราว 3 ภาพต่อครั้ง)

ห้ามคลิกปุ่มอัปโหลดหรือช่อง file ตรง ๆ — จะเปิด file picker ของ Windows ที่ควบคุมไม่ได้ ดัก input ก่อนด้วย `javascript_tool`:
```js
(() => {
  const orig = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type !== 'file') return orig.call(this);
    HTMLInputElement.prototype.click = orig;               // ดักครั้งเดียว แล้วคืนค่าเดิม
    this.dataset.aniUpload = '1';                          // ไม่เรียก orig → ไม่เปิด picker
    if (!this.isConnected) { this.hidden = true; document.body.append(this); }
  };
  return 'hooked';
})()
```
จากนั้นคลิกปุ่มอัปโหลดใน Flow (asset picker) → `find` "file input with data-ani-upload" → `file_upload(paths, ref)`
- ส่งหลายไฟล์ได้เมื่อ `document.querySelector('[data-ani-upload]').multiple` เป็น true; ไม่งั้นดักใหม่ทีละไฟล์
- กล่อง `สิทธิ์ในการใช้รูปภาพนี้` / image rights ขึ้น → **ผู้ใช้กด `ฉันยอมรับ` เอง**: แจ้งข้อเดียว รอ แล้วทำต่อ — อัปโหลดรวดเดียวทำให้ผู้ใช้กดครั้งเดียว
- ตรวจว่า tile ภาพขึ้นครบ ชื่อ tile มี `scene-XX` (ไม่ตรงให้ตั้งชื่อใหม่ในหน้า detail) เพื่อค้นได้แน่นอนในขั้นถัดไป

## 3. ต่อฉาก: เฟรมเริ่ม + motion prompt
1. อยู่หน้า grid ไม่ใช่หน้า detail — ปุ่มสร้างในหน้า detail จะ **แก้ asset เดิม** แทนการสร้างคลิปใหม่
2. ช่อง `เริ่ม`/Start → ค้น `scene-XX` → แนบด้วยปุ่มแนบที่ UI ให้ (เช่น "Add to prompt"); ถ้าคลิกแถวรูปแล้วเข้าโหมดแก้ภาพ ให้ถอยกลับ → ตรวจชิปเฟรมเริ่มใน composer ว่าเป็นภาพฉากนั้น
3. composer (`[contenteditable=true]`) ต้องว่าง — ไม่ว่างใช้ปุ่ม `ล้างพรอมต์` เท่านั้น → คลิกช่อง → type motion prompt เต็มจาก `plan_media(slug, "clips")`
4. เปิด popover อ่านราคาอีกครั้ง: ตรงกับที่อนุมัติ, ยังมีเครดิตพอ, ไม่มี tile กำลังสร้างค้างอยู่ (มี → รอให้เสร็จก่อน ไม่งั้นจับคู่ผลกับฉากผิด)
5. `mark_scene(slug, "XX", note="flow submitted HH:MM <บัญชี>")` → กด `เริ่มสร้าง` **ครั้งเดียว**

## 4. รอ + ตรวจ
- คลิป 1–3 นาที: ดู % ที่ pending tile ทุก ~30 วินาที — นานกว่าคาดไม่ใช่ล้ม ห้ามกดซ้ำ
- เสร็จ → คลิกที่ภาพของ tile → หน้า detail: ตั้งชื่อ `scene-XX` (ช่องชื่อแก้ได้ + Enter) → screenshot 1–2 จุดดูว่าตัวละครไม่เปลี่ยน ไม่ morph ชัด ๆ (QC ละเอียดทำที่ frames-grid หลัง collect)
- ถูกปฏิเสธ/ผลผิดเรื่อง → แก้ `motion_prompt` ใน project.json ก่อน แล้วลองใหม่ภายในงบ redo

## 5. ดาวน์โหลด
- `ดาวน์โหลดสื่อ` → **720p ขนาดดั้งเดิม / Original size** เท่านั้น — 1080p/4K คือ upscale ที่คิดเครดิต
- Chrome บันทึกลง Downloads ทันทีด้วยชื่อของ Flow → หาไฟล์ใหม่สุด: `Get-ChildItem $HOME\Downloads\*.mp4 | Sort-Object LastWriteTime | Select-Object -Last 1`
- `python tools/ani.py collect clips --project <slug> --map XX=<path>` → ตรวจคู่ → `--yes`
- กลับหน้า grid (ปุ่มย้อนกลับ) ก่อนเริ่มฉากถัดไป

## 6. เครดิตหมด / สลับบัญชี
แบนเนอร์เครดิตหมด → หยุด รายงานฉากที่เสร็จ/ค้าง + เครดิตที่ใช้ → เสนอให้ใช้ Chrome/บัญชีอื่น ผู้ใช้เลือกผ่าน `list_connected_browsers` — ห้ามสลับเอง

## 7. กู้งานเมื่อ session หลุด
มี note `flow submitted` แต่ `05-clips/` ยังไม่มีไฟล์ฉากนั้น → เปิด grid ดูก่อนทำอย่างอื่น:
- มี tile เสร็จแล้ว → ตั้งชื่อ + ดาวน์โหลด (ไม่เสียเครดิตเพิ่ม)
- ไม่มีเลย → ถามผู้ใช้ก่อนสร้างใหม่ เพราะอาจเสียเครดิตไปแล้ว
