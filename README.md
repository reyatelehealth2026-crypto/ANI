# ANI — AI short-film pipeline

สร้างหนังสั้นแนวตั้งจาก `project.json`: เขียนเรื่องและ prompt ครั้งเดียว แล้วใช้ CLI สร้างภาพ/คลิป ตรวจ QC ตัดต่อ พากย์ ทำดนตรี ผสมเสียง และทำซับ โปรเจกต์ที่ผลิตไว้เดิมไม่ได้รวมใน repo เพื่อให้ clone แล้วเริ่มเรื่องใหม่ได้ทันที

## สิ่งที่ต้องมี

- Python 3.12 ขึ้นไป
- `ffmpeg` และ `ffprobe` บน `PATH`
- Chrome เมื่อใช้ Google Flow; อินเทอร์เฟซ Flow ใน `tools/flow.py` ทดสอบกับ Chrome บน Windows
- อินเทอร์เน็ตเมื่อใช้ Edge TTS, Flow หรือ API provider

## เริ่มใช้งาน

```powershell
git clone <repo-url> ANI
cd ANI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python tools/test_ani.py
python tools/ani.py new my-film
```

`new` สร้าง manifest ว่างแบบไม่ผูกกับเรื่องใด เปิด `my-film/project.json` แล้วเขียน `style`, `characters`, `scenes`, prompt และบทพูดของเรื่องใหม่ (เพิ่มฉากได้ตามต้องการ) จากนั้นรัน:

```powershell
python tools/ani.py validate --project my-film
python tools/ani.py run --project my-film
```

โปรเจกต์ใหม่ตั้ง `image` และ `video` เป็น `manual` เพื่อให้เริ่มได้โดยไม่ต้องมีบัญชีหรือเครดิต ระบบจะหยุดและพิมพ์ prompt พร้อมที่วางไฟล์เมื่อถึงขั้นที่ต้องสร้างสื่อเอง หลังนำไฟล์เข้าแล้วรันต่อจาก stage ที่หยุด:

```powershell
python tools/ani.py collect images --project my-film
python tools/ani.py collect images --project my-film --yes
python tools/ani.py run --from images --project my-film
```

`collect` แสดงการจับคู่ไฟล์จาก Downloads ก่อนเสมอ ตรวจคู่ฉากให้ถูกก่อนใส่ `--yes`; ใช้ `--map 01=C:/path/to/image.png` หากต้องจับคู่เอง วิธีเดียวกันใช้กับ `collect clips` ไฟล์สุดท้ายอยู่ที่ `my-film/08-final/final.mp4` และสถานะอยู่ใน `my-film/status.md`

## ใช้ Google Flow หรือ API

เปลี่ยน `providers.image` / `providers.video` ใน `project.json` เป็น `flow`, `gemini`, `openai` หรือ `fal` ตาม provider ที่รองรับ ถ้าใช้ Flow ให้ตั้ง `provider_config.flow.project_url` เป็น URL ของโปรเจกต์ Flow ของตนเอง และใช้ Chrome ลงชื่อเข้าใช้เมื่อสคริปต์เปิดครั้งแรก ก่อนสร้างคลิปแบบเสียเครดิต รัน `clips` เพื่อดูราคา แล้วจึงรัน `clips --yes` หลังตรวจค่าใช้จ่าย

ถ้าใช้ API ให้คัดลอก `.env.example` เป็น `.env` แล้วกรอก key ที่ต้องใช้ ไฟล์ `.env` และ `project.json` ของเรื่องใหม่ถูก Git ignore ไว้ เพราะอาจมี key, URL โปรเจกต์ หรือข้อมูลบัญชีส่วนตัว อย่าใส่ key ในไฟล์ที่ commit

## หน้า UI สรุปงานและเชื่อมต่อ Flow

```powershell
python tools/ani.py ui
```

คำสั่งนี้เปิดหน้าเว็บในเครื่องที่ `http://127.0.0.1:8765/` แสดงทุกเรื่องที่มี `project.json` ใน repo พร้อมจำนวนฉาก/ภาพ/คลิป สถานะ final รายละเอียดเรื่อง provider, style, ตัวละคร, prompt, บทพากย์ และ QC รายฉาก ดู final ได้ในหน้าเดียว กด **รีเฟรช** เพื่ออ่านไฟล์ล่าสุดหลังรัน pipeline ใช้ `--port 9000` เปลี่ยนพอร์ต หรือ `--no-open` หากไม่ต้องการให้เปิด browser เอง UI รับการเชื่อมต่อจากเครื่องตัวเองเท่านั้น

ส่วน **เชื่อมต่อ Flow** บนหน้าแรก:

1. กด **เปิด Chrome เพื่อล็อกอิน** แล้วลงชื่อเข้าใช้ Google ด้วยตัวเอง หรือเลือก **นำเข้า cookies .txt / .json**
2. รองรับ Netscape cookies.txt (7 ช่องคั่นด้วย Tab รวม `#HttpOnly_`), JSON array จากส่วนขยาย และ Playwright storageState ตรวจชนิดไฟล์ให้อัตโนมัติ
3. ใส่ URL โปรเจกต์ Flow แล้วกด **บันทึก URL และตรวจสอบล็อกอิน** ระบบจะขึ้นพร้อมสร้างเมื่อพบเครื่องมือสร้างในโปรเจกต์จริง การมี cookies อย่างเดียวไม่ถือว่าเชื่อมต่อสำเร็จ
4. เลือกเรื่องแล้วกด **ใช้ Flow สำหรับเรื่องที่เลือก** เพื่อบันทึก provider และเซสชันลง manifest
5. กด **ดูแผนสร้างภาพ** หรือ **ดูแผนสร้างคลิป** ระบบอ่านเครดิตปัจจุบันจากหน้า Flow แสดงฉากและเครดิตรวมประมาณการ จากนั้นติ๊กยืนยันและกด **เริ่มสร้างอัตโนมัติ**

สร้างภาพให้ครบก่อนสร้างคลิป ระบบสร้างและดาวน์โหลดทีละฉากด้วย pipeline เดิม พร้อมแสดง log งานบนหน้าเว็บ แผนมีอายุ 5 นาที ใช้ได้ครั้งเดียว และหยุดถ้า manifest/รายการงานเปลี่ยนหรือเครดิตต่องานสูงกว่าที่อนุมัติ ไม่กด Generate หากอ่านเครดิตไม่ได้

โปรไฟล์ Chrome ของ dashboard อยู่ใน `.local/chrome-flow` ใช้พอร์ต CDP 9443 ต่างจากค่า CLI เดิม เซสชันอยู่ในโปรไฟล์นี้; cookies ที่นำเข้ามีสำเนาเข้ารหัสด้วย Windows DPAPI ใน `.local/flow-cookies.dpapi` ใช้ได้เฉพาะผู้ใช้ Windows เดิม ไม่มี cookies ดิบใน source/logs และ `.local/` ถูก Git ignore ไว้ หาก cookies หมดอายุหรือ Google ไม่ยอมรับ ให้ล็อกอินผ่าน Chrome อีกครั้ง ไม่รับรองว่า cookies สามารถใช้ได้ตลอดไป

ทดสอบส่วนเชื่อมต่อและการอนุมัติเพิ่มเติมด้วย `python tools/test_flow_setup.py` (ไม่ใช้บัญชีจริงหรือเครดิต)

## ใช้เป็น MCP / Codex plugin

ติดตั้ง dependencies จาก `requirements.txt` ตามขั้นเริ่มใช้งาน แล้วตั้ง MCP host ให้เปิด stdio server ใน clone นี้ (ใช้ Python จาก `.venv` ที่ติดตั้ง dependencies แล้ว):

```toml
[mcp_servers.ani_studio]
command = "C:\\path\\to\\ANI\\.venv\\Scripts\\python.exe"
args = ["C:\\path\\to\\ANI\\tools\\mcp_server.py"]
startup_timeout_sec = 30
tool_timeout_sec = 3600
```

ใส่บล็อกนี้ใน `~/.codex/config.toml` โดยเปลี่ยน `C:\path\to\ANI` เป็น path ของ clone จริง บน macOS/Linux ใช้ `.venv/bin/python` แทน Python จะอ่านโฟลเดอร์ที่มี server เป็น root เสมอ จึงสร้างเรื่องใหม่ใน clone นั้นได้ซ้ำโดยไม่ผูกกับเรื่องก่อน ไม่ต้องรัน `tools/mcp_server.py` ใน terminal แยก เพราะ MCP host จะเปิดเอง

repo มี `.codex-plugin/plugin.json`, `.mcp.json` และ `skills/ani-studio/SKILL.md` สำหรับใช้เป็น Codex plugin จากโฟลเดอร์นี้ด้วย หากใช้งานผ่าน plugin ให้แน่ใจว่า MCP process เห็น Python ที่ติดตั้ง `requirements.txt` แล้ว; หากไม่แน่ใจ ให้ใช้การตั้ง MCP ตรงตามตัวอย่างด้านบน

MCP มีเครื่องมือ `list_stories`, `get_story`, `create_story`, `mark_scene`, `plan_media`, `run_local_stage` และ `open_dashboard` เครื่องมือ `create_story` รับพล็อต/ตัวละคร/ฉากใหม่และไม่เขียนทับโปรเจกต์เดิม `open_dashboard` ส่ง URL ของ UI แบบ read-only บน `127.0.0.1` กลับมา หน้า UI จะทำงานระหว่างที่ MCP server ยังเชื่อมต่ออยู่

MCP ไม่เรียก image/video provider และไม่จ่ายเครดิตเอง `plan_media` แสดงฉากและ provider ที่จะใช้ การสร้างจริงต้องอ่านราคาปัจจุบันและรักษาวงเงินที่บันทึกหรือได้รับอนุมัติ `run_local_stage` จำกัดเฉพาะ stage ที่ไม่สร้างภาพ/คลิปแบบเสียเครดิต

### เอเจนท์ทำงานอัตโนมัติ

ผู้ใช้พิมพ์ไอเดียในแชตกับเอเจนท์ แดชบอร์ดแสดงสถานะ Flow และผลลัพธ์เป็นหลัก ปุ่มล็อกอิน นำเข้า cookies และควบคุมด้วยมืออยู่ในส่วนตั้งค่าที่พับไว้ เอเจนท์ตรวจปุ่มบัญชีในหน้า Flow จริงก่อนรายงาน `report_flow_session`; ผลตรวจมีอายุ 15 นาที และตรวจใหม่เมื่อเริ่มคำสั่ง

ตั้งวงเงินรวมต่อคำสั่งครั้งเดียวในส่วนตั้งค่า (ทั้งภาพและคลิปรวมกันต่อเรื่องใหม่) เอเจนท์อ่าน `get_agent_status`, ออกแบบเรื่องด้วย `create_story`, อ่านเครดิตปัจจุบันจากเบราว์เซอร์ แล้วใช้ `reserve_agent_generation` ก่อนส่งแต่ละงาน ถ้า `submit=false` ห้ามส่งซ้ำ ให้ทำต่องานเดิม เมื่อดาวน์โหลดต้นฉบับแล้วเรียก `collect_agent_result` เพื่อคัดลอกเข้าโปรเจกต์และสร้าง contact/frames ให้แดชบอร์ด จากนั้นตรวจ QC ด้วย `mark_scene` และทำขั้นตอนในเครื่องตามคำขอ หากเกินวงเงินหรืออ่านราคาไม่ได้ให้หยุดก่อนกดสร้าง

ถ้า MCP ยังไม่เชื่อมต่อ ใช้ `python tools/agent_workflow.py status` หรือ `session|reserve|collect --data-file <JSON>` ได้เหมือนกัน ระบบนี้ใช้เอเจนท์ที่กำลังทำงานในแชตเพื่อออกแบบและควบคุมเบราว์เซอร์ ไม่ใช่บริการ AI ที่รันเองขณะปิดแชต การใช้เบราว์เซอร์ของเอเจนท์แยกจากการเชื่อมต่อ CDP ของ ANI ซึ่งอาจยังต้องแก้การตั้งค่าในเครื่อง

### ติดตั้งเป็นปลั๊กอิน Claude Code

repo นี้เป็นทั้ง plugin และ marketplace (`.claude-plugin/`) ติดตั้งให้ใช้ได้จากทุกโฟลเดอร์

**เครื่องใหม่ (Windows) — คำสั่งเดียว** หลังติดตั้ง Python 3.12+, ffmpeg และ Claude Code:

```powershell
git clone https://github.com/reyatelehealth2026-crypto/ANI.git
cd ANI
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

สคริปต์สร้าง `.venv` ติดตั้ง requirements ตั้ง `ANI_ROOT` และติดตั้งปลั๊กอิน `ani@ani` ให้ ส่วน `.env` และการล็อกอิน Flow ต้องทำเองในแต่ละเครื่อง หรือติดตั้งเองทีละขั้น:

```text
/plugin marketplace add reyatelehealth2026-crypto/ANI
/plugin install ani@ani
```

หรือจาก clone ในเครื่อง: `claude plugin marketplace add C:\path\to\ANI` แล้ว `claude plugin install ani@ani` ปลั๊กอินมี MCP `ani-studio` และ skill `ani-studio`

เรื่องทั้งหมดเก็บที่ `ANI_ROOT` — ตั้ง environment variable `ANI_ROOT` ชี้ไปที่ clone นี้ (แนะนำ: ใช้ `.venv` ของ clone ได้เลยและเห็นเรื่องเดิม) ถ้าไม่ตั้ง ปลั๊กอินจะใช้ `~/ANI` เพื่อไม่ให้ไฟล์หายตอนอัปเดตปลั๊กอิน Python ที่รัน server ต้องมี `requirements.txt` — server หา `.venv` ใน clone หรือใน `ANI_ROOT` ให้เองถ้า `python` บน PATH ยังไม่มี `fastmcp`

### ใช้กับ Claude Code

ไฟล์ `.mcp.json` เดียวกันใช้กับ Claude Code ในโปรเจกต์นี้ได้อยู่แล้ว เปิด terminal จาก root ของ clone หลัง activate `.venv` และติดตั้ง dependencies แล้วรัน `claude` ครั้งแรก ให้ยืนยัน workspace trust และอนุมัติ MCP server `ani-studio` ที่ Claude แสดง จากนั้นพิมพ์ `/mcp` เพื่อตรวจว่าเชื่อมต่อ หรือเช็คก่อนด้วย `claude mcp get ani-studio` (สถานะ Pending approval หมายถึงยังต้องเปิด `claude` เพื่ออนุมัติ) ไม่ต้องเพิ่ม server ซ้ำด้วย `claude mcp add` เพราะโปรเจกต์มี `.mcp.json` อยู่แล้ว

Claude Code จะอ่าน `CLAUDE.md` และ `.claude/skills/ani-pipeline/SKILL.md` เพื่อใช้ `create_story` กับเรื่องใหม่, `get_story`/`list_stories` สำหรับรายละเอียด และ `open_dashboard` เพื่อเปิด UI เครื่องมือทำงานกับ clone นี้ ไม่ดึงพล็อตของเรื่องก่อนมาเป็นค่าเริ่มต้น การเชื่อมต่อแบบนี้สำหรับ Claude Code ที่รันในเครื่อง; Claude chat บนเว็บไม่สามารถเปิด stdio server หรือ URL `localhost` ของเครื่องคุณโดยตรง

## คำสั่งที่ใช้บ่อย

```text
python tools/ani.py new <slug>
python tools/ani.py run --project <slug> [--from stage]
python tools/ani.py <stage> --project <slug> [--scene 03] [--force]
python tools/ani.py mark 03 image=redo --project <slug>
python tools/ani.py collect images|clips --project <slug> [--yes]
python tools/ani.py subs --project <slug> --burn
python tools/ani.py status --project <slug>
python tools/ani.py ui [--port 8765]
```

ลำดับ stage: `validate → story → images → contact → clips → frames → assemble → vo → music → mix → subs → status` ใช้ `--help` ดูตัวเลือกทั้งหมด Codex อ่าน `AGENTS.md`, Claude อ่าน `CLAUDE.md`; สำหรับ workflow และข้อควรระวังของ Flow ดู `.claude/skills/ani-pipeline/SKILL.md` และ `flow-playbook.md`

`project.json` เป็นแหล่งข้อมูลหลัก: แก้ prompt/บทพูดที่นี่ ไม่แก้ไฟล์ storyboard หรือ prompts ที่สร้างอัตโนมัติ หลังแก้ prompt/บทพูด pipeline จะทำเฉพาะ asset ที่ input เปลี่ยนให้เอง (ภาพ ← image prompt, คลิป ← motion prompt หรือภาพใหม่, VO ← บท/เสียง, ดนตรี ← mood/ตั้งค่า) โดยจำ fingerprint ไว้ใน `<slug>/.ani-inputs.json`; ไฟล์ที่เห็นครั้งแรกถือว่าตรงกับ input ปัจจุบัน ขั้นที่เสียเครดิตยังผ่านการอนุมัติราคาเหมือนเดิม ใช้ `--force` หรือ `mark` เมื่ออยากทำใหม่ทั้งที่ input ไม่เปลี่ยน

สั่งทำเรื่องใหม่ได้ซ้ำทุกเมื่อ: ใช้ `python tools/ani.py new another-film` แล้วเขียน `another-film/project.json` จากโจทย์ใหม่ แต่ละเรื่องมีไฟล์และสถานะแยกกัน CLI สร้างโครงโปรเจกต์; ผู้ใช้หรือ AI agent เป็นผู้แต่งเรื่องและกรอก manifest จึงไม่มีพล็อตหรือตัวละครที่ถูกล็อกไว้ในโค้ด

ถ้าใช้ AI agent สามารถสั่งตรง ๆ เช่น “สร้างเรื่องใหม่แนวสืบสวนในเมืองลอยฟ้า” agent จะตั้ง slug ใหม่ สร้าง manifest จากโจทย์นั้น แล้วเดิน pipeline ให้ เรื่องถัดไปใช้ slug ใหม่และไม่แตะไฟล์ของเรื่องก่อน

## เผยแพร่เป็น repo ต้นแบบ

ก่อนเผยแพร่ ให้ตรวจ `git status --short` ว่ามีเฉพาะโค้ด เอกสาร และไฟล์ตั้งค่าตัวอย่าง จากนั้นสร้าง commit และเพิ่ม remote ของตนเอง:

```powershell
git init -b main
git add .gitignore .env.example .mcp.json .codex-plugin AGENTS.md CLAUDE.md README.md requirements.txt tools docs .claude skills
git status --short
git commit -m "Prepare reusable ANI template"
git remote add origin <repo-url>
git push -u origin main
```

ไฟล์งานของ `crimson-blade` และ `moonpetal-guardian` ถูก ignore ไว้ในเครื่องนี้ รวมถึงไฟล์งาน/manifest ที่สร้างใหม่ในระดับบนสุด เมื่อ clone ไปแล้วให้ใช้ `python tools/ani.py new <slug>` เพื่อเริ่มเรื่องใหม่
