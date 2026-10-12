# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# ANI — AI short-film pipeline

โฟลเดอร์นี้ผลิตหนังสั้น/อนิเมชัน AI ด้วย `python tools/ani.py` — ค่าแนะนำคือ 9:16, 5 ฉาก × 8 s แต่เรื่องและจำนวนฉากกำหนดใน `project.json`; LLM เขียน manifest + ดูภาพ QC, สคริปต์ทำที่เหลือ

เมื่อ user สั่ง "เรื่องใหม่" ให้สร้าง slug ใหม่ด้วย `python tools/ani.py new <slug>` แล้วเขียนเรื่อง ตัวละคร ฉาก prompt และบทพูดใหม่ใน `<slug>/project.json` ตามคำขอ ห้ามยึดเรื่องหรือตัวละครจากโปรเจกต์เดิม เว้นแต่ user ขอภาคต่อ; สร้างหลายเรื่องใน repo เดียวกันได้
เอกสาร: `docs/superpowers/specs/2026-09-26-ani-pipeline-design.md` | workflow เต็ม: skill `ani-pipeline`

## Claude Code + MCP
เมื่อเปิด Claude Code จาก root ของ repo ให้ใช้ server `ani-studio` ใน `.mcp.json` หลังผู้ใช้ยืนยัน trust/อนุมัติ server ครั้งแรก ตรวจสถานะด้วย `/mcp` หรือ `claude mcp get ani-studio` ถ้า server ยังไม่เชื่อมต่อ ให้ใช้ CLI ด้านล่างแทน ไม่ต้องแก้ `.mcp.json` เป็น path เฉพาะเครื่อง

- เรื่องใหม่: เขียนเรื่องใหม่จากโจทย์ครั้งนี้ แล้วเรียก `create_story` พร้อม title, style, characters และ scenes ครบในครั้งเดียว; slug ใหม่ทุกเรื่อง ห้ามดึงเรื่องเก่ามาใช้เอง
- สรุป: `list_stories` / `get_story`; หน้า UI: `open_dashboard` แล้วส่ง URL localhost ให้ผู้ใช้
- QC: `mark_scene`; ขั้นที่ไม่ใช้เครดิต: `run_local_stage`; วางแผนภาพ/คลิป: `plan_media`
- โหมดเอเจนท์: อ่าน `get_agent_status` และวงเงินที่ผู้ใช้บันทึก อ่านราคาปัจจุบันใน Flow แล้วเรียก `reserve_agent_generation` ก่อนกดสร้างทุกงาน ภายในวงเงินไม่ถามเครดิตซ้ำ งานเดิมต้อง resume ไม่กดซ้ำ ดาวน์โหลดต้นฉบับแล้วเรียก `collect_agent_result` เพื่อแสดงในแดชบอร์ด หากไม่มีวงเงินที่บันทึก ให้ขออนุมัติก่อนใช้เครดิต

## คำสั่งหลัก
```
python tools/ani.py new <slug>                       # สร้างโปรเจค + template
python tools/ani.py run --project <slug> [--from S --to S]  # เดินทุก stage หยุดเมื่อต้อง manual/Flow
python tools/ani.py <stage> --project <slug> [--scene 03] [--force]
python tools/ani.py clips --project <slug> [--yes]          # flow: รอบแรกบอกราคา, --yes หลัง user ok (tools/flow.py)
python tools/ani.py collect clips --project <slug> [--yes]   # ย้ายไฟล์จาก ~/Downloads เข้าฉากที่ขาด
python tools/ani.py mark 03 clip=redo note="..." --project <slug>
python tools/test_ani.py                             # pipeline (ไม่ต้องมี ffmpeg/network)
python tools/test_flow_setup.py                      # Flow login/cookies/อนุมัติเครดิต (ไม่ใช้บัญชีจริง)
python tools/test_agent_workflow.py                  # standing budget, กันกดซ้ำ, collect
python tools/test_ani.py TimelineTests.test_moonpetal_timeline      # รันเทสต์เดียว (unittest)
python tools/ani.py ui                               # หน้าเว็บสรุปทุกเรื่อง + รายละเอียดฉาก (localhost)
```
stages: validate → story → images → contact → clips → frames → assemble → vo → music → mix → subs → status

## สถาปัตยกรรม `tools/`
- `ani.py` — แกนกลาง: manifest (`load_project`/`save_project`), `timeline()`, `STAGES`, CLI; `run_stage()` lazy-import โมดูลตาม stage; `ROOT` = `$ANI_ROOT` หรือ clone (ใน plugin cache → `~/ANI`); `scene_needs()`/`is_stale()` ทำใหม่เมื่อ input เปลี่ยน (`<slug>/.ani-inputs.json`)
- `gen.py` — provider ภาพ/คลิป (manual/flow/gemini/openai/fal) + `collect` จาก Downloads; `media.py` — ffmpeg/Pillow (contact, frames, assemble xfade, mix loudness 2-pass, subs); `audio.py` — TTS (edge/elevenlabs/file) + ดนตรี synth
- `flow.py` — Google Flow ผ่าน CDP (Playwright); `flow_auth.py` — โปรไฟล์ Chrome `.local/chrome-flow` (CDP 9443) + cookies เข้ารหัส DPAPI; `flow_studio.py` — serialize งานเบราว์เซอร์ของแดชบอร์ด, preview เครดิต, เรียก CLI เดิม
- `dashboard.py` + `ui/` — เว็บ localhost (127.0.0.1:8765); `mcp_server.py` (FastMCP stdio) → `mcp_actions.py` (ops ที่ปลอดภัย ไม่ใช้เครดิต); `agent_workflow.py` — session evidence, standing budget, reservation แบบ idempotent (CLI: `python tools/agent_workflow.py status|session|reserve|collect --data-file <JSON>`)
- ปลั๊กอิน: `.claude-plugin/plugin.json` (MCP ผ่าน `${CLAUDE_PLUGIN_ROOT}`) + `marketplace.json`; skill ของปลั๊กอิน = `skills/ani-studio/` (CLAUDE.md ไม่ถูกโหลดในโหมดปลั๊กอิน → กติกาสำคัญต้องอยู่ใน skill); ตรวจด้วย `claude plugin validate .`
- เทสต์ใช้ `unittest` + `sys.path` ชี้ `tools/` ต้องรันจาก root; ทุก stage ใหม่ต้องเพิ่ม option ใน `ani.py`/โมดูล + เทสต์

## กติกา
1. **source of truth = `<slug>/project.json`** — แก้เรื่อง/prompt/บทพูด/provider ที่นั่น แล้วรัน stage ใหม่ ห้ามแก้ storyboard.md/prompts.md ตรง ๆ (ถูก render ทับ)
2. **ห้ามเขียนคำสั่ง ffmpeg/edge-tts/numpy เอง** — ทุกอย่างอยู่ใน `tools/` ถ้าขาดความสามารถ ให้เพิ่ม option ใน tools + test ไม่ใช่รัน ad hoc
3. **QC ด้วยภาพเดียว**: ภาพฉาก → `03-images/contact-sheet.jpg`, คลิป → `06-draft/frames-grid.jpg` ห้ามเปิดวิดีโอหรือเฟรมทีละไฟล์ (เปลือง token)
4. **ก่อนใช้เครดิต Flow/API** อ่านราคาปัจจุบันและรักษาวงเงินที่ผู้ใช้อนุญาต สำหรับโหมดเอเจนท์ที่มี standing budget ให้ใช้การจองเครดิตรวมและเดินงานต่อโดยไม่ถามซ้ำ หยุดเมื่อเกินวงเงินหรืออ่านราคาไม่ได้; provider อื่นที่ไม่ได้อยู่ในนโยบายยังต้องขออนุมัติ
5. **redo รายฉาก** ใช้ `mark <id> image=redo` แล้ว `images --scene <id>` (ไม่ `--force` ทั้งเรื่อง)
6. **รายงาน = `ani status`** (เขียน `status.md`) ไม่ต้องสรุปซ้ำยาว ๆ; ไฟล์ output ชื่อคงที่ (`06-draft/draft.mp4`, `08-final/final.mp4`)
7. ไฟล์ media ไม่เข้า git; API key อยู่ใน `ANI/.env` เท่านั้น
