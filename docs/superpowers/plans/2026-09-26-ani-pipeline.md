# ANI Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CLI `python tools/ani.py <stage>` ที่ทำทุก stage ของหนังสั้น AI (images → clips → assemble → vo → music → mix → subs → status) จาก `project.json` โดย LLM ทำแค่เขียน manifest + ดูภาพ QC

**Architecture:** 4 Python modules ใน `tools/` (ani = manifest/timeline/CLI, media = ffmpeg/PIL, gen = image/video providers + collect, audio = tts/music) + project-scoped skill/CLAUDE.md/permissions ให้ Claude Code ขับ; ทุก stage idempotent ตาม glob ของไฟล์ + `qc.redo`

**Tech Stack:** Python 3.12 stdlib (`argparse`, `json`, `subprocess`, `urllib`), numpy/scipy (synth), Pillow (grids), edge-tts (VO), ffmpeg 8 + libass (บน PATH). ไม่เพิ่ม dependency

**Spec:** `docs/superpowers/specs/2026-09-26-ani-pipeline-design.md`

## Global Constraints

- ไม่เพิ่ม dependency; REST ผ่าน `urllib.request` เท่านั้น
- ทุกไฟล์ < 500 บรรทัด; ฟังก์ชัน < 50 บรรทัด (ยกเว้น synth section ที่เป็นข้อมูลโน้ต)
- ffmpeg รันด้วย `subprocess.run(list, cwd=project_dir)` path ใน filter เป็น relative; ไม่ใช้ shell
- output เขียน `.<name>.tmp` แล้ว `replace()`; ห้ามทับไฟล์เดิมของ user (`*-draft-v1.mp4`, `*-final.mp4`, `music-moonpetal.wav`, `vo/vo-0N.mp3`)
- ชื่อ output คงที่: `03-images/scene-{id}.png`, `05-clips/scene-{id}.mp4`, `06-draft/draft.mp4`, `07-audio/vo/{id}-{n}.mp3`, `07-audio/music.wav`, `08-final/final.mp4`
- Thai ใน console ต้องไม่ crash: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
- error = `SystemExit("ani: <สาเหตุ> — <วิธีแก้>")`

## Review Focus

1. คลิปสั้นกว่า `seconds` ใน manifest (เช่น Flow ให้ 7.9 s) → xfade offset เกิน → ffmpeg fail; ต้องใช้ `min(seconds, probe)` + warning (test ใน Task 2: `build_xfade_graph` รับ seconds ที่ถูก clamp แล้ว; `assemble` clamp)
2. คลิปไม่มี audio stream (Kling/manual) → acrossfade fail; ต้องเติม `anullsrc` (Task 2 test: `a_in` ชี้ input อื่นได้)
3. ชื่อไฟล์เก่า `scene-01-image.png` กับใหม่ `scene-01.png` อยู่พร้อมกันหลัง redo → glob เลือกผิด; ต้อง `retire_asset` ก่อนเขียน (Task 1 test)
4. VO บรรทัดหนึ่ง TTS ล้มเหลว (เน็ตหลุด) → ต้องทำบรรทัดอื่นต่อและสรุปตอนจบ ไม่ทิ้งไฟล์ครึ่ง ๆ (Task 3: เขียน tmp แล้ว rename)
5. `collect` เจอไฟล์ใน Downloads น้อยกว่าฉากที่ขาด หรือ mtime เก่าเกิน → จับคู่เท่าที่มี + dry-run ก่อนเสมอ (Task 4 test `plan_collect`)

---

## File Structure

| ไฟล์ | หน้าที่ |
|---|---|
| `tools/ani.py` | DEFAULTS, load/save/validate manifest, timeline/vo_events/music_sections, find_asset/retire_asset/scene_needs, prompt compose, story/status render, CLI + run |
| `tools/media.py` | ffmpeg/ffprobe wrappers, contact_sheet, frames, build_xfade_graph + assemble, mix (2-pass), srt_text/write_srt/burn_subs |
| `tools/gen.py` | http helpers, IMAGE_PROVIDERS/VIDEO_PROVIDERS, generate_images/clips, plan_collect/collect |
| `tools/audio.py` | TTS_PROVIDERS, tts(), music(), `_Synth` + synth_music |
| `tools/test_ani.py` | unittest ทั้งหมด (`python tools/test_ani.py`) |
| `CLAUDE.md`, `.claude/skills/ani-pipeline/SKILL.md`, `.claude/settings.json`, `.gitignore` | Claude Code integration |
| `moonpetal-guardian/project.json` | migration ของโปรเจคเดิม |

---

### Task 1: ani.py core (manifest, timeline, assets)

**Files:**
- Create: `tools/ani.py`, `tools/test_ani.py`, `.gitignore`, `.claude/settings.json`

**Interfaces:**
- Produces: `load_project(dir)->dict`, `save_project(dir, project)`, `timeline(project)->list[dict]`, `total_seconds`, `vo_events`, `music_sections`, `find_asset(dir, kind, id)`, `retire_asset(dir, kind, id)`, `scene_needs(dir, scene, kind, force)`, `reference_path(dir, project)`, `image_prompt(project, scene)`, `motion_prompt(project, scene)`, `load_env(root)`, constants `MOODS`, `IMAGE_EXT`, `CLIP_EXT`, `FOLDERS`, `STAGES`

- [ ] **Step 1: เขียน test ที่ fail**

```python
# tools/test_ani.py
import json, os, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ani

def moonpetal():
    return {
        "slug": "mp", "title": "t", "style": "S", "characters": "C",
        "voices": {"narrator": "th-TH-PremwadeeNeural", "rin": "th-TH-PremwadeeNeural"},
        "edit": {"xfade": 0.5, "fade_out": 1.0},
        "scenes": [
            {"id": "01", "seconds": 8, "mood": "calm", "image_prompt": "a", "motion_prompt": "m",
             "vo": [{"speaker": "narrator", "text": "one", "offset": 0.6}]},
            {"id": "02", "seconds": 8, "mood": "threat", "image_prompt": "a", "motion_prompt": "m",
             "vo": [{"speaker": "narrator", "text": "two", "offset": 0.5}]},
            {"id": "03", "seconds": 8, "mood": "resolve", "image_prompt": "a", "motion_prompt": "m",
             "vo": [{"speaker": "rin", "text": "three", "offset": 0.6}]},
            {"id": "04", "seconds": 8, "mood": "climax", "image_prompt": "a", "motion_prompt": "m",
             "vo": [{"speaker": "rin", "text": "four", "offset": 0.7}]},
            {"id": "05", "seconds": 8, "mood": "resolution", "image_prompt": "a", "motion_prompt": "m",
             "vo": [{"speaker": "narrator", "text": "five", "offset": 1.0}]},
        ],
    }

class TimelineTests(unittest.TestCase):
    def test_moonpetal_timeline(self):
        p = ani.apply_defaults(moonpetal())
        tl = ani.timeline(p)
        self.assertEqual([t["start"] for t in tl], [0, 7.5, 15, 22.5, 30])
        self.assertEqual(ani.total_seconds(p), 38)
    def test_single_scene_and_zero_xfade(self):
        p = ani.apply_defaults({**moonpetal(), "scenes": moonpetal()["scenes"][:1]})
        self.assertEqual(ani.total_seconds(p), 8)
        q = ani.apply_defaults({**moonpetal(), "edit": {"xfade": 0}})
        self.assertEqual([t["start"] for t in ani.timeline(q)], [0, 8, 16, 24, 32])
    def test_vo_events(self):
        ev = ani.vo_events(ani.apply_defaults(moonpetal()))
        self.assertEqual([e["at"] for e in ev], [0.6, 8.0, 15.6, 23.2, 31.0])
        self.assertEqual(ev[2]["file"], "07-audio/vo/03-1.mp3")
    def test_music_sections(self):
        self.assertEqual(ani.music_sections(ani.apply_defaults(moonpetal())),
                         [("calm", 0, 7.5), ("threat", 7.5, 15), ("resolve", 15, 22.5), ("climax", 22.5, 30), ("resolution", 30, 38)])

class ManifestTests(unittest.TestCase):
    def test_defaults_and_bad_mood(self):
        p = moonpetal(); p["scenes"][0]["mood"] = "weird"
        p = ani.apply_defaults(p)
        self.assertEqual(p["providers"]["image"], "manual")
        self.assertEqual(p["scenes"][0]["mood"], "calm")
        self.assertEqual(p["scenes"][0]["qc"], {"image": "", "clip": "", "note": ""})
    def test_missing_id_rejected(self):
        p = moonpetal(); del p["scenes"][1]["id"]
        with self.assertRaises(SystemExit): ani.apply_defaults(p)
    def test_find_retire_scene_needs(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / "03-images").mkdir()
            old = d / "03-images" / "scene-01-image.png"; old.write_bytes(b"x")
            self.assertEqual(ani.find_asset(d, "image", "01"), old)
            self.assertIsNone(ani.find_asset(d, "image", "02"))
            scene = {"id": "01", "qc": {"image": "redo"}}
            self.assertTrue(ani.scene_needs(d, scene, "image"))
            ani.retire_asset(d, "image", "01")
            self.assertIsNone(ani.find_asset(d, "image", "01"))
            self.assertEqual(len(list((d / "03-images" / "_old").iterdir())), 1)
    def test_prompts(self):
        p = ani.apply_defaults(moonpetal())
        self.assertEqual(ani.image_prompt(p, p["scenes"][0]), "a\nS\nC")
        self.assertTrue(ani.motion_prompt(p, p["scenes"][0]).startswith("m Keep the exact"))

if __name__ == "__main__":
    unittest.main(verbosity=1)
```

- [ ] **Step 2: รันให้ fail** — `python tools/test_ani.py` → `ModuleNotFoundError: ani`

- [ ] **Step 3: เขียน `tools/ani.py` (ส่วน core)** — ตาม spec §3.3–3.4 + §4:

```python
DEFAULTS = {...}  # ตาม spec §3.3 (video, motion_suffix, reference, providers, provider_config, voices, tts, music, edit, subs)
MOODS = ("calm", "threat", "resolve", "climax", "resolution")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp"); CLIP_EXT = (".mp4", ".mov", ".webm")

def deep_merge(base, over):   # dict recursive, list/scalar = override
def apply_defaults(data) -> dict:   # deep_merge(DEFAULTS, data) + validate() (SystemExit เมื่อไม่มี scenes / id ซ้ำ / seconds<=0; mood ผิด → "calm" + warning; เติม qc/vo)
def load_project(project_dir): return apply_defaults(json.loads((project_dir/"project.json").read_text("utf-8")))
def save_project(project_dir, project): tmp write ensure_ascii=False indent=2 → replace
def timeline(project):  # start_0=0; start_i = end_{i-1} - xfade
def total_seconds(project): return timeline(project)[-1]["end"]
def vo_events(project):  # {scene, n, speaker, text, at=start+offset, file="07-audio/vo/{id}-{n}.mp3"} เรียงตาม at
def music_sections(project): [(mood, start_i, start_{i+1}|total)]
def find_asset(project_dir, kind, scene_id): glob f"scene-{id}*" ใน 03-images/05-clips กรอง ext, sorted()[0]
def retire_asset(project_dir, kind, scene_id): ย้ายทุก match ไป <folder>/_old/<name>.<epoch><ext>
def scene_needs(project_dir, scene, kind, force=False): force or qc[kind]=="redo" or find_asset is None
def reference_path(project_dir, project): reference.file ถ้ามี ไม่งั้น glob 02-reference/reference.* หรือไฟล์ภาพแรกในโฟลเดอร์
def image_prompt(project, scene): "\n".join([scene image_prompt, style, characters])
def motion_prompt(project, scene): f"{motion_prompt} {motion_suffix}"
def load_env(root): parse KEY=VALUE → os.environ.setdefault
```

- [ ] **Step 4: รัน test ให้ผ่าน** — `python tools/test_ani.py` → OK (9 tests)

- [ ] **Step 5: `.gitignore` + `.claude/settings.json`**

```
# .gitignore
.env
*/02-reference/ */03-images/ */05-clips/ */06-draft/ */07-audio/ */08-final/
Claude outputs/
*.mp4 *.wav *.mp3 *.png *.jpg
!docs/**
```
```json
{ "permissions": { "allow": [
  "Bash(python tools/ani.py:*)", "Bash(python tools/test_ani.py:*)",
  "Bash(ffmpeg:*)", "Bash(ffprobe:*)" ] } }
```

---

### Task 2: media.py (pure graph builders → ffmpeg stages)

**Files:**
- Create: `tools/media.py`
- Modify: `tools/test_ani.py` (เพิ่ม MediaTests)

**Interfaces:**
- Consumes: `ani.find_asset`, `ani.timeline`, `ani.vo_events`, `ani.total_seconds`
- Produces: `build_xfade_graph(clips, w, h, fps, xfade, fade_out) -> (graph, vmap, amap, total)`, `srt_text(items)->str`, `fmt_ts(t)->str`, `contact_sheet`, `frames`, `assemble`, `mix`, `write_srt`, `burn_subs`, `probe_duration`, `has_audio`

- [ ] **Step 1: test ที่ fail**

```python
import media
class MediaTests(unittest.TestCase):
    def test_xfade_graph_offsets(self):
        clips = [{"seconds": 8.0, "v_in": 0, "a_in": 0}, {"seconds": 8.0, "v_in": 1, "a_in": 3}, {"seconds": 8.0, "v_in": 2, "a_in": 2}]
        g, vmap, amap, total = media.build_xfade_graph(clips, 720, 1280, 24, 0.5, 1.0)
        self.assertIn("xfade=transition=fade:duration=0.5:offset=7.5", g)
        self.assertIn("offset=15.0", g)
        self.assertIn("[3:a]aresample", g)          # audio จาก anullsrc input
        self.assertIn("fade=t=out:st=22.0:d=1.0", g)
        self.assertEqual((vmap, amap, total), ("[vout]", "[aout]", 23.0))
    def test_xfade_zero_uses_concat(self):
        g, *_ = media.build_xfade_graph([{"seconds": 8, "v_in": 0, "a_in": 0}, {"seconds": 8, "v_in": 1, "a_in": 1}], 720, 1280, 24, 0, 1.0)
        self.assertIn("concat=n=2:v=1:a=1", g)
    def test_srt(self):
        items = [{"at": 0.6, "end": 6.672, "text": "หนึ่ง"}, {"at": 8.0, "end": 12.4, "text": "สอง"}]
        s = media.srt_text(items)
        self.assertTrue(s.startswith("1\n00:00:00,600 --> 00:00:06,672\nหนึ่ง\n\n2\n00:00:08,000"))
    def test_srt_no_overlap(self):
        items = media.dedupe_overlaps([{"at": 0.0, "end": 9.0, "text": "a"}, {"at": 8.0, "end": 12.0, "text": "b"}])
        self.assertAlmostEqual(items[0]["end"], 7.9)
```

- [ ] **Step 2: รันให้ fail** → `ModuleNotFoundError: media`

- [ ] **Step 3: implement**

```python
def build_xfade_graph(clips, w, h, fps, xfade, fade_out):
    parts = []
    for i, c in enumerate(clips):
        S = c["seconds"]
        parts.append(f"[{c['v_in']}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1,trim=0:{S},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[{c['a_in']}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{S},asetpts=PTS-STARTPTS[a{i}]")
    if xfade <= 0 or len(clips) == 1:
        if len(clips) == 1: v, a, total = "v0", "a0", clips[0]["seconds"]
        else:
            parts.append("".join(f"[v{i}][a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=1[vc][ac]")
            v, a, total = "vc", "ac", sum(c["seconds"] for c in clips)
    else:
        v, a, elapsed = "v0", "a0", clips[0]["seconds"]
        for i in range(1, len(clips)):
            off = round(elapsed - xfade, 3)
            parts.append(f"[{v}][v{i}]xfade=transition=fade:duration={xfade}:offset={off}[x{i}]")
            parts.append(f"[{a}][a{i}]acrossfade=d={xfade}[y{i}]")
            v, a, elapsed = f"x{i}", f"y{i}", off + clips[i]["seconds"]
        total = round(elapsed, 3)
    st = round(max(0.0, total - fade_out), 3)
    parts.append(f"[{v}]fade=t=out:st={st}:d={fade_out}[vout]")
    parts.append(f"[{a}]afade=t=out:st={st}:d={fade_out}[aout]")
    return ";".join(parts), "[vout]", "[aout]", total
```
- `assemble`: ต่อฉาก `clip = find_asset` (ไม่มี → SystemExit), `S = min(seconds, probe_duration)` (+warning ถ้าสั้นกว่า), `has_audio` ไม่ใช่ → เพิ่ม `-f lavfi -t S -i anullsrc=r=48000:cl=stereo` และ `a_in` = index นั้น; encode ตาม spec §5.4 ลง `.draft.tmp.mp4` → replace
- `mix`: ตาม spec §5.5 (pass 1 → `_mix.wav`, วัด `loudnorm print_format=json` จาก stderr, gain = lufs − input_i, pass 2 `volume=gain dB,alimiter=limit=10^(tp/20):attack=5:release=50:level=false`, `-c:v copy`) แล้ววัดผลลัพธ์พิมพ์ `[mix] final I=-14.x LUFS TP=-1.x`
- `srt_text`, `fmt_ts`, `dedupe_overlaps(items)` (end_k ≤ at_{k+1} − 0.1, ขั้นต่ำ at+0.5), `write_srt` (end = probe ของไฟล์ VO ถ้ามี ไม่งั้น `max(2, len/12)`, cap ที่ total, utf-8-sig), `burn_subs` ตาม §5.7
- `contact_sheet`, `frames` ตาม §5.3 (`ImageFont.load_default(size=28)`)

- [ ] **Step 4: test ผ่าน** — `python tools/test_ani.py`

---

### Task 3: audio.py (TTS + music synth)

**Files:**
- Create: `tools/audio.py`
- Modify: `tools/test_ani.py` (AudioTests)

**Interfaces:**
- Consumes: `ani.vo_events`, `ani.music_sections`, `ani.total_seconds`, `gen.need_key`, `gen.http_bytes`
- Produces: `TTS_PROVIDERS`, `tts(project_dir, project, force)->list[Path]`, `music(project_dir, project, force)->Path`, `synth_music(sections, total, out, seed=7, sr=44100)->Path`

- [ ] **Step 1: test ที่ fail**

```python
import audio, wave
class AudioTests(unittest.TestCase):
    def test_synth_moonpetal(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.wav"
            audio.synth_music([("calm", 0, 7.5), ("threat", 7.5, 15), ("resolve", 15, 22.5), ("climax", 22.5, 30), ("resolution", 30, 38)], 38.0, out)
            with wave.open(str(out)) as w:
                self.assertEqual(w.getnchannels(), 2); self.assertEqual(w.getframerate(), 44100)
                self.assertAlmostEqual(w.getnframes() / 44100, 38.0, places=2)
                import numpy as np
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32767
            self.assertAlmostEqual(float(abs(pcm).max()), 0.89, places=1)
    def test_synth_short_two_sections(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.wav"
            audio.synth_music([("climax", 0, 3), ("calm", 3, 6)], 6.0, out)
            with wave.open(str(out)) as w: self.assertAlmostEqual(w.getnframes() / 44100, 6.0, places=2)
    def test_tts_provider_table(self):
        self.assertEqual(set(audio.TTS_PROVIDERS), {"edge", "elevenlabs", "file"})
```

- [ ] **Step 2: fail** → `ModuleNotFoundError: audio`

- [ ] **Step 3: implement** — port `moonpetal-guardian/07-audio/make_music.py` เป็น `class _Synth` (sr, n, rng, L, R; methods `hz env lp add saw_pad bell boom noise_swell`) + mood methods `(t0, dur)` ที่ใช้ offset relative:
  - `calm`: pad Dm(add9) `[50,57,62,64,65]` dur+1, cutoff 900, gain .55; bells `[74,77,81,76,74,79,81,76]` ทุก 0.8 s เริ่ม 0.8 จนกว่า > dur−0.5, gain .16, pan −0.4+0.1i
  - `threat`: drone `[38,45]` เริ่ม max(0,t0−0.3) dur+0.8 cutoff 300 gain .38; pad `[58,62,65]` cutoff 600 gain .35; shimmer `[69,70]` เริ่ม +2.5 cutoff 1800 detune .3 gain .12 pan .5; heartbeat boom(1.0) lp150 ที่ +0.9+k·1.1 (gain .22) และ +1.15+k·1.1 (.14) จนเต็ม dur
  - `resolve`: chords `[[50,57,62,65],[46,53,58,62],[48,55,60,64],[50,57,62,65,69]]` ทุก 1.9 s dur 2.2 cutoff 900+j·475 gain .5+j·.114; pulse 8th ทุก 0.25 s `[62,69,62,67]` cutoff 1500+i·80 gain .16+.016i pan สลับ; riser noise_swell(min(4,dur)) 400→9000 จบที่ท้าย section gain .10
  - `climax`: boom(3.0) gain .9 ที่ t0; crash tail reversed 1.2 s gain .10; chords `[[46,58,62,65,70],[48,60,64,67,72],[50,62,65,69,74],[50,62,66,69,74]]` ทุก 1.9 s dur 2.1 cutoff 3200 gain .55; arp bell(m,0.8) ทุก 0.125 s `[74,77,81,86,81,77]` gain .07 pan sin(i·0.7)·0.6; booms lp200 gain .45 ที่ทุก chord หลังตัวแรก
  - `resolution`: pad Dmaj9 `[50,57,62,66,69,76]` dur, cutoff 1400 a1.2 r3.5 gain .55; bells `[78,81,86,85,81,78,76,74]` ทุก 0.85 s เริ่ม 0.4 dur 3.0 gain .14 pan .4−.1i
  - `master()`: reverb IR 2.6 s (exp −2.4, lp 5000, normalize เหมือนเดิม) dry .75 + wet .9; fade ท้าย min(2.5, total/4) ^1.5; normalize peak .89; int16 stereo
- `tts`: ตาม §5.6 — edge (`asyncio.run(Communicate(text, voice, rate, pitch).save(tmp))`), elevenlabs (`POST /v1/text-to-speech/{voice}?output_format=mp3_44100_128`), file; เขียน tmp → rename; ล้มเหลวรายบรรทัดไม่หยุด
- `music`: file mode → `ffmpeg -i src -af apad,atrim=0:total,afade=t=out:st=total-2.5:d=2.5 -ar 44100 -ac 2 -c:a pcm_s16le`; synth mode → `synth_music`

- [ ] **Step 4: test ผ่าน** (synth ใช้เวลา ~10 s)

---

### Task 4: gen.py (providers + collect)

**Files:**
- Create: `tools/gen.py`
- Modify: `tools/test_ani.py` (GenTests)

**Interfaces:**
- Consumes: `ani.find_asset/retire_asset/scene_needs/reference_path/image_prompt/motion_prompt/save_project`
- Produces: `need_key(name)`, `http_json(url, method, headers, body, raw, content_type, timeout)`, `http_bytes(...)`, `download(url, out, headers)`, `IMAGE_PROVIDERS`, `VIDEO_PROVIDERS`, `generate_images(dir, project, scenes, force)->(done, missing)`, `generate_clips(...)`, `plan_collect(missing_ids, candidates)->dict`, `collect(dir, project, kind, src_dir, hours, mapping, apply)->list`

- [ ] **Step 1: test ที่ fail**

```python
import gen
class GenTests(unittest.TestCase):
    def test_plan_collect_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "b.mp4", Path(d) / "a.mp4"
            a.write_bytes(b"1"); time.sleep(0.05); b.write_bytes(b"2")
            plan = gen.plan_collect(["02", "03"], sorted([b, a], key=lambda p: p.stat().st_mtime))
            self.assertEqual(plan, {"02": a, "03": b})
    def test_plan_collect_fewer_candidates(self):
        self.assertEqual(gen.plan_collect(["01", "02"], [Path("x.mp4")]), {"01": Path("x.mp4")})
    def test_provider_tables(self):
        self.assertEqual(set(gen.IMAGE_PROVIDERS), {"manual", "gemini", "openai", "fal"})
        self.assertEqual(set(gen.VIDEO_PROVIDERS), {"manual", "flow", "gemini", "fal"})
    def test_need_key_message(self):
        os.environ.pop("ZZ_TEST_KEY", None)
        with self.assertRaises(SystemExit) as cm: gen.need_key("ZZ_TEST_KEY")
        self.assertIn("ZZ_TEST_KEY", str(cm.exception))
```

- [ ] **Step 2: fail** → `ModuleNotFoundError: gen`

- [ ] **Step 3: implement** ตาม spec §3.5 + §5.1–5.2 (endpoint/param ตามตาราง; fal ผ่าน `fal_run` queue+poll; gemini video `predictLongRunning` + poll operation ทุก 10 s ≤ 600 s, `durationSeconds` เลือกจาก {4,6,8} ที่ใกล้ `seconds`; manual/flow พิมพ์ block แล้ว return None; API providers รันขนาน `ThreadPoolExecutor(4)`; ก่อนเขียนไฟล์ใหม่เรียก `retire_asset`)

- [ ] **Step 4: test ผ่าน**

---

### Task 5: CLI wiring (new / validate / story / mark / status / collect / run)

**Files:**
- Modify: `tools/ani.py` (เพิ่ม render + main)

- [ ] **Step 1: test ที่ fail**

```python
class CliTests(unittest.TestCase):
    def test_new_then_story_and_status(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(ani.main(["new", "demo", "--root", str(root)]), 0)
            self.assertTrue((root / "demo" / "project.json").exists())
            for f in ani.FOLDERS: self.assertTrue((root / "demo" / f).is_dir())
            self.assertEqual(ani.main(["story", "--project", str(root / "demo")]), 0)
            self.assertIn("Storyboard", (root / "demo" / "01-story" / "storyboard.md").read_text("utf-8"))
            self.assertEqual(ani.main(["mark", "01", "image=redo", "note=หมอก", "--project", str(root / "demo")]), 0)
            p = json.loads((root / "demo" / "project.json").read_text("utf-8"))
            self.assertEqual(p["scenes"][0]["qc"]["image"], "redo")
            self.assertIn("redo", (root / "demo" / "status.md").read_text("utf-8"))
```

- [ ] **Step 2: fail** → `AttributeError: main`

- [ ] **Step 3: implement**
  - `render_story(dir, project)` → `01-story/storyboard.md` (หัวเรื่อง, สรุป, Style, Characters, ตาราง `| ฉาก | เวลา | ชื่อ | mood | ภาพ | motion | บทพูด |`) และ `04-prompts/prompts.md` (STYLE/CHARACTER block, reference prompt, prompt เต็มต่อฉาก ทั้ง image และ motion)
  - `render_status(dir, project)` → `status.md` ตาม §5.8 (ใช้ `media.probe_duration` แบบ lazy import)
  - `cmd_new(slug, root)` → โฟลเดอร์ + `project.json` จาก template (DEFAULTS + `_guide` + 1 ฉากตัวอย่าง)
  - `main(argv)`: argparse `cmd rest*` + `--project --root --scene* --force --yes --src --hours --map* --from --to --burn`; dispatch dict; `run` เดินตาม `STAGES` หยุดเมื่อ images/clips คืน missing ≠ []; return 0/1

- [ ] **Step 4: test ผ่าน**

---

### Task 6: Claude Code integration

**Files:**
- Create: `CLAUDE.md`, `.claude/skills/ani-pipeline/SKILL.md`

- [ ] **Step 1:** `CLAUDE.md` ≤ 40 บรรทัด: pipeline คืออะไร, คำสั่งหลัก, กติกา 6 ข้อ (source of truth = project.json; ห้ามเขียน ffmpeg เอง; ดู QC ผ่าน contact-sheet/frames-grid เท่านั้น; ก่อนใช้เครดิต Flow list ฉากให้ user; อย่าเปิดไฟล์วิดีโอ/เฟรมทีละไฟล์; รายงานด้วย `ani status`)
- [ ] **Step 2:** `SKILL.md` frontmatter `name: ani-pipeline`, `description` (trigger: ทำหนังสั้น/อนิเมชัน/คลิป Veo/Flow/storyboard/บรอดแคสวิดีโอ ในโฟลเดอร์ ANI) + เนื้อหา: workflow 10 ขั้น, คู่มือเขียน manifest, QC protocol, Flow playbook (token rules), collect, provider switch, รายงาน
- [ ] **Step 3:** ตรวจ `python tools/ani.py --help` แสดงทุก cmd

---

### Task 7: Migrate moonpetal + E2E verify

**Files:**
- Create: `moonpetal-guardian/project.json`

- [ ] **Step 1:** เขียน `project.json` จาก storyboard/prompts/vo-script เดิม (offset = 0.6/0.5/0.6/0.7/1.0; `reference.file` = `02-reference/character-sheet-rin-kogi.png`; moods calm/threat/resolve/climax/resolution)
- [ ] **Step 2:** `python tools/ani.py validate --project moonpetal-guardian` → ไม่มี warning
- [ ] **Step 3:** `python tools/ani.py run --from contact --project moonpetal-guardian` → ผ่าน contact, clips(ข้าม—มีครบ), frames, assemble, vo (edge-tts ออนไลน์), music, mix, status
- [ ] **Step 4:** ตรวจ
  ```
  ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate -of default=nw=1 moonpetal-guardian/08-final/final.mp4
  ffmpeg -hide_banner -nostats -i moonpetal-guardian/08-final/final.mp4 -af ebur128=peak=true -f null - 2>&1 | grep -E "I:|Peak:"
  ```
  Expected: 720x1280, 24/1, duration 38.0, I = -14 ± 1 LUFS, Peak ≤ -1.0 dBFS
- [ ] **Step 5:** `python tools/ani.py subs --burn --project moonpetal-guardian` → `final-subs.mp4` มี; ดู 1 เฟรมกลางเรื่องยืนยันซับไทย render
- [ ] **Step 6:** ดู `03-images/contact-sheet.jpg` และ `06-draft/frames-grid.jpg` 1 ครั้ง ยืนยันภาพ/label ถูก
- [ ] **Step 7:** ไฟล์เดิมของ user ยังอยู่ครบ (`ls moonpetal-guardian/06-draft moonpetal-guardian/08-final moonpetal-guardian/07-audio`)
- [ ] **Step 8:** code review ด้วย `oh-my-claudecode:code-reviewer` (ไม่ self-approve) แล้วแก้ CRITICAL/HIGH

---

## Self-review

- Spec coverage: §3.2 ทุก cmd → Task 5; §3.5 providers → Task 3/4; §5.x → Task 2/3/4; §3.6 → Task 6; §7 tests → Task 1–5; §9 → Task 7 ✔
- Placeholder: ไม่มี TBD; โค้ด glue ที่ไม่ได้แสดงเต็มอ้าง spec section ที่มีสูตรครบ
- Type consistency: `scene_needs(dir, scene, kind, force)` ใช้ kind = `"image" | "clip"`; `collect(kind="images"|"clips")` แปลงเป็น asset kind ภายใน; `build_xfade_graph` คืน 4 ค่าเสมอ
- Review Focus 1–5 มี test/พฤติกรรมผูกกับ Task 1, 2, 3, 4 แล้ว
