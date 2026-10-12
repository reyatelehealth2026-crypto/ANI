# Flow playbook v2 — `tools/flow.py` ขับ Google Flow ผ่าน Playwright (ยืนยันจริง 2026-09-27)

ป้ายความน่าเชื่อถือ: ✅ ทดสอบบนเครื่องนี้ · 📄 จากเอกสาร/วิจัย (`docs/research/2026-09-26-browser-agent-tools.md`) · ⚠️ ยังไม่ได้ทดสอบ

## 0. สรุป
- งาน Flow ทั้งหมดรันด้วย **คำสั่งเดียวต่อ stage** — Claude ไม่ต้องคลิกทีละปุ่ม ไม่มี Save As ไม่ต้อง `collect`
  - ภาพ: `python tools/ani.py images --project <slug>` (`providers.image = "flow"`) ✅
  - คลิป: `python tools/ani.py clips --project <slug>` → รอบแรกหยุดที่ราคา → ให้ user ok → รันซ้ำพร้อม `--yes` ✅ ถึงขั้นเช็กเครดิต · ⚠️ submit/รอ/โหลดคลิปยังไม่ได้รันจริง (เครดิตหมดวันทดสอบ)
- เครื่องยนต์: Playwright Python `connect_over_cdp` → คลิกเป็น trusted event, หาปุ่มด้วย label ไทย, `expect_download()+save_as()` ✅
- Browser: **Chrome แยกสำหรับ Flow** (`~/.ani/chrome-flow`, พอร์ต `127.0.0.1:9333`) — flow.py เปิดเองถ้ายังไม่รัน ✅ ไม่แตะ Chrome ประจำวันของ user

## 1. Setup ครั้งแรก (ต่อบัญชี Google)
0. ตั้ง `provider_config.flow.project_url` (เปิดโปรเจคใน Flow แล้วคัดลอก URL) — ไม่ตั้ง = flow.py หยุดบอก
1. รัน `python tools/ani.py images --project <slug>` → ถ้ายังไม่ login จะหยุดพร้อมข้อความ และมีหน้าต่าง Chrome ของ Flow เปิดค้างไว้
2. **user** login Google ในหน้าต่างนั้นเอง (Claude ห้ามกรอกรหัส/กดยอมรับแทน) ✅ login ผ่าน ไม่ถูกบล็อก
3. รันคำสั่งเดิมซ้ำ
- เครดิตหมด → ใช้บัญชีอื่น: ตั้ง `provider_config.flow.profile_dir` (โฟลเดอร์ใหม่) + `cdp` (พอร์ตใหม่ เช่น `http://127.0.0.1:9334`) แล้ว login บัญชีนั้นครั้งเดียว
- ความปลอดภัย 📄: พอร์ตนี้ไม่มีกล่อง Allow — process ในเครื่องต่อได้ขณะหน้าต่างเปิด (เฉพาะ cookie ของโปรไฟล์ Flow) → ปิดหน้าต่างเมื่อไม่ใช้; profile dir อยู่นอก repo

## 2. รันงาน
| คำสั่ง | เกิดอะไร |
|---|---|
| `images --project <slug>` | ไม่มีไฟล์ reference → gen reference ก่อน (ไม่ใส่ ingredient) → ทุกฉากที่ขาดภาพ: แนบ reference เป็น ingredient + image prompt → รอ → ตั้งชื่อ tile → โหลด `03-images/scene-XX.jpg` (Flow ส่ง .jpg) |
| `contact` | ดู `03-images/contact-sheet.jpg` ภาพเดียว → `mark` |
| `clips --project <slug>` | อ่านราคาจาก UI แล้วหยุด: `[flow] 01: Flow แจ้ง 10 เครดิต/clip — ยังไม่กด` → Claude แสดงรายการฉาก × ราคาให้ user ok **1 ครั้ง** (กติกาข้อ 4) |
| `clips --project <slug> --yes` | ต่อฉาก: โหมดวิดีโอ/เฟรม/9:16/x1/model → Start frame = tile ภาพของฉากนั้น (ค้นด้วยชื่อ) → motion prompt → กด `เริ่มสร้าง` 1 ครั้ง → รอ (สูงสุด `max_wait` 600 s) → ตั้งชื่อ → โหลด 720p `05-clips/scene-XX.mp4` |
| `frames` → `assemble` → ... | เหมือนเดิม |
- ทำทีละงาน (sequential) ตั้งใจ: จับคู่ tile ↔ ฉากได้แน่นอน; งานยาวให้รันด้วย Bash `run_in_background` แล้วรอ notification
- คลิปใช้ภาพฉากที่อยู่ใน Flow: ชื่อ tile จาก `scene.flow.image.media` **เฉพาะเมื่อ `file` ตรงกับภาพปัจจุบัน** (ภาพถูกแทนด้วย provider อื่น/`collect` → record ถูกล้าง) ไม่งั้นค้นชื่อ `scene-XX` → ไม่เจอ/เจอ >1 = หยุดให้ตั้งชื่อ tile ใน Flow ให้ตรง
- reference เป็นไฟล์ในเครื่อง (ไม่ได้ gen ใน Flow) → ภาพฉากจะแนบ tile ชื่อ `reference` ใน Flow (ตั้งชื่อ tile เองครั้งเดียว)

## 3. state ใน `project.json` + กติกาเครดิต
`scene.flow.{image|clip}` (reference อยู่ที่ `reference.flow.image`) = `{status, at, media, credits, file}`
| status | ความหมาย | รันซ้ำแล้วเกิดอะไร |
|---|---|---|
| `unknown` | เขียนก่อนคลิก Generate — อาจเสียเครดิตไปแล้ว | **หยุด**: เปิดกริด Flow ดู → มีงาน: ตั้งชื่อ tile แล้วใส่ `media` + `status: submitted` / ไม่มี: `--force --scene XX` (**ห้าม** `--force` ทั้งเรื่อง — ฉากอื่นจะถูกสร้างใหม่และเสียเครดิต; reference: ลบ `reference.flow`) |
| `submitted` (ไม่มี media) | Flow รับงานแล้ว แต่ process ตายก่อนงานเสร็จ | หยุดเหมือน unknown |
| `submitted` + `media` | งานเสร็จ ตั้งชื่อ tile แล้ว ยังโหลดไม่เสร็จ | รอ/โหลดต่อ **ไม่กดซ้ำ ไม่ต้อง --yes** |
| `downloaded` | ไฟล์อยู่ที่ `file` | ข้าม (redo ด้วย `mark XX clip=redo`) |
- ห้ามกด Generate ซ้ำเพราะรอนาน/ timeout — งานนานกว่าคาดไม่ใช่งานล้ม
- ราคาอ่านจาก popover settings (`การสร้างจะใช้ N เครดิต`) ทุกงาน (อ่านซ้ำจนค่านิ่ง) — ไม่ใช่ 0 หรืออ่านไม่ได้ → ต้อง `--yes`; **ภาพ** 0 → ไปต่อได้; **คลิป** 0 ไม่เชื่อ (อาจเป็นราคาค้างจากโหมดภาพ) → ยังต้อง `--yes`
- ก่อนเขียน state ทุกงาน flow.py เช็กซ้ำ: อยู่หน้ากริด (ไม่ใช่หน้า detail ที่ปุ่มสร้างจะ **แก้** asset เดิม), asset ที่แนบยังอยู่หลังพิมพ์ prompt, **ไม่มี tile กำลังสร้างค้าง** (มี → หยุด เพราะจะจับคู่ผลลัพธ์ผิดฉาก), เครดิตพอ
- take ใหม่แย่กว่าเก่า → ไฟล์เก่าถูกย้ายไป `03-images/_old/` / `05-clips/_old/` ก่อนเซฟตัวใหม่เสมอ ✅ ย้ายกลับได้ (tile เก่าใน Flow ยังอยู่)

## 4. กติกาเหล็ก
1. **คุม Chrome ของ Flow ได้ทีละตัว** — ห้ามใช้ Claude in Chrome / playwright-cli กับหน้าต่างนั้นระหว่าง flow.py รัน
2. ห้ามส่ง `ctrl+a` / `Delete` / `Backspace` แบบไม่ระบุช่อง (เคยลบ media 6 ไฟล์) — flow.py ใช้ `fill()` + ปุ่ม `ล้างพรอมต์`; ปุ่ม `ย้ายไปที่ถังขยะ` ห้ามแตะ
3. ห้ามกด `ฉันยอมรับ` ในกล่อง **"สิทธิ์ในการใช้รูปภาพนี้"** (ขึ้นตอน upload) แทน user — v2 ไม่ upload: ใช้ asset ใน Flow ด้วยชื่อ ✅
4. ดาวน์โหลดเฉพาะ `ขนาดดั้งเดิม` (`1K` ภาพ / `720p` คลิป) — `2K/4K/1080p` = upscale คิดเงิน
5. JS `.click()` ไม่ยิง submit/download ✅ → คลิกผ่าน Playwright เท่านั้น
6. อย่าต่อ Chrome ประจำวันด้วย CDP ถ้าไม่จำเป็น 📄: บัญชี Flow อยู่ `Profile 3` แต่ last-used คือ `Profile 40` → download setting/แท็บใหม่ไปลงผิดโปรไฟล์

## 5. UI ที่ยืนยันแล้ว (UI ภาษาไทย, 2026-09-27) — ค่าเดียวกับ dict `UI` ใน `tools/flow.py`
| สิ่งที่ใช้ | label / selector |
|---|---|
| popover settings | ปุ่ม `ทริกเกอร์การตั้งค่า` → radio `รูปภาพ`/`วิดีโอ`, โหมดย่อยวิดีโอ `เฟรม`/`องค์ประกอบ`, `9:16`, `x1`–`x4`, dropdown `เลือกกลุ่มผลิตภัณฑ์โมเดล` (menuitem `Nano Banana Pro/2/2 Lite`, `Omni 1.1 Flash`, `Veo 3.1 - Lite/Fast/Quality`); ข้อความราคาเห็นเฉพาะตอน popover เปิด |
| Agent | `button.agent-mode-chip` (`aria-pressed`) — โปรไฟล์ใหม่ปิดอยู่แล้ว |
| composer | `[contenteditable=true]` 1 ช่อง, `เพิ่มองค์ประกอบลงในช่องพรอมต์` (โหมดภาพ), `เริ่ม`/`สิ้นสุด` (โหมดเฟรม), `ล้างพรอมต์`, submit `เริ่มสร้าง` (เครดิตไม่พอ → กลายเป็น `คำเตือนเครดิตไม่เพียงพอ`) |
| asset picker | ใน `.cdk-overlay-container`: ค้น `ค้นหาเนื้อหา` → `role=option` (บรรทัดแรก = ชื่อ) → **คลิกแล้วแนบทันที** ไม่มีปุ่มยืนยัน |
| tile | `flow-tile-container` > `flow-image-tile` / `flow-video-tile`; ภาพมี `img[data-media-id]` (UUID ตรงกับ src ของชิปใน composer), คลิปมีแค่ src ภาพปก; ชื่ออยู่ `.footer-title` (hover footer → หาด้วย role ไม่ได้ ให้คลิกที่ `img`) |
| กำลังสร้าง | `flow-pending-tile` แสดง % — ภาพเสร็จ ~40 s ✅; หลังกดสร้าง composer ล้างตัวเอง ✅ |
| หน้า detail | คลิก `img` ของ tile → ช่องชื่อ `ข้อความที่แก้ไขได้` (แก้ได้ + Enter), `ดาวน์โหลดสื่อ` → menuitem `… ขนาดดั้งเดิม`, กลับ `ปุ่มย้อนกลับเพื่อไปยังหน้าก่อนหน้า` |
| เครดิตหมด | แบนเนอร์ `คุณใช้เครดิต Google Flow หมดแล้ว`; Veo 3.1 Lite = 10 เครดิต/คลิป, Nano Banana 2 = 0 |

## 6. เมื่อ flow.py ล้ม / UI เปลี่ยน
1. อ่านข้อความ error (บอก step + ชื่อ label) และ `scene.flow` ใน project.json — ถ้าเป็น `unknown`/`submitted` ทำตาม §3 ก่อนอย่างอื่น
2. สำรวจหน้า: ต่อ Playwright ที่ `http://127.0.0.1:9333` แล้วอ่าน label ปุ่ม/radio ที่มองเห็น (อ่านอย่างเดียว) หรือ `playwright-cli attach --cdp=http://127.0.0.1:9333` 📄 (ยังไม่ติดตั้ง) — screenshot ย่อเฉพาะตอนสับสน
3. แก้ `UI` ใน `tools/flow.py` → `python tools/test_ani.py` → ลองจริงด้วยงานภาพ (0 เครดิต) → อัปเดต §5
4. ซ่อมไม่ได้ใน 2 รอบ → บอก user + ใช้ทางสำรอง §7

## 7. ทางสำรอง
- **โหมด A** (Chrome ประจำ + `chrome://inspect/#remote-debugging`) 📄⚠️ ยังไม่ implement: Chrome 154 มี toggle จริง ✅ แต่ทุกการต่อมีกล่อง `Allow remote debugging?` ✅ และต้อง reuse แท็บ Flow เดิม + `Page.setDownloadBehavior` + Playwright ≥ 1.60 `no_defaults` — ใช้เมื่อ login โปรไฟล์แยกไม่ได้
- **Claude in Chrome** (วิธี v1): ปิด "Ask where to save" ใน profile ของ Flow ก่อน แล้วทำทีละปุ่ม + `collect clips --map ... --yes`
- **manual**: `providers.video = "manual"` → ทำเองแล้ว `collect`

## 8. ต้นทุนที่วัดได้
- ภาพ 1 งาน ≈ 40 s gen + ~10 s ตั้งชื่อ/โหลด ✅ (รันจริง 5 งาน: reference + ฉาก 02, 03, 04 + redo 02) — Claude ใช้ 1 tool call ต่อ stage
- โหลดคลิป 720p (5.8 MB) 0.2 s, ภาพ 1K 1.2 s, ไม่มี Save As ✅
- คลิป Veo: ⚠️ ยังไม่ได้วัดด้วย flow.py (รอบ v1: 1–3 นาที/คลิป)
