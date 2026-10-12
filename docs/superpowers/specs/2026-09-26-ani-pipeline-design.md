# ANI Pipeline — Design Spec

วันที่: 2026-09-26 | สถานะ: approved-by-default (user สั่งให้เขียน spec → plan → implement ต่อเนื่อง) | ดู assumption ที่ §11

## 1. เป้าหมาย

ย้าย workflow ผลิตหนังสั้น AI ที่ทำใน Claude Cowork (เรื่อง *Moonpetal Guardian*) มาเป็นระบบที่ **Claude Code ขับได้ด้วยคำสั่งเดียวต่อ stage**:

- **LLM ทำเฉพาะงานสร้างสรรค์/ตัดสินใจ**: เขียน `project.json` (เรื่อง, character bible, prompt ภาพ/motion, บทพากย์), ดูภาพ QC 2 ภาพ, สั่ง redo รายฉาก
- **งาน deterministic เป็นสคริปต์ทั้งหมด**: contact sheet, frame grid, assemble (xfade), TTS, music, mix + ducking + loudness, subtitle, status
- **Provider สลับได้ด้วย config** ไม่แก้โค้ด: image = `manual | gemini | openai | fal`, video = `flow | manual | gemini | fal`, tts = `edge | elevenlabs | file`, music = `synth | file`
- **Idempotent + redo รายฉาก**: ทุก stage ข้ามฉากที่มี output แล้ว, `--scene 03` / `--force` ทำใหม่เฉพาะจุด

### Success criteria
1. `python tools/ani.py run --from contact` บน `moonpetal-guardian/` (asset เดิม, ไม่ใช้เครดิต/API) ได้ `08-final/final.mp4` = 720x1280, 24 fps, 38.0 s, integrated loudness -14 ± 1 LUFS, true peak ≤ -1 dBTP
2. `python tools/test_ani.py` ผ่านทุกข้อ (timeline, VO time, xfade graph, srt, collect mapping, manifest validation)
3. โปรเจคใหม่: `ani new <slug>` → Claude เขียน `project.json` → `ani run` เดินทุก stage ที่เดินได้ และหยุดพร้อมบอกสิ่งที่ต้องทำเมื่อเจอ stage ที่ต้องใช้ browser/manual
4. ประมาณการ token ต่อเรื่อง 5 ฉาก: ≤ 150K เมื่อใช้ Flow-playbook, ≤ 50K เมื่อใช้ API (เทียบ 7.8M ใน Cowork)

## 2. สิ่งที่ Cowork ทำจริง (วิเคราะห์จาก asset)

| Stage | Cowork ทำอย่างไร | Output | ปัญหา |
|---|---|---|---|
| Story + bible | LLM เขียน `01-story/storyboard.md` | 5 ฉาก, 9:16, palette, STYLE/CHARACTER block | ดี — เก็บรูปแบบนี้ไว้ |
| Prompts | LLM เขียน `04-prompts/image-prompts.md`, `flow-motion-prompts.md` | STYLE+CHARACTER block ใช้ซ้ำทุกฉาก + suffix กัน morphing | ดี — ย้ายเป็น field ใน manifest |
| Reference + 5 scene images | ChatGPT ผ่าน in-app browser (screenshot-driven) | PNG 941x1672 | **0.99M tokens (13%)** |
| Contact sheet | PIL/ffmpeg ต่อภาพ | `03-images/contact-sheet.jpg` | ok |
| 5 clips | Google Flow (Veo 3.1 Lite 720p 8s, image-to-video) ผ่าน Claude in Chrome + Windows save dialog | MP4 720x1280 24fps 8s มีเสียง Veo | **0.64M + 0.40M tokens (13%)**, 50 credits |
| Frame QC | ffmpeg ดึง 3 เฟรม/คลิป | `06-draft/frames/*.jpg` | ok แต่ LLM ดูหลายภาพ |
| Draft | ffmpeg xfade 0.5 s, fade out 1 s | `06-draft/...-draft-v1.mp4` 38 s | ทำทีละคำสั่งผ่าน LLM |
| VO | edge-tts `th-TH-PremwadeeNeural` 5 บรรทัด, วางที่ 0.6/8.0/15.6/23.2/31.0 s | `07-audio/vo/vo-0N.mp3` | ok |
| Music | `make_music.py` (numpy/scipy synth 5 section ตามฉาก) | `music-moonpetal.wav` 38 s | hard-code เวลา — ต้อง parametrize |
| Mix/final | ambient 28 %, music duck ใต้ VO, loudnorm → -14.8 LUFS / -1.4 dBTP | `08-final/...-final.mp4` | ok |
| Status | LLM เขียน `status.md` | ตาราง QC | ควร generate |

**Token ใช้ไป ~7.8M**: 46 % = instruction re-read ทุก turn, 24 % = chat/thinking, 26 % = browser/ChatGPT/Flow/Windows dialog, **3 % = งาน ffmpeg/ไฟล์/เสียงจริง**

แนวแก้:
- instruction overhead → Claude Code มี prompt cache; ใช้ `CLAUDE.md` โปรเจคสั้น + skill โหลดเฉพาะตอนใช้
- browser → API adapter (ไม่มี screenshot เลย) หรือ Flow playbook แบบ text-only (`find`/`form_input`/`browser_batch`) + `ani collect` ย้ายไฟล์จาก Downloads แทน save dialog
- ffmpeg/audio ad hoc → สคริปต์เดียว รันครั้งเดียว ไม่มี LLM ในลูป

## 3. สถาปัตยกรรม

### 3.1 Layout

```
ANI/
  CLAUDE.md                          # กติกาสั้นสำหรับ Claude Code ในโปรเจคนี้
  .gitignore                         # media/.env
  .env                               # API keys (optional, ไม่ commit)
  .claude/settings.json              # permissions allow: python tools/ani.py, ffmpeg, ffprobe
  .claude/skills/ani-pipeline/SKILL.md   # workflow skill (project-scoped)
  docs/superpowers/{specs,plans}/    # เอกสารนี้ + plan
  tools/
    ani.py        # CLI, manifest, timeline, story render, status, run, mark, collect dispatch
    media.py      # ffmpeg/PIL: contact, frames, assemble, mix, subs
    gen.py        # image/video providers + collect
    audio.py      # tts providers + music synth
    test_ani.py   # stdlib unittest — ไม่ต้องใช้ ffmpeg/network
  moonpetal-guardian/                # โปรเจคแรก (asset เดิม + project.json ใหม่)
  <slug>/                            # โปรเจคต่อ ๆ ไป (ani new สร้าง)
    project.json
    01-story/ 02-reference/ 03-images/ 04-prompts/ 05-clips/ 06-draft/ 07-audio/ 08-final/
    status.md
```

Dependencies: Python 3.12 stdlib + numpy/scipy/PIL/edge-tts (มีอยู่แล้ว) + ffmpeg/ffprobe บน PATH. **ไม่เพิ่ม dependency ใหม่** (REST ใช้ `urllib`).

### 3.2 CLI

```
python tools/ani.py <cmd> [--project DIR] [--scene ID ...] [--force] [--dry-run]
```
`--project` default = cwd ถ้ามี `project.json` ไม่งั้น error ชัด ๆ

| cmd | ทำอะไร | Input → Output | LLM ต้องทำ |
|---|---|---|---|
| `new <slug>` | สร้างโฟลเดอร์ 01–08 + `project.json` template | — | เขียน project.json |
| `validate` | ตรวจ manifest (schema, mood, voice, prompt ว่าง) | project.json | — |
| `story` | render `01-story/storyboard.md` + `04-prompts/prompts.md` จาก manifest | project.json | — |
| `images` | สร้าง reference + ภาพฉากผ่าน provider | prompts → `02-reference/reference.png`, `03-images/scene-{id}.png` | manual: วางไฟล์ |
| `contact` | contact sheet | ภาพฉาก → `03-images/contact-sheet.jpg` | ดู 1 ภาพ, `mark` |
| `clips` | image-to-video ผ่าน provider | ภาพ+motion → `05-clips/scene-{id}.mp4` | flow: playbook |
| `collect images\|clips` | ย้ายไฟล์จาก Downloads เข้าฉากที่ยังขาด (dry-run ก่อน) | ~/Downloads → 03/05 | ยืนยัน mapping |
| `frames` | 3 เฟรม/คลิป + grid รวม | clips → `06-draft/frames/`, `frames-grid.jpg` | ดู 1 ภาพ, `mark` |
| `assemble` | xfade + fade-out + normalize ขนาด/fps | clips → `06-draft/draft.mp4` | — |
| `vo` | TTS ทุกบรรทัด | manifest → `07-audio/vo/{id}-{n}.mp3` | — |
| `music` | synth ตาม mood/timeline หรือใช้ไฟล์ | manifest → `07-audio/music.wav` | — |
| `mix` | ambient + music(duck) + VO → loudness → mux | draft+audio → `08-final/final.mp4` | — |
| `subs` | srt จาก VO (+ `--burn` → `08-final/final-subs.mp4`) | manifest+vo → `07-audio/subs.srt` | — |
| `status` | render `status.md` จาก qc + ไฟล์ที่มี | — | รายงาน user |
| `mark <id> image=pass\|redo clip=pass\|redo note="..."` | บันทึก QC ลง manifest | — | — |
| `run [--from S] [--to S]` | รันทุก stage ตามลำดับ หยุดเมื่อต้อง manual | — | — |

ลำดับ `run`: validate → story → images → contact → clips → frames → assemble → vo → music → mix → subs(ถ้า enabled) → status

### 3.3 Manifest `project.json` (source of truth)

```json
{
  "slug": "moonpetal-guardian",
  "title": "ผู้พิทักษ์กลีบจันทรา (Moonpetal Guardian)",
  "video": { "width": 720, "height": 1280, "fps": 24, "aspect": "9:16", "resolution": "720p" },
  "style": "Japanese fantasy anime / manga key-visual style, ... no text, no watermark.",
  "characters": "RIN: ... KOGI: ...",
  "motion_suffix": "Keep the exact character design, art style, colors and composition of the source image. Japanese anime style, smooth natural motion, no morphing, no text.",
  "reference": { "prompt": "Character reference sheet of RIN and KOGI ...", "file": "02-reference/character-sheet-rin-kogi.png" },
  "providers": { "image": "manual", "video": "flow", "tts": "edge", "music": "synth" },
  "provider_config": {
    "gemini": { "image_model": "gemini-2.5-flash-image", "video_model": "veo-3.1-fast-generate-preview" },
    "openai": { "image_model": "gpt-image-1", "quality": "high" },
    "fal": { "image_model": "fal-ai/nano-banana-pro/edit", "video_model": "fal-ai/veo3.1/fast/image-to-video", "image_params": {}, "video_params": {} },
    "elevenlabs": { "model": "eleven_multilingual_v2" },
    "flow": { "model": "Veo 3.1 - Fast", "downloads": "~/Downloads" }
  },
  "voices": { "narrator": "th-TH-PremwadeeNeural", "rin": "th-TH-PremwadeeNeural" },
  "tts": { "rate": "+0%", "pitch": "+0Hz" },
  "music": { "file": null, "seed": 7, "gain": 0.5 },
  "edit": { "xfade": 0.5, "fade_out": 1.0, "clip_audio": 0.28, "vo_gain": 1.0, "duck_ratio": 4, "duck_threshold": 0.1, "lufs": -14, "true_peak": -1.5, "crf": 18 },
  "subs": { "enabled": false, "font": "Leelawadee UI", "size": 56, "margin_v": 220 },
  "scenes": [
    {
      "id": "01", "seconds": 8, "mood": "calm",
      "title": "เปิดโลก",
      "image_prompt": "Wide shot: Rin stands at the grassy cliff edge ...",
      "motion_prompt": "Slow cinematic push-in toward Rin. ...",
      "vo": [ { "speaker": "narrator", "text": "ณ หมู่เกาะลอยฟ้าแห่งเอลอเรีย...", "offset": 0.6 } ],
      "qc": { "image": "", "clip": "", "note": "" }
    }
  ]
}
```

กติกา:
- prompt ภาพที่ส่ง provider = `image_prompt + "\n" + style + "\n" + characters`; prompt motion = `motion_prompt + " " + motion_suffix`
- `mood` ∈ `calm | threat | resolve | climax | resolution` (music synth) — ค่าอื่น → fallback `calm` + warning
- `vo[].offset` = วินาทีนับจากจุดเริ่มฉากใน timeline (ไม่ใช่เวลาสัมบูรณ์) → ย้ายฉาก/เปลี่ยน xfade แล้ว VO ยังถูก
- `qc.image/clip` ∈ `"" | pass | redo`; `redo` ทำให้ stage images/clips สร้างฉากนั้นใหม่แม้มีไฟล์
- ไฟล์ input หาแบบ glob: `03-images/scene-{id}*.{png,jpg,jpeg,webp}`, `05-clips/scene-{id}*.mp4` → asset เดิมชื่อ `scene-01-image.png` ใช้ได้ไม่ต้อง rename; provider เขียนชื่อ `scene-{id}.png|.mp4`

### 3.4 Timeline (ใช้ร่วมทุก stage)

- `n` ฉาก, xfade `x`: `start_i = Σ_{j<i} seconds_j − i·x`, `total = Σ seconds − (n−1)·x`
- moonpetal: 5×8 − 4×0.5 = **38.0 s**, start = 0 / 7.5 / 15 / 22.5 / 30 ✔ ตรง `edit-plan.md`
- VO absolute = `start_i + offset` → 0.6 / 8.0 / 15.6 / 23.2 / 31.0 ✔ ตรง `status.md`
- Music sections = `[(mood_i, start_i, start_{i+1} หรือ total)]` → A 0–7.5 calm … E 30–38 resolution ✔ ตรง docstring ของ `make_music.py`

### 3.5 Provider matrix

| ชนิด | provider | ใช้ได้เมื่อ | วิธี | ทดสอบใน sprint นี้ |
|---|---|---|---|---|
| image | `manual` | เสมอ | พิมพ์ prompt ทุกฉากที่ยังขาด + รอไฟล์; ใช้กับ ChatGPT/Gemini web หรือ Claude in Chrome | ✅ |
| image | `gemini` | `GEMINI_API_KEY` | `generateContent` model `gemini-2.5-flash-image`, reference เป็น inline_data, `imageConfig.aspectRatio` | ⛔ (ไม่มี key) |
| image | `openai` | `OPENAI_API_KEY` | `/v1/images/generations` (`gpt-image-1`, size `1024x1536`) ; มี reference → `/v1/images/edits` multipart | ⛔ |
| image | `fal` | `FAL_KEY` | queue API `POST https://queue.fal.run/{model}` → poll → download; image input เป็น data URI | ⛔ |
| video / image | `flow` (**default**) | Chrome แยกของ Flow (`~/.ani/chrome-flow`, พอร์ต 9333) login ครั้งเดียว | `tools/flow.py` (Playwright `connect_over_cdp`) — ดู §12 และ `flow-playbook.md` | ✅ ภาพครบวงจร, คลิปถึงก่อนกดสร้าง (เครดิตหมด) |
| video | `manual` | เสมอ | พิมพ์ motion prompt + ชื่อภาพ + รอไฟล์ | ✅ |
| video | `gemini` | `GEMINI_API_KEY` (paid) | `veo-3.1-fast-generate-preview:predictLongRunning` image+prompt, 9:16, 720p, 8 s → poll operation → download uri | ⛔ |
| video | `fal` | `FAL_KEY` | queue API, `image_url` data URI, `aspect_ratio: 9:16`, `duration: "8s"` | ⛔ |
| tts | `edge` | เสมอ (ต้องมีเน็ต) | `edge_tts.Communicate(text, voice, rate, pitch).save()` | ✅ |
| tts | `elevenlabs` | `ELEVENLABS_API_KEY` | `POST /v1/text-to-speech/{voice_id}` ; `voices` map speaker→voice_id | ⛔ |
| tts | `file` | เสมอ | ใช้ไฟล์ที่วางไว้แล้ว (`07-audio/vo/{id}-{n}.mp3`) | ✅ |
| music | `synth` | เสมอ | port `make_music.py` เป็น mood sections parametrized | ✅ |
| music | `file` | เสมอ | `music.file` ชี้ไฟล์ wav/mp3 (Suno/Udio/ของเอง) | ✅ |

Key อ่านจาก env หรือ `ANI/.env` (`KEY=VALUE`, stdlib parser, ไม่ commit)

### 3.6 Claude Code integration

- `ANI/CLAUDE.md` (≤ 40 บรรทัด): pipeline คืออะไร, `python tools/ani.py --help`, กติกา: source of truth = `project.json`; ห้ามเขียน ffmpeg เอง; ดูภาพ QC ผ่าน `contact-sheet.jpg` / `frames-grid.jpg` เท่านั้น (ห้ามเปิดวิดีโอ/เฟรมทีละไฟล์); ก่อนใช้เครดิต Flow ต้อง list ฉากที่จะ gen ให้ user ก่อน
- `ANI/.claude/skills/ani-pipeline/SKILL.md`: workflow เต็ม, คู่มือเขียน manifest (STYLE/CHARACTER block, motion suffix, VO ≤ 14 คำ/บรรทัด, offset), QC protocol, **Flow playbook** (token rules: ใช้ `find`/`read_page`/`form_input`/`browser_batch`; screenshot ได้ไม่เกิน 1 ครั้งต่อคลิปเฉพาะเมื่อ `find` ไม่เจอ; ปิด "Ask where to save" ใน Chrome → ไม่มี Windows dialog; จบด้วย `ani collect clips`), รูปแบบรายงาน
- `ANI/.claude/settings.json`: allow `Bash(python tools/ani.py:*)`, `Bash(python tools/test_ani.py:*)`, `Bash(ffmpeg:*)`, `Bash(ffprobe:*)` → ไม่มี permission prompt ระหว่าง run

## 4. Module contracts (สำหรับ implement ขนาน)

ทุก module: `from __future__ import annotations`, `pathlib.Path`, ไม่มี global state นอกจาก registry dict; log ด้วย `print(f"[stage] ...")`; error → `raise SystemExit("ani: <สาเหตุ> — <วิธีแก้>")`

```python
# ani.py
def load_project(project_dir: Path) -> dict            # อ่าน+validate เบื้องต้น, เติม default
def save_project(project_dir: Path, project: dict) -> None   # indent=2, ensure_ascii=False, atomic
def timeline(project: dict) -> list[dict]              # [{id, start, end, seconds}], end = start+seconds
def total_seconds(project: dict) -> float
def vo_events(project: dict) -> list[dict]             # [{scene, n, speaker, text, at, file:"07-audio/vo/{id}-{n}.mp3"}] เรียงตาม at
def music_sections(project: dict) -> list[tuple[str, float, float]]   # [(mood, t0, t1)]
def find_asset(project_dir: Path, kind: "image"|"clip", scene_id: str) -> Path | None   # glob rule §3.3
def scene_needs(project: dict, scene: dict, kind) -> bool   # ไม่มีไฟล์ หรือ qc == "redo" หรือ --force
def load_env(root: Path) -> None                       # ANI/.env → os.environ.setdefault
def main(argv) -> int                                  # argparse dispatch; sys.stdout.reconfigure(encoding="utf-8")

# media.py  (ทุกฟังก์ชันรับ project_dir, project; รัน ffmpeg ด้วย subprocess list-args, cwd=project_dir, path ใน filter เป็น relative)
def contact_sheet(project_dir, project) -> Path        # 03-images/contact-sheet.jpg (PIL, สูง 800px, label id)
def frames(project_dir, project, scenes=None) -> Path  # 06-draft/frames/s{id}_t{1,2,3}.jpg + frames-grid.jpg (rows=scene, cols=3, label)
def assemble(project_dir, project) -> Path             # 06-draft/draft.mp4
def build_xfade_graph(clips: list[dict], w, h, fps, xfade, fade_out) -> tuple[str, str, str]  # pure: (filter_complex, vmap, amap) — unit-test ได้
def mix(project_dir, project) -> Path                  # 08-final/final.mp4 (2-pass loudness §5.5)
def write_srt(project_dir, project) -> Path            # 07-audio/subs.srt
def srt_text(events: list[dict]) -> str                # pure — unit-test ได้
def burn_subs(project_dir, project) -> Path            # 08-final/final-subs.mp4
def probe_duration(path: Path) -> float
def has_audio(path: Path) -> bool

# gen.py
ImageFn = Callable[[str, list[Path], Path, dict], Path]   # (prompt, reference_images, out_path, cfg) -> out_path
VideoFn = Callable[[str, Path, Path, dict], Path]         # (prompt, source_image, out_path, cfg) -> out_path
IMAGE_PROVIDERS: dict[str, ImageFn]   # manual, gemini, openai, fal
VIDEO_PROVIDERS: dict[str, VideoFn]   # manual, flow, gemini, fal   (manual/flow = พิมพ์คำสั่ง+return None ถ้ายังไม่มีไฟล์)
def generate_images(project_dir, project, scenes: list[str] | None, force: bool) -> list[Path]   # reference ก่อน แล้วฉาก; API providers รันขนาน ThreadPoolExecutor(4)
def generate_clips(project_dir, project, scenes, force) -> list[Path]
def collect(project_dir, project, kind: "images"|"clips", src_dir: Path, hours: float, mapping: dict[str,Path] | None, apply: bool) -> list[tuple[str, Path, Path]]  # (scene_id, src, dst); dry-run ถ้า apply=False
def plan_collect(missing_ids: list[str], candidates: list[Path]) -> dict[str, Path]   # pure: จับคู่ตาม mtime asc — unit-test ได้
def http_json(url, method, headers, body: dict | None, timeout) -> dict   # urllib; error → SystemExit พร้อม status+body ตัดสั้น
def download(url, out: Path, headers) -> Path

# audio.py
TtsFn = Callable[[str, str, Path, dict], Path]    # (text, voice, out_path, cfg) -> out_path
TTS_PROVIDERS: dict[str, TtsFn]   # edge, elevenlabs, file
def tts(project_dir, project, force: bool) -> list[Path]          # ทุก vo event → 07-audio/vo/{id}-{n}.mp3 (ข้ามที่มีแล้ว)
def music(project_dir, project, force: bool) -> Path              # 07-audio/music.wav (synth หรือ copy/convert จาก music.file)
def synth_music(sections: list[tuple[str, float, float]], total: float, out: Path, seed: int = 7, sr: int = 44100) -> Path
```

`synth_music` ต้องให้ผลใกล้ `make_music.py` เดิมเมื่อ sections = moonpetal (5 mood, 38 s): เสียงเดียวกันต่อ mood, เวลาภายใน section เป็น relative จาก `t0`, จำนวน loop (bells/heartbeat/pulse/arp) คิดจากความยาว section, reverb + fade 2.5 s + normalize peak 0.89 เหมือนเดิม; section ต่อกันได้ทุกจำนวน/ทุกความยาว ≥ 2 s

## 5. Stage specs

### 5.1 `images` / `clips`
- ลูปฉากที่ `scene_needs()`; API provider ทำขนานสูงสุด 4; manual/flow พิมพ์ block ต่อฉาก:
  ```
  === scene 03 (image) ===
  <prompt>
  → save as: 03-images/scene-03.png
  ```
  แล้วจบด้วยสรุป "ขาด N ฉาก — วางไฟล์แล้วรัน `ani collect images` หรือรันซ้ำ"
- clips: ถ้าไม่มีภาพฉาก → error ชี้ให้ทำ `images` ก่อน
- หลังสำเร็จ: ล้าง `qc.<kind>` จาก `redo` เป็น `""`

### 5.2 `collect`
- candidates = ไฟล์นามสกุลตรง kind (images: png/jpg/jpeg/webp, clips: mp4/mov/webm) ใน `src_dir` ที่ mtime ภายใน `--hours` (default 6), เรียง mtime เก่า→ใหม่
- missing = ฉากที่ยังไม่มี asset เรียงตาม id; `plan_collect` จับคู่ทีละตัว (ถ้า candidates น้อยกว่า → เท่าที่มี)
- `--map 03=path` override; default dry-run พิมพ์ตาราง `scene ← file (size, mtime)`; `--yes` ย้าย (`shutil.move`) เป็น `scene-{id}.<ext>`
- เขียน `.collect.log` ต่อท้ายใน project dir (เวลา, src→dst) เผื่อย้อนรอย

### 5.3 `contact` / `frames`
- contact: โหลดภาพฉากทั้งหมด (ข้ามที่ขาด), resize สูง 800, ต่อแนวนอน gap 12 px bg #101018, label `01`… ซ้ายบน (`ImageDraw`, default font) → JPEG q 85
- frames: ต่อคลิป `ffmpeg -ss t -i clip -frames:v 1 -vf scale=360:-2` ที่ t = 1, seconds/2, seconds−1 → `s{id}_t{k}.jpg`; grid = rows ฉาก × 3 คอลัมน์ + label → `frames-grid.jpg` (ภาพเดียวให้ LLM ดู)

### 5.4 `assemble`
- ต่อคลิป: probe `has_audio`; ถ้าไม่มีเสียง เพิ่ม input `-f lavfi -t seconds -i anullsrc=r=48000:cl=stereo`
- per-clip filter: `[i:v]scale=W:H:force_original_aspect_ratio=increase,crop=W:H,fps=FPS,setsar=1,trim=0:S,setpts=PTS-STARTPTS[v_i]` และ `[a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:S,asetpts=PTS-STARTPTS[a_i]`
- chain: `[v0][v1]xfade=transition=fade:duration=X:offset=O1[x1]`, `[x1][v2]xfade=...:offset=O2[x2]` … `O_k = Σ_{j<k} S_j − k·X`; audio `acrossfade=d=X` ต่อกัน
- ท้าย: `fade=t=out:st=total−F:d=F` + `afade=t=out:st=total−F:d=F`
- encode: `libx264 -crf {crf} -preset medium -pix_fmt yuv420p`, `aac 192k`, `-movflags +faststart`, `-t total`
- 1 คลิป: ไม่มี xfade แค่ normalize + fade
- `build_xfade_graph` เป็น pure function คืน string → test เทียบ offset 7.5/15/22.5/30

### 5.5 `mix` (2-pass, linear gain)
- pass 1 → `08-final/_mix.wav` (pcm 48k):
  ```
  [0:a]volume={clip_audio}[amb];
  [k:a]adelay={ms}|{ms}[v_k] …; [v_*]amix=inputs=N:normalize=0,volume={vo_gain},apad=whole_dur={total}[vo]; [vo]asplit=2[vo_sc][vo_out];
  [1:a]volume={music.gain}[mus]; [mus][vo_sc]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}:attack=20:release=400[musd];  (≈ -10 dB ใต้เสียงพากย์)
  [amb][musd][vo_out]amix=inputs=3:normalize=0:dropout_transition=0[out]
  ```
  (ไม่มี VO → ข้าม sidechain; ไม่มี music → ข้าม; ไม่มี ambient (draft ไร้เสียง) → anullsrc)
- measure: `ffmpeg -i _mix.wav -af loudnorm=I={lufs}:TP={tp}:print_format=json -f null -` → parse `input_i`, `input_tp`
- gain = lufs − input_i (linear); peak ที่เกินให้ `alimiter` จัดการ; ถ้า input_tp + gain > tp + 6 dB พิมพ์ warning ว่า limiter ทำงานหนัก
- pass 2: `-i draft.mp4 -i _mix.wav -map 0:v -map 1:a -c:v copy -af volume={gain}dB,alimiter=limit={10^(tp/20)}:attack=5:release=50 -c:a aac -b:a 192k -ar 48000 -shortest -movflags +faststart 08-final/final.mp4`
- ลบ `_mix.wav`; พิมพ์ loudness สุดท้ายจากการวัดซ้ำ (ebur128) ให้เห็นตัวเลข

### 5.6 `vo` / `music`
- vo: ข้ามไฟล์ที่มี (เว้น `--force`); edge: `asyncio.run(Communicate(text, voice, rate=..., pitch=...).save(path))` ห่อด้วย `_retry` (4 ครั้ง backoff 2/4/6 s — edge-tts คืน `NoAudioReceived` สุ่มกับข้อความใหม่); ผิดพลาดต่อบรรทัดไม่หยุดทั้งหมด — สรุปตอนจบว่าบรรทัดไหนพลาด
- music: `providers.music == "file"` หรือ `music.file` ตั้งค่า → ffmpeg convert เป็น wav 44.1k stereo ตัด/pad ให้ยาว `total`; ไม่งั้น `synth_music(music_sections(project), total, out, seed)`

### 5.7 `subs`
- event end = `at + probe_duration(vo file)` ถ้ามี ไม่งั้น `at + max(2.0, len(text)/12)`; ไม่ทับกัน (end_k ≤ at_{k+1} − 0.1)
- burn: `-vf subtitles=07-audio/subs.srt:force_style='FontName={font},FontSize={size·288/H},Outline=2,Shadow=0,MarginV={margin_v·288/H},Alignment=2'` (cwd = project dir → ไม่ต้อง escape drive letter); `subs.size`/`margin_v` ระบุเป็น px ของวิดีโอ แล้วสเกลเป็นหน่วย script 384x288 ของ libass (ไม่งั้น MarginV=200 = 69% ของจอ)

### 5.8 `status`
- render ตารางเหมือน `status.md` เดิม: ฉาก | ภาพ(มี/ไม่มี + qc) | คลิป(มี/ไม่มี + qc + duration จาก probe) | note; ส่วนท้าย: draft/final มีไหม ขนาด/ความยาว, VO/music มีไหม, provider ที่ใช้, "ทำต่อได้"
- `mark` แก้ `scenes[].qc` แล้ว `status` อัตโนมัติ

## 6. Error handling
- ไม่มี ffmpeg/ffprobe → SystemExit บอกวิธีติดตั้ง (winget)
- provider ต้องการ key แต่ไม่มี → SystemExit ชี้ชื่อ env + ไฟล์ `.env`
- HTTP ≠ 2xx → SystemExit แสดง status + body 300 ตัวอักษรแรก; API poll timeout: gemini video 10 นาที, fal image 5 นาที / video 15 นาที (คิวยาวได้)
- งานขนาน (API providers): งานที่สำเร็จถูกบันทึก (retire/qc/save) ก่อนเสมอ แล้วค่อย SystemExit รวมรายการที่พลาด → รันซ้ำทำเฉพาะที่ขาด ไม่จ่ายซ้ำ
- ffmpeg fail → แสดง stderr 40 บรรทัดท้าย + คำสั่งเต็มที่รัน
- output เขียนลง temp ชื่อ `.<name>.tmp` แล้ว rename → ไม่มีไฟล์ครึ่ง ๆ
- ทุกอย่างพิมพ์ UTF-8 (Thai) ได้บน Windows console

## 7. Testing
- `tools/test_ani.py` (unittest, ไม่แตะ ffmpeg/network):
  1. timeline moonpetal → total 38, starts [0,7.5,15,22.5,30]; 1 ฉาก → total = seconds; xfade 0 → ต่อกันตรง ๆ
  2. vo_events → at [0.6, 8.0, 15.6, 23.2, 31.0] และ file names
  3. music_sections → 5 ช่วงตรง docstring เดิม
  4. build_xfade_graph 3 คลิป 8 s x 0.5 → มี `offset=7.5` และ `offset=15`, fade st = 22.5−1
  5. srt_text → format `00:00:00,600 --> …`, ไม่ทับกัน
  6. plan_collect → จับคู่ตาม mtime, candidates น้อยกว่าฉาก
  7. load_project เติม default + reject mood ผิด (warning) + reject ฉากไม่มี id
- E2E (manual ใน plan): moonpetal `contact → frames → assemble → vo → music → mix → subs → status` แล้ว ffprobe/ebur128 ตรวจ criteria §1
- `synth_music` self-check: รันกับ sections moonpetal → 38 s, peak 0.89±0.01, ไม่มี NaN; และ 2 section 6 s

## 8. Data flow (สรุป)

```
Claude เขียน project.json ──ani story──▶ storyboard.md / prompts.md (คนอ่าน)
        │
   ani images (provider) ──▶ 02-reference/*.png, 03-images/scene-XX.png ──ani contact──▶ contact-sheet.jpg ──Claude ดู──▶ ani mark
        │
   ani clips (provider/flow playbook + collect) ──▶ 05-clips/scene-XX.mp4 ──ani frames──▶ frames-grid.jpg ──Claude ดู──▶ ani mark
        │
   ani assemble ──▶ 06-draft/draft.mp4
   ani vo ──▶ 07-audio/vo/XX-n.mp3 ; ani music ──▶ 07-audio/music.wav
        │
   ani mix ──▶ 08-final/final.mp4 ──ani subs --burn──▶ final-subs.mp4 ; ani status ──▶ status.md
```

## 9. Migration ของ moonpetal-guardian
- สร้าง `moonpetal-guardian/project.json` จาก storyboard/image-prompts/flow-motion-prompts/vo-script (ข้อมูลครบ, offset = at − start)
- `reference.file` ชี้ `02-reference/character-sheet-rin-kogi.png`; ภาพ/คลิปเดิมเข้า glob โดยไม่ rename
- output ใหม่ใช้ชื่อใหม่ (`draft.mp4`, `music.wav`, `vo/01-1.mp3`, `final.mp4`) → **ไม่ทับไฟล์เดิมของ user**; `contact-sheet.jpg` และ `frames/` เป็น derived artifact สร้างทับได้
- ไฟล์เดิม (`make_music.py`, `vo-script.tsv`, `*-draft-v1.mp4`, `*-final.mp4`) คงไว้ ไม่ลบ

## 10. Non-goals (รอบนี้)
- ~~scripted browser automation ของ Google Flow~~ → ทำแล้วใน §12 (2026-09-27)
- 1080p / upscale, Remotion overlay, lip-sync, SFX library, multi-language VO
- git init / commit (user ไม่ได้สั่ง — แนะนำใน plan)

## 11. Assumptions (แก้ได้ทีหลัง)
1. ยังไม่มี API key ใด ๆ ในเครื่อง → default providers = `image: manual`, `video: flow`, `tts: edge`, `music: synth`; adapter API เขียนไว้ครบแต่ทดสอบไม่ได้จนกว่าจะใส่ key ใน `ANI/.env`
2. Flow ยังเป็นแหล่งคลิปหลัก (เครดิตในแพ็กเกจ) → ลด token ด้วย playbook + collect แทนที่จะแทนด้วย API ทันที
3. โครงโฟลเดอร์ 01–08 ของเดิมดีอยู่แล้ว → ใช้ต่อ ไม่ย้ายไฟล์
4. ภาษาเอกสาร/สถานะ = ไทย, code/identifier = อังกฤษ
5. Windows + Git Bash/PowerShell; path ใน ffmpeg filter ใช้ relative จาก project dir
6. ไม่ทำ git repo ให้ (system rule: commit เมื่อสั่งเท่านั้น)

## 12. Flow automation — `tools/flow.py` (เพิ่ม 2026-09-27)
เหตุผล: รอบ crimson-blade ขั้น Flow ผ่าน Claude in Chrome ใช้ ~30 นาที + tool call หลายสิบครั้ง, Save As ค้าง, จับคู่คลิปด้วยชื่ออัตโนมัติ. วิจัย: `docs/research/2026-09-26-browser-agent-tools.md`
- **Engine:** Playwright Python `connect_over_cdp` (ติดตั้งแล้ว 1.59) — trusted input, locator ด้วย label ไทย, `expect_download()+save_as()` (spike: ไม่มี Save As แม้เปิด Ask where to save, ไม่รั่วหลัง disconnect)
- **Browser (โหมด B):** Chrome แยก `--user-data-dir=~/.ani/chrome-flow --remote-debugging-port=9333`, `flow.launch()` เปิดเองถ้ายังไม่รัน; user login ครั้งเดียว. ไม่ต่อ Chrome ประจำวัน (last-used profile ≠ profile ของ Flow → download/แท็บใหม่ผิดโปรไฟล์; โหมด chrome://inspect ต้องกด Allow ทุกการต่อ) — โหมด A = ทางสำรองที่ยังไม่ implement
- **Providers:** `image: flow` (Nano Banana 2; reference ขึ้นก่อน แล้วแนบเป็น ingredient ทุกฉาก) · `video: flow` (Start frame = tile ภาพของฉากใน Flow) — ทีละงาน, โหลดตรง `03-images/scene-XX.jpg` / `05-clips/scene-XX.mp4`, ไม่ upload (upload มีกล่องยืนยันสิทธิ์ที่ต้องให้ user กดเอง)
- **Identity:** tile ที่เสร็จถูกตั้งชื่อ `scene-XX <kind> <mmdd-HHMMSS>` (ช่องชื่อแก้ได้ใน detail view) → ใช้ค้นใน picker และหาเพื่อโหลดข้าม session; ภาพยืนยันซ้ำด้วย `img[data-media-id]`
- **State:** `scene.flow.{image|clip} = {status, at, media, credits, file}` — `unknown` ก่อนคลิก Generate, `submitted` หลัง Flow รับงาน (และอีกครั้งพร้อม `media` เมื่อเสร็จ), `downloaded` หลังเซฟ; rerun: pending+media → โหลดต่อ, pending ไม่มี media → หยุด (`--force --scene XX` ข้ามเฉพาะฉากนั้น); take เก่า → `_old/` ก่อนเซฟตัวใหม่
- **Credit gate:** ราคาอ่านจาก popover ทุกงาน; ≠ 0 หรืออ่านไม่ได้ → ต้อง `--yes` (กติกาข้อ 4); เครดิตไม่พอ → หยุดก่อนแตะ state
- **Tests:** `make()` ด้วย FakeFlowPage (ลำดับ state, gate, resume, unknown, นามสกุลไฟล์จริง) + wiring ของ images/clips; ส่วน DOM ยืนยันด้วยรันจริง (ภาพ 3 งาน, คลิปถึงก่อน submit)

