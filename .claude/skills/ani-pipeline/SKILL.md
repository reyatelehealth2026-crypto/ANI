---
name: ani-pipeline
description: ทำหนังสั้น/อนิเมชัน AI ในโฟลเดอร์ ANI ผ่าน MCP ani-studio หรือ `python tools/ani.py` — ใช้เมื่อ user ขอสร้างเรื่องใหม่ สรุปงาน เปิด UI ทำ storyboard ภาพ คลิป พากย์เสียง หรือตัดต่อ
---

# ANI pipeline

## หลักการ
- **LLM ทำ 3 อย่าง**: (1) เขียน/แก้ `project.json` (2) ดูภาพ QC 2 ภาพ แล้ว `mark` (3) ขอ ok เครดิตจาก user ก่อน `clips --yes` — provider `flow` ขับ Google Flow เองด้วย `tools/flow.py`
- **สคริปต์ทำที่เหลือ**: contact sheet, frame grid, xfade, TTS, ดนตรี, ducking, loudness, ซับ, status — ห้ามเขียน ffmpeg เอง
- ทุก stage **idempotent**: ข้ามฉากที่มี output แล้ว; ทำใหม่ด้วย `--scene <id> --force` หรือ `mark <id> image=redo|clip=redo`
- เวลาทั้งหมดคำนวณจาก manifest: `start_i = Σ seconds − i·xfade`, VO = `start + offset` → เปลี่ยน xfade/ลำดับฉากแล้ว VO ยังตรง

## Workflow (เรื่องใหม่)
ทุกครั้งที่ user ขอเรื่องใหม่ ให้สร้าง slug/โฟลเดอร์ใหม่และเขียน `project.json` ต้นฉบับจากโจทย์ครั้งนั้น อย่านำเรื่อง ตัวละคร หรือ prompt จาก `moonpetal-guardian` หรือโปรเจกต์ก่อนหน้ามาใช้เอง; โปรเจกต์เดิมใช้ต่อเมื่อ user ระบุชื่อหรือขอภาคต่อ

ถ้า MCP `ani-studio` เชื่อมต่ออยู่ ให้ใช้ `create_story` เพื่อสร้าง manifest และโฟลเดอร์ใหม่ในครั้งเดียว, `list_stories` / `get_story` เพื่อดูสถานะ, `open_dashboard` เพื่อส่งหน้า UI, `mark_scene` สำหรับ QC และ `run_local_stage` สำหรับขั้นที่ไม่ใช้เครดิต ถ้า MCP ไม่เชื่อมต่อจึงใช้ CLI ด้านล่าง ก่อนสร้างภาพหรือคลิปด้วย provider แบบจ่ายเงิน เรียก `plan_media` เพื่อแสดงฉากและ provider แล้วตรวจราคาจริง ขออนุมัติผู้ใช้ก่อนรัน CLI

1. `python tools/ani.py new <slug>` → เปิด `<slug>/project.json`
2. เขียน manifest (ดู §เขียน project.json) → `validate` จนไม่มี warning → `story` (ให้ user อ่าน `01-story/storyboard.md`)
3. `images` — ค่าเริ่มต้น `manual`: สคริปต์พิมพ์ prompt → สร้างเอง → `collect images --yes` | เปลี่ยนเป็น `flow` เมื่อผู้ใช้ต้องการใช้ Flow และยอมรับค่าใช้จ่ายแล้ว
4. `contact` → **ดู `03-images/contact-sheet.jpg` 1 ครั้ง** → ฉากที่ไม่ผ่าน: `mark XX image=redo note="..."` แล้วแก้ `image_prompt` → `images --scene XX`
5. `clips` — provider `flow`: รันครั้งแรกหยุดที่ราคา → แสดง user ok 1 ครั้ง → `clips --yes` (โหลดเข้า `05-clips/` เอง ไม่ต้อง collect; รันด้วย `run_in_background`) | provider API: รอเสร็จเอง
6. `frames` → **ดู `06-draft/frames-grid.jpg` 1 ครั้ง** → `mark XX clip=redo` ถ้าต้อง gen ใหม่
7. `assemble` → `vo` → `music` → `mix` (พิมพ์ LUFS/TP ให้เห็น) → `subs --burn` ถ้าต้องการซับ
8. `status` → ส่ง `status.md` + path `08-final/final.mp4` ให้ user
ทางลัด: `run --project <slug>` เดินทุก stage และหยุดตรงที่ต้อง manual พร้อมบอกวิธีต่อ (`run --from <stage>`)

## เขียน project.json
- `style` = STYLE BLOCK ภาษาอังกฤษ 1 ย่อหน้า: art style, line/shading, background treatment, lighting, palette, `vertical 9:16 portrait composition, no text, no watermark`
- `characters` = CHARACTER BLOCK: `NAME: age, hair (สี/ทรง/จุดเด่น), eyes, outfit ทุกชิ้น, props` — ใช้ชุดเดียวทุกฉาก (consistency)
- `reference.prompt` = character sheet (front + 3/4 view, plain background) — ใช้เป็น reference image ให้ provider ที่รองรับ (gemini/openai/fal)
- แต่ละ scene:
  - `seconds` 8 (Veo/Flow ให้ 8 s; API รับ 4/6/8 ปัดขึ้น), `mood` ∈ `calm | threat | resolve | climax | resolution` (ขับดนตรี synth)
  - `image_prompt` เฉพาะฉากนี้: shot type + subject + action + environment + atmosphere (style/characters ต่อท้ายให้อัตโนมัติ)
  - `motion_prompt`: การเคลื่อนกล้อง 1 อย่าง + สิ่งที่ขยับ 3–5 อย่าง + mood; ห้ามเปลี่ยนองค์ประกอบภาพ (suffix กัน morphing ต่อให้เอง)
  - `vo`: ไทย ≤ 14 คำ/บรรทัด อ่านออกเสียง ≤ 5 s; `offset` 0.5–1.0 s จากต้นฉาก; บทตัวละครใส่ speaker ที่มีใน `voices`
- `edit`: `xfade 0.5`, `fade_out 1.0`, `clip_audio 0.28` (เสียงบรรยากาศจาก Veo), `duck_ratio 4` / `duck_threshold 0.1` (ดนตรีหลบพากย์ ≈ −10 dB), `lufs -14`, `true_peak -1.5`
- `providers`: image `flow|manual|gemini|openai|fal`, video `flow|manual|gemini|fal`, tts `edge|elevenlabs|file`, music `synth|file` (`music.file` = เพลงของตัวเอง/Suno)
- `subs`: `size`/`margin_v` เป็น px ของวิดีโอ (default 56 / 220 = ตัวหนาอ่านง่าย วาง 1/3 ล่าง ไม่บังหน้า); `enabled: true` ให้ `run` burn ซับอัตโนมัติ
- เสียงไทย edge-tts: `th-TH-PremwadeeNeural` (หญิง), `th-TH-NiwatNeural` (ชาย); ปรับ `tts.rate` เช่น `-5%`

## QC protocol (ประหยัด token)
- ดูภาพรวมภาพเดียว (`contact-sheet.jpg` / `frames-grid.jpg`) แล้วตัดสินทุกฉากในรอบเดียว
- เกณฑ์ภาพ: ตัวละครตรง bible (ผม/ตา/ชุด/props), องค์ประกอบตรง storyboard, ไม่มีตัวหนังสือ/ลายน้ำ, สไตล์เดียวกันทุกฉาก
- เกณฑ์คลิป (3 เฟรม t=1/กลาง/ท้าย): ไม่ morph, กล้องเคลื่อนตามสั่ง, ท้ายคลิปต่อฉากถัดไปได้
- บันทึกผลด้วย `mark XX image=pass|redo clip=pass|redo note="เหตุผลสั้น ๆ"` — status.md จะอัปเดตเอง
- ห้ามเปิด mp4 หรือเฟรมทีละไฟล์ ยกเว้น user ขอดูจุดเฉพาะ

## Flow (provider `flow`) — `tools/flow.py`
**อ่าน `flow-playbook.md` ก่อนทุกครั้งที่ Flow ล้ม/UI เปลี่ยน** — v2: Playwright ต่อ Chrome แยกของ Flow (`~/.ani/chrome-flow`, พอร์ต 9333, flow.py เปิดเอง; login ครั้งแรก user ทำ) → คลิก trusted, หาปุ่มด้วย label ไทย, โหลดตรงเข้าโฟลเดอร์ฉาก ไม่มี Save As
- state ต่อฉากอยู่ `scene.flow` ใน project.json: `unknown`/`submitted` ไม่มี media = หยุดให้ตรวจกริดก่อน (ห้ามกดซ้ำ) · `submitted`+media = รันซ้ำแล้วโหลดต่อ
- เครดิต: ราคาอ่านจาก UI; ≠ 0 ต้อง `--yes` หลัง user ok · เครดิตหมด → หยุดรายงาน (เปลี่ยนบัญชีได้ด้วย `profile_dir`/`cdp` ใหม่)
- ห้ามคุมหน้าต่าง Flow พร้อมกันหลายเครื่องมือ; ห้ามกด `ฉันยอมรับ` สิทธิ์รูปภาพแทน user; ห้ามโหลดแบบ upscale (2K/4K/1080p)

## collect
- `collect clips` = ไฟล์ mp4 ใน ~/Downloads ที่ใหม่กว่า 6 ชม. เรียง mtime เก่า→ใหม่ จับคู่ฉากที่ยังขาดตามลำดับ id; dry-run เสมอจนใส่ `--yes`
- ผิดคู่: `--map 03=C:/Users/.../Flow_xxx.mp4 04=...`; ไฟล์เก่ากว่า: `--hours 48`; โฟลเดอร์อื่น: `--src DIR`
- ไฟล์เก่าของฉากที่ redo จะถูกย้ายไป `_old/` (ไม่ลบ) และ log ไว้ที่ `<slug>/.collect.log`

## Providers / keys
- ใส่ key ใน `ANI/.env`: `GEMINI_API_KEY=`, `OPENAI_API_KEY=`, `FAL_KEY=`, `ELEVENLABS_API_KEY=` แล้วเปลี่ยน `providers` ใน manifest — ไม่ต้องแก้โค้ด
- model ปรับที่ `provider_config` (`gemini.video_model`, `fal.video_model`, `fal.video_params` สำหรับ param เฉพาะ model)
- API adapters (gemini/openai/fal/elevenlabs) ยังไม่เคยรันกับ key จริง — รอบแรกที่ใช้ให้ทดสอบ 1 ฉากก่อน (`--scene 01`) แล้วค่อยทั้งเรื่อง

## รายงานให้ user
- หลังทุกช่วง: `python tools/ani.py status` แล้วสรุป ≤ 5 บรรทัด: ทำอะไรเสร็จ, ฉากไหน redo เพราะอะไร, next action 1 อย่าง, เครดิต/เงินที่ใช้
- ส่งมอบ: path `08-final/final.mp4` (+ `final-subs.mp4`), ค่า LUFS/TP จาก `mix`, `status.md`

## Troubleshooting
- `assemble` warning คลิปสั้นกว่า `seconds` → แก้ `seconds` ให้ตรงหรือ gen ใหม่; คลิปไม่มีเสียง (Kling/manual) → ใส่ silent track ให้เอง
- `vo` ล้มเหลวบางบรรทัด (เน็ต) → รัน `vo` ซ้ำ ข้ามที่เสร็จแล้ว
- `mix` เตือน limiter ทำงานหนัก → ลด `music.gain` หรือ `edit.clip_audio`
- ซับไม่ขึ้น → ฟอนต์ไทยใน `subs.font` ต้องมีในเครื่อง (`Leelawadee UI`, `Tahoma`)
