"""ANI pipeline — manifest, timeline, assets, CLI.

Spec: docs/superpowers/specs/2026-09-26-ani-pipeline-design.md
Usage: python tools/ani.py <cmd> [--project DIR] [options]
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent


def project_root(env: dict = os.environ, tools_dir: Path = TOOLS_DIR) -> Path:
    """Where stories, .env and .local live: $ANI_ROOT, else the clone — but never a plugin cache (wiped on update)."""
    if env.get("ANI_ROOT"):
        return Path(env["ANI_ROOT"]).expanduser().resolve()
    if ".claude" in tools_dir.parts and "plugins" in tools_dir.parts:
        return Path.home() / "ANI"
    return tools_dir.parent


ROOT = project_root()
sys.path.insert(0, str(TOOLS_DIR))
for _stream in (sys.stdout, sys.stderr):  # Windows console = cp1252 → Thai/arrows would crash print()
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MOODS = ("calm", "threat", "resolve", "climax", "resolution")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
CLIP_EXT = (".mp4", ".mov", ".webm")
FOLDERS = ["01-story", "02-reference", "03-images", "04-prompts", "05-clips", "06-draft", "07-audio", "08-final"]
STAGES = ["validate", "story", "images", "contact", "clips", "frames", "assemble", "vo", "music", "mix", "subs", "status"]
ASSET_DIR = {"image": "03-images", "clip": "05-clips"}
ASSET_EXT = {"image": IMAGE_EXT, "clip": CLIP_EXT}

DEFAULTS = {
    "slug": "", "title": "", "style": "", "characters": "",
    "video": {"width": 720, "height": 1280, "fps": 24, "aspect": "9:16", "resolution": "720p"},
    "motion_suffix": ("Keep the exact character design, art style, colors and composition of the source image. "
                      "Smooth natural motion, no morphing, no text."),
    "reference": {"prompt": "", "file": None},
    "providers": {"image": "manual", "video": "flow", "tts": "edge", "music": "synth"},
    "provider_config": {
        "gemini": {"image_model": "gemini-2.5-flash-image", "video_model": "veo-3.1-fast-generate-preview"},
        "openai": {"image_model": "gpt-image-1", "quality": "high"},
        "fal": {"image_model": "fal-ai/nano-banana-pro", "image_edit_model": "fal-ai/nano-banana-pro/edit",
                "video_model": "fal-ai/veo3.1/fast/image-to-video", "image_params": {}, "video_params": {}},
        "elevenlabs": {"model": "eleven_multilingual_v2"},
        "flow": {"model": "Veo 3.1 - Lite", "project_url": "", "downloads": "~/Downloads",
                 "image_model": "Nano Banana 2",
                 "cdp": "http://127.0.0.1:9333", "profile_dir": "~/.ani/chrome-flow", "max_wait": 600},
    },
    "voices": {"narrator": "th-TH-PremwadeeNeural"},
    "tts": {"rate": "+0%", "pitch": "+0Hz"},
    "music": {"file": None, "seed": 7, "gain": 0.5},
    "edit": {"xfade": 0.5, "fade_out": 1.0, "clip_audio": 0.28, "vo_gain": 1.0, "duck_ratio": 4,
             "duck_threshold": 0.1, "lufs": -14, "true_peak": -1.5, "crf": 18},
    "subs": {"enabled": False, "font": "Leelawadee UI", "size": 56, "margin_v": 220},  # px of output video
    "scenes": [],
}


# ---------------------------------------------------------------- manifest
def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def apply_defaults(data: dict) -> dict:
    project = deep_merge(DEFAULTS, data)
    scenes = project.get("scenes") or []
    if not scenes:
        raise SystemExit("ani: project.json ไม่มี scenes — เพิ่มอย่างน้อย 1 ฉาก")
    seen = set()
    for i, s in enumerate(scenes):
        sid = str(s.get("id") or "").strip()
        if not sid:
            raise SystemExit(f"ani: scenes[{i}] ไม่มี id — ใส่ id เช่น \"01\"")
        if sid in seen:
            raise SystemExit(f"ani: scene id ซ้ำ: {sid}")
        seen.add(sid)
        s["id"] = sid
        if float(s.get("seconds") or 0) <= 0:
            raise SystemExit(f"ani: scene {sid} ต้องมี seconds > 0")
        if s.get("mood", "calm") not in MOODS:
            print(f"[validate] warning: scene {sid} mood '{s.get('mood')}' ไม่รู้จัก → ใช้ calm (เลือกจาก {', '.join(MOODS)})")
            s["mood"] = "calm"
        s.setdefault("mood", "calm")
        s["qc"] = {"image": "", "clip": "", "note": "", **(s.get("qc") or {})}
        s.setdefault("vo", [])
        for v in s["vo"]:
            if v.get("speaker") not in project["voices"]:
                print(f"[validate] warning: scene {sid} speaker '{v.get('speaker')}' ไม่มีใน voices → ใช้เสียง narrator")
        for key in ("image_prompt", "motion_prompt"):
            if not s.get(key):
                print(f"[validate] warning: scene {sid} ไม่มี {key}")
    return project


def load_project(project_dir: Path) -> dict:
    p = Path(project_dir) / "project.json"
    if not p.exists():
        raise SystemExit(f"ani: ไม่พบ {p} — รัน `python tools/ani.py new <slug>` หรือใส่ --project DIR")
    try:
        return apply_defaults(json.loads(p.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        raise SystemExit(f"ani: project.json ไม่ใช่ JSON ที่ถูกต้อง — {e}")


def save_project(project_dir: Path, project: dict) -> None:
    p = Path(project_dir) / "project.json"
    tmp = p.with_name(".project.json.tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def load_env(root: Path = ROOT) -> None:
    p = Path(root) / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ---------------------------------------------------------------- timeline
def timeline(project: dict) -> list[dict]:
    x = float(project["edit"]["xfade"])
    out, start = [], 0.0
    for i, s in enumerate(project["scenes"]):
        if i:
            start = out[-1]["end"] - x
        d = float(s["seconds"])
        out.append({"id": s["id"], "start": round(start, 3), "end": round(start + d, 3), "seconds": d,
                    "mood": s.get("mood", "calm")})
    return out


def total_seconds(project: dict) -> float:
    return timeline(project)[-1]["end"]


def vo_events(project: dict) -> list[dict]:
    ev = []
    for t, s in zip(timeline(project), project["scenes"]):
        for n, v in enumerate(s.get("vo") or [], 1):
            ev.append({"scene": s["id"], "n": n, "speaker": v.get("speaker", "narrator"), "text": v["text"],
                       "at": round(t["start"] + float(v.get("offset", 0.5)), 3),
                       "file": f"07-audio/vo/{s['id']}-{n}.mp3"})
    return sorted(ev, key=lambda e: e["at"])


def music_sections(project: dict) -> list[tuple[str, float, float]]:
    tl = timeline(project)
    total = tl[-1]["end"]
    return [(t["mood"], t["start"], tl[i + 1]["start"] if i + 1 < len(tl) else total) for i, t in enumerate(tl)]


# ---------------------------------------------------------------- assets
def _asset_files(project_dir: Path, kind: str, scene_id: str) -> list[Path]:
    """Files of one scene: scene-{id}.ext or scene-{id}[-_.]anything.ext — never scene-{id}0... of another scene."""
    folder = Path(project_dir) / ASSET_DIR[kind]
    if not folder.is_dir():
        return []
    pat = re.compile(rf"scene-{re.escape(scene_id)}(?:[-_.].*)?$")
    return [p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in ASSET_EXT[kind] and pat.fullmatch(p.name)]


def find_asset(project_dir: Path, kind: str, scene_id: str) -> Path | None:
    hits = _asset_files(project_dir, kind, scene_id)
    # newest file wins → dropping a redo file next to the old one just works
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def retire_asset(project_dir: Path, kind: str, scene_id: str, keep: Path | None = None) -> list[Path]:
    """Move existing assets of the scene (except `keep`) to <folder>/_old/ so only the new one matches."""
    moved = []
    for p in _asset_files(project_dir, kind, scene_id):
        if keep is not None and p.resolve() == Path(keep).resolve():
            continue
        old = p.parent / "_old"
        old.mkdir(exist_ok=True)
        dst = old / f"{p.stem}.{int(time.time() * 1000)}{p.suffix}"
        p.replace(dst)
        moved.append(dst)
    return moved


INPUTS_FILE = ".ani-inputs.json"


def is_stale(project_dir: Path, key: str, out: Path, inputs) -> bool:
    """True when `out` was built from different inputs than now. A file seen for the first time
    (new project, freshly generated/collected) records a baseline and counts as current."""
    path = Path(project_dir) / INPUTS_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    fp = hashlib.sha1(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    stamp = [out.name, out.stat().st_mtime_ns]
    rec = state.get(key)
    if rec and rec.get("file") == stamp:
        if rec.get("input") != fp:
            print(f"[stale] {key}: input เปลี่ยนจากตอนสร้าง {out.name} → ทำใหม่")
            return True
        return False
    state[key] = {"file": stamp, "input": fp}
    tmp = path.with_name(INPUTS_FILE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return False


def asset_inputs(project_dir: Path, project: dict, scene: dict, kind: str) -> list:
    if kind == "image":
        return [image_prompt(project, scene)]
    img = find_asset(project_dir, "image", scene["id"])  # new source image → clip is stale too
    return [motion_prompt(project, scene), [img.name, img.stat().st_mtime_ns] if img else None]


def scene_needs(project_dir: Path, scene: dict, kind: str, force: bool = False, project: dict | None = None) -> bool:
    if force or (scene.get("qc") or {}).get(kind) == "redo":
        return True
    asset = find_asset(project_dir, kind, scene["id"])
    if asset is None:
        return True
    return project is not None and is_stale(project_dir, f"{kind}:{scene['id']}", asset,
                                            asset_inputs(project_dir, project, scene, kind))


def reference_path(project_dir: Path, project: dict) -> Path | None:
    f = (project.get("reference") or {}).get("file")
    if f:
        p = Path(project_dir) / f
        return p if p.exists() else None
    folder = Path(project_dir) / "02-reference"
    if not folder.is_dir():
        return None
    hits = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    pref = [p for p in hits if p.stem == "reference"]
    return (pref or hits or [None])[0]


# ---------------------------------------------------------------- prompts
def image_prompt(project: dict, scene: dict) -> str:
    return "\n".join(x for x in (scene.get("image_prompt", ""), project.get("style", ""), project.get("characters", "")) if x).strip()


def motion_prompt(project: dict, scene: dict) -> str:
    return f"{scene.get('motion_prompt', '')} {project.get('motion_suffix', '')}".strip()


# ---------------------------------------------------------------- renders (human-readable)
def _cell(text: str) -> str:
    return str(text or "—").replace("|", "\\|").replace("\n", " ")


def render_story(project_dir: Path, project: dict) -> list[Path]:
    tl, v, pv = timeline(project), project["video"], project["providers"]
    lines = [f"# {project['title'] or project['slug']}", "",
             f"- ความยาว ~{total_seconds(project):.0f} วิ | {len(tl)} ฉาก | {v['aspect']} {v['width']}x{v['height']} @{v['fps']}fps | xfade {project['edit']['xfade']}s",
             f"- providers: image={pv['image']}, video={pv['video']}, tts={pv['tts']}, music={pv['music']}", "",
             "## Style", project["style"] or "—", "", "## Characters", project["characters"] or "—", "",
             "## Storyboard", "| ฉาก | เวลา | ชื่อ | mood | ภาพ | motion | บทพูด |", "|---|---|---|---|---|---|---|"]
    for t, s in zip(tl, project["scenes"]):
        vo = " / ".join(f"{x.get('speaker', '')}: {x['text']}" for x in s.get("vo") or [])
        lines.append(f"| {s['id']} | {t['start']:g}–{t['end']:g}s | {_cell(s.get('title'))} | {s['mood']} | "
                     f"{_cell(s.get('image_prompt'))} | {_cell(s.get('motion_prompt'))} | {_cell(vo)} |")
    story = Path(project_dir) / "01-story" / "storyboard.md"
    story.parent.mkdir(parents=True, exist_ok=True)
    story.write_text("\n".join(lines) + "\n", encoding="utf-8")
    p = ["# Prompts — " + (project["title"] or project["slug"]), "", "## STYLE BLOCK", project["style"], "",
         "## CHARACTER BLOCK", project["characters"], "", "## MOTION SUFFIX", project["motion_suffix"], ""]
    if (project.get("reference") or {}).get("prompt"):
        p += ["## Reference sheet", "```", "\n".join(x for x in (project["reference"]["prompt"], project["style"], project["characters"]) if x), "```", ""]
    for s in project["scenes"]:
        p += [f"## scene {s['id']} — {s.get('title', '')}", "### image", "```", image_prompt(project, s), "```",
              "### motion", "```", motion_prompt(project, s), "```", ""]
    prompts = Path(project_dir) / "04-prompts" / "prompts.md"
    prompts.parent.mkdir(parents=True, exist_ok=True)
    prompts.write_text("\n".join(p), encoding="utf-8")
    print(f"[story] 01-story/storyboard.md + 04-prompts/prompts.md ({len(tl)} ฉาก, {total_seconds(project):g}s)")
    return [story, prompts]


def render_status(project_dir: Path, project: dict) -> Path:
    import media
    project_dir = Path(project_dir)
    rows = [f"# สถานะงาน — {project['title'] or project['slug']}", "",
            "| ฉาก | ภาพ | คลิป | หมายเหตุ |", "|---|---|---|---|"]
    todo = []
    for s in project["scenes"]:
        img, clip, qc = find_asset(project_dir, "image", s["id"]), find_asset(project_dir, "clip", s["id"]), s["qc"]
        icell = (f"✅ {img.name}" if img else "❌ ยังไม่มี") + (f" ({qc['image']})" if qc["image"] else "")
        ccell = (f"✅ {clip.name} {media.probe_duration(clip):.1f}s" if clip else "❌ ยังไม่มี") + (f" ({qc['clip']})" if qc["clip"] else "")
        rows.append(f"| {s['id']} | {icell} | {ccell} | {_cell(qc.get('note'))} |")
        if not img or qc["image"] == "redo":
            todo.append(f"images ฉาก {s['id']}")
        if not clip or qc["clip"] == "redo":
            todo.append(f"clips ฉาก {s['id']}")
    rows += ["", "## ไฟล์"]
    for label, relp in (("draft", "06-draft/draft.mp4"), ("final", "08-final/final.mp4"), ("final+subs", "08-final/final-subs.mp4"),
                        ("music", "07-audio/music.wav"), ("subs", "07-audio/subs.srt")):
        f = project_dir / relp
        rows.append(f"- {label}: " + (f"✅ `{relp}` {f.stat().st_size / 1e6:.1f} MB" if f.exists() else f"❌ `{relp}`"))
        if not f.exists() and label in ("draft", "final", "music"):
            todo.append({"draft": "assemble", "final": "mix", "music": "music"}[label])
    ev = vo_events(project)
    have = sum((project_dir / e["file"]).exists() for e in ev)
    rows.append(f"- VO: {have}/{len(ev)} ไฟล์ (tts={project['providers']['tts']})")
    if have < len(ev):
        todo.append("vo")
    pv = project["providers"]
    rows += ["", f"providers: image={pv['image']}, video={pv['video']}, tts={pv['tts']}, music={pv['music']}", "", "## ทำต่อได้"]
    rows += [f"- {t}" for t in todo] or ["- ครบทุก stage แล้ว (ซับ: `subs --burn`)"]
    out = project_dir / "status.md"
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    return out


# ---------------------------------------------------------------- commands
TEMPLATE_GUIDE = [
    "scenes: id ('01'..), seconds (8 = Veo clip), mood calm|threat|resolve|climax|resolution, title, "
    "image_prompt (EN, เฉพาะฉากนี้ — style/characters ต่อท้ายให้เอง), motion_prompt (กล้อง+การเคลื่อนไหว), "
    "vo [{speaker, text ไทย ≤14 คำ, offset วินาทีจากต้นฉาก}]",
    "providers: image manual|flow|gemini|openai|fal · video manual|flow|gemini|fal · tts edge|elevenlabs|file · music synth|file",
    "ลำดับ: validate → story → images → contact → clips → frames → assemble → vo → music → mix → subs → status  (หรือ `run`)",
]


def cmd_new(slug: str, root: Path) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise SystemExit("ani: slug ต้องใช้ a-z, 0-9 และขีดกลาง เช่น my-film")
    d = Path(root) / slug
    if d.exists():
        raise SystemExit(f"ani: {d} มีอยู่แล้ว — ใช้ชื่ออื่น หรือแก้โปรเจกต์เดิม")
    for f in FOLDERS:
        (d / f).mkdir(parents=True, exist_ok=True)
    tpl = deep_merge(DEFAULTS, {
        "slug": slug, "title": slug, "_guide": TEMPLATE_GUIDE,
        "providers": {"image": "manual", "video": "manual"},
        "reference": {"prompt": "", "file": None},
        "scenes": [{"id": "01", "seconds": 8, "mood": "calm", "title": "",
                    "image_prompt": "", "motion_prompt": "", "vo": [],
                    "qc": {"image": "", "clip": "", "note": ""}}],
    })
    (d / "project.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[new] {d}\n  1) เขียน {d / 'project.json'} (scenes/style/characters/vo)\n"
          f"  2) python tools/ani.py validate --project {d}\n  3) python tools/ani.py run --project {d}")
    return d


def cmd_mark(project_dir: Path, project: dict, rest: list[str]) -> None:
    if not rest:
        raise SystemExit("ani: mark <scene-id> image=pass|redo clip=pass|redo note=\"...\"")
    scene = next((s for s in project["scenes"] if s["id"] == rest[0]), None)
    if not scene:
        raise SystemExit(f"ani: ไม่มีฉาก {rest[0]} (มี: {', '.join(s['id'] for s in project['scenes'])})")
    for kv in rest[1:]:
        k, _, v = kv.partition("=")
        if k not in ("image", "clip", "note") or (k != "note" and v not in ("pass", "redo", "")):
            raise SystemExit(f"ani: mark รับเฉพาะ image=pass|redo|'' clip=pass|redo|'' note=... (ได้ '{kv}')")
        scene["qc"][k] = v
    save_project(project_dir, project)
    print(f"[mark] {scene['id']} → {scene['qc']}")


def run_stage(name: str, project_dir: Path, project: dict, args) -> bool:
    """Run one stage. Returns False when the stage needs manual input before the pipeline can continue."""
    scenes = args.scene or None
    if name == "validate":
        incomplete = [f"{s['id']} ({', '.join(key for key in ('image_prompt', 'motion_prompt') if not s.get(key))})"
                      for s in project["scenes"] if not s.get("image_prompt") or not s.get("motion_prompt")]
        if incomplete:
            raise SystemExit("ani: project.json ยังไม่มี prompt สำหรับฉาก " + ", ".join(incomplete))
        print(f"[validate] ok — {len(project['scenes'])} ฉาก, {total_seconds(project):g}s")
    elif name == "story":
        render_story(project_dir, project)
    elif name in ("images", "clips"):
        import gen
        fn = gen.generate_images if name == "images" else gen.generate_clips
        _, missing = fn(project_dir, project, scenes, args.force, args.yes)
        return not missing
    elif name == "contact":
        import media
        media.contact_sheet(project_dir, project)
    elif name == "frames":
        import media
        media.frames(project_dir, project, scenes)
    elif name == "assemble":
        import media
        media.assemble(project_dir, project)
    elif name == "vo":
        import audio
        return len(audio.tts(project_dir, project, args.force)) == len(vo_events(project))
    elif name == "music":
        import audio
        audio.music(project_dir, project, args.force)
    elif name == "mix":
        import media
        media.mix(project_dir, project)
    elif name == "subs":
        import media
        media.write_srt(project_dir, project)
        if args.burn or project["subs"]["enabled"]:
            media.burn_subs(project_dir, project)
    elif name == "status":
        render_status(project_dir, project)
    else:
        raise SystemExit(f"ani: stage '{name}' ไม่รู้จัก — เลือกจาก {', '.join(STAGES)}")
    return True


def cmd_run(project_dir: Path, project: dict, args) -> int:
    a = STAGES.index(args.from_) if args.from_ else 0
    b = STAGES.index(args.to) if args.to else len(STAGES) - 1
    for st in STAGES[a:b + 1]:
        if st == "subs" and not (args.burn or project["subs"]["enabled"]):
            continue
        print(f"\n▶ {st}")
        if not run_stage(st, project_dir, project, args):
            print(f"\n[run] หยุดที่ `{st}` — ทำตามคำแนะนำข้างบน แล้วรันต่อ: python tools/ani.py run --from {st} --project {project_dir}")
            if st != "status":
                render_status(project_dir, project)
            return 1
    return 0


def parse_map(items: list[str] | None) -> dict[str, str] | None:
    if not items:
        return None
    out = {}
    for m in items:
        k, sep, v = m.partition("=")
        if not sep or not k or not v:
            raise SystemExit(f"ani: --map ต้องเป็น <scene-id>=<path> (ได้ '{m}')")
        out[k] = v
    return out


def _resolve_project(args) -> Path:
    if args.project:
        return Path(args.project).resolve()
    if (Path.cwd() / "project.json").exists():
        return Path.cwd()
    found = sorted(p.parent.name for p in ROOT.glob("*/project.json"))
    raise SystemExit("ani: ใส่ --project DIR (โปรเจคที่มี: " + (", ".join(found) or "ยังไม่มี — `ani new <slug>`") + ")")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python tools/ani.py", description="ANI pipeline — หนังสั้น AI จาก project.json",
                                  epilog="stages: " + " → ".join(STAGES) + "\nอื่น ๆ: new <slug> | run [--from S --to S] | mark <id> image=redo | collect images|clips [--yes] | ui [--port N]",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=STAGES + ["new", "run", "mark", "collect", "ui"])
    ap.add_argument("rest", nargs="*", help="new: slug | mark: id k=v... | collect: images|clips")
    ap.add_argument("--project", help="โฟลเดอร์โปรเจค (default: cwd ที่มี project.json)")
    ap.add_argument("--root", default=str(ROOT), help="โฟลเดอร์แม่สำหรับ new (default: ANI/)")
    ap.add_argument("--scene", nargs="*", help="ทำเฉพาะฉาก เช่น --scene 03 04")
    ap.add_argument("--force", action="store_true", help="ทำใหม่แม้มี output แล้ว")
    ap.add_argument("--yes", action="store_true", help="collect: ย้ายไฟล์จริง (default dry-run) | images/clips (flow): ยืนยันใช้เครดิต")
    ap.add_argument("--src", help="collect: โฟลเดอร์ต้นทาง (default ~/Downloads)")
    ap.add_argument("--hours", type=float, default=6.0, help="collect: รับไฟล์ที่ใหม่กว่า N ชม. (default 6)")
    ap.add_argument("--map", nargs="*", help="collect: จับคู่เอง เช่น --map 03=C:/x.mp4")
    ap.add_argument("--from", dest="from_", choices=STAGES, help="run: เริ่มจาก stage")
    ap.add_argument("--to", choices=STAGES, help="run: หยุดหลัง stage")
    ap.add_argument("--burn", action="store_true", help="subs: burn-in ลง 08-final/final-subs.mp4")
    ap.add_argument("--port", type=int, default=8765, help="ui: พอร์ตของเว็บในเครื่อง (default 8765)")
    ap.add_argument("--no-open", action="store_true", help="ui: ไม่เปิด browser อัตโนมัติ")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        if not args.rest:
            raise SystemExit("ani: new <slug>")
        cmd_new(args.rest[0], Path(args.root))
        return 0
    if args.cmd == "ui":
        import dashboard
        dashboard.serve(ROOT, args.port, not args.no_open)
        return 0
    load_env(ROOT)
    project_dir = _resolve_project(args)
    project = load_project(project_dir)
    if args.cmd == "run":
        return cmd_run(project_dir, project, args)
    if args.cmd == "mark":
        cmd_mark(project_dir, project, args.rest)
        render_status(project_dir, project)
        return 0
    if args.cmd == "collect":
        import gen
        if not args.rest:
            raise SystemExit("ani: collect images|clips [--yes] [--src DIR] [--hours N] [--map 03=path]")
        src = args.src or project["provider_config"].get("flow", {}).get("downloads") or "~/Downloads"
        gen.collect(project_dir, project, args.rest[0], Path(src), args.hours, parse_map(args.map), apply=args.yes)
        return 0
    return 0 if run_stage(args.cmd, project_dir, project, args) else 1


if __name__ == "__main__":
    sys.exit(main())
