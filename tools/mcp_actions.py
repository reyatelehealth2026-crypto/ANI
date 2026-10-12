"""Safe, local operations shared by the ANI MCP tools."""
from __future__ import annotations

import contextlib
import io
import math
import re
from pathlib import Path
from types import SimpleNamespace

import ani
import dashboard


LOCAL_STAGES = {"validate", "story", "contact", "frames", "assemble", "vo", "music", "mix", "subs", "status"}
SCENE_ID = re.compile(r"[A-Za-z0-9_-]+")


def _directory(root: Path, slug: str) -> Path:
    directory = dashboard.project_dir(root, slug)
    if directory is None:
        raise ValueError(f"ไม่พบโปรเจกต์ {slug}")
    return directory


def _project(directory: Path) -> dict:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return ani.load_project(directory)
    except SystemExit as error:
        raise ValueError(str(error)) from error


def list_stories(root: Path) -> list[dict]:
    return dashboard.list_projects(root)


def get_story(root: Path, slug: str) -> dict:
    detail = dashboard.project_detail(root, slug)
    if detail is None:
        raise ValueError(f"ไม่พบโปรเจกต์ {slug}")
    return detail


def create_story(root: Path, slug: str, title: str, style: str, characters: str,
                 scenes: list[dict], voices: dict[str, str] | None = None) -> dict:
    if not dashboard.SLUG.fullmatch(slug):
        raise ValueError("slug ต้องใช้ a-z, 0-9 และขีดกลาง")
    if not title.strip() or not style.strip() or not characters.strip():
        raise ValueError("ต้องมี title, style และ characters ของเรื่องใหม่")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("ต้องมี scenes อย่างน้อยหนึ่งฉาก")
    clean_scenes = []
    for scene in scenes:
        if not isinstance(scene, dict) or not SCENE_ID.fullmatch(str(scene.get("id", ""))):
            raise ValueError("scene id ต้องใช้ตัวอักษร ตัวเลข _ หรือ -")
        try:
            seconds = float(scene.get("seconds", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"scene {scene['id']} ต้องมี seconds > 0") from error
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"scene {scene['id']} ต้องมี seconds > 0")
        if not str(scene.get("image_prompt") or "").strip() or not str(scene.get("motion_prompt") or "").strip():
            raise ValueError(f"scene {scene['id']} ต้องมี image_prompt และ motion_prompt")
        if not isinstance(scene.get("vo", []), list):
            raise ValueError(f"scene {scene['id']} vo ต้องเป็น list")
        voice_lines = []
        for line in scene.get("vo", []):
            if not isinstance(line, dict) or not str(line.get("text") or "").strip():
                raise ValueError(f"scene {scene['id']} บทพูดต้องมี text")
            try:
                offset = float(line.get("offset", 0.5))
            except (TypeError, ValueError) as error:
                raise ValueError(f"scene {scene['id']} offset ของบทพูดไม่ถูกต้อง") from error
            if not math.isfinite(offset) or offset < 0 or offset >= seconds:
                raise ValueError(f"scene {scene['id']} offset ของบทพูดต้องอยู่ในฉาก")
            voice_lines.append({"speaker": str(line.get("speaker") or "narrator"),
                                "text": str(line["text"]).strip(), "offset": offset})
        clean_scenes.append({"id": str(scene["id"]), "seconds": seconds,
                             "title": str(scene.get("title") or ""),
                             "mood": str(scene.get("mood") or "calm"),
                             "image_prompt": str(scene["image_prompt"]).strip(),
                             "motion_prompt": str(scene["motion_prompt"]).strip(),
                             "vo": voice_lines})
    if voices is not None and (not isinstance(voices, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in voices.items())):
        raise ValueError("voices ต้องเป็น object ของชื่อผู้พูดและชื่อเสียง")
    data = {"slug": slug, "title": title.strip(), "style": style.strip(),
            "characters": characters.strip(), "scenes": clean_scenes,
            "providers": {"image": "manual", "video": "manual"}}
    if voices:
        data["voices"] = voices
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            project = ani.apply_defaults(data)
            ani.run_stage("validate", Path(root) / slug, project,
                          SimpleNamespace(scene=None, force=False, yes=False, burn=False))
    except (SystemExit, TypeError, KeyError) as error:
        raise ValueError(str(error)) from error
    directory = Path(root).resolve() / slug
    if directory.exists() or directory.is_symlink() or directory.resolve().parent != Path(root).resolve():
        raise ValueError(f"โปรเจกต์ {slug} มีอยู่แล้วหรือ path ไม่ปลอดภัย")
    with contextlib.redirect_stdout(io.StringIO()):
        ani.cmd_new(slug, root)
        ani.save_project(directory, project)
        ani.render_story(directory, project)
    return get_story(root, slug)


def mark_scene(root: Path, slug: str, scene_id: str, image: str | None = None,
               clip: str | None = None, note: str | None = None) -> dict:
    directory = _directory(root, slug)
    project = _project(directory)
    changes = []
    for kind, value in (("image", image), ("clip", clip)):
        if value is not None:
            if value not in ("pass", "redo", ""):
                raise ValueError(f"{kind} ต้องเป็น pass, redo หรือค่าว่าง")
            changes.append(f"{kind}={value}")
    if note is not None:
        changes.append(f"note={note}")
    if not changes:
        raise ValueError("ต้องระบุ image, clip หรือ note อย่างน้อยหนึ่งค่า")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ani.cmd_mark(directory, project, [scene_id, *changes])
    except SystemExit as error:
        raise ValueError(str(error)) from error
    return get_story(root, slug)


def plan_media(root: Path, slug: str, kind: str, force: bool = False) -> dict:
    if kind not in ("images", "clips"):
        raise ValueError("kind ต้องเป็น images หรือ clips")
    directory = _directory(root, slug)
    project = _project(directory)
    asset_kind = "image" if kind == "images" else "clip"
    jobs = []
    for scene in project["scenes"]:
        if ani.scene_needs(directory, scene, asset_kind, force, project):
            jobs.append({"scene_id": scene["id"], "title": scene.get("title", ""),
                         "prompt": ani.image_prompt(project, scene) if kind == "images"
                         else ani.motion_prompt(project, scene),
                         "source_image": str(ani.find_asset(directory, "image", scene["id"]))
                         if kind == "clips" and ani.find_asset(directory, "image", scene["id"]) else None})
    provider = project["providers"][asset_kind if kind == "images" else "video"]
    import agent_workflow
    policy = agent_workflow.status(root)['policy']
    standing_budget = provider == 'flow' and policy['enabled']
    return {"slug": slug, "kind": kind, "provider": provider, "jobs": jobs,
            "needs_approval": provider != "manual" and not standing_budget,
            "standing_budget": policy if standing_budget else None,
            "cost_note": 'อ่านราคา Flow และจองเครดิตด้วย reserve_agent_generation ก่อนส่งงาน ไม่ถามซ้ำภายในวงเงิน' if standing_budget else
            "ราคา/เครดิตขึ้นกับ provider และรุ่นที่เลือก ตรวจราคาปัจจุบันและขออนุมัติก่อนสร้างจริง"
            if provider != "manual" else "manual: ไม่มีค่า API จากเครื่องมือนี้"}


def run_local_stage(root: Path, slug: str, stage: str, scene_ids: list[str] | None = None,
                    force: bool = False, burn: bool = False) -> dict:
    if stage not in LOCAL_STAGES:
        raise ValueError("MCP รันได้เฉพาะ stage ในเครื่อง; images/clips ต้องใช้ CLI หลังอนุมัติค่าใช้จ่าย")
    directory = _directory(root, slug)
    project = _project(directory)
    if stage == "vo" and project["providers"]["tts"] not in ("edge", "file"):
        raise ValueError("TTS provider นี้อาจคิดเงิน; ใช้ CLI หลังอนุมัติค่าใช้จ่าย")
    if stage == "music" and project["providers"]["music"] not in ("synth", "file"):
        raise ValueError("music provider นี้อาจคิดเงิน; ใช้ CLI หลังอนุมัติค่าใช้จ่าย")
    if scene_ids is not None:
        known = {scene["id"] for scene in project["scenes"]}
        if not isinstance(scene_ids, list) or any(scene_id not in known for scene_id in scene_ids):
            raise ValueError("scene_ids มีฉากที่ไม่อยู่ในโปรเจกต์")
    args = SimpleNamespace(scene=scene_ids, force=force, yes=False, burn=burn)
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            complete = ani.run_stage(stage, directory, project, args)
    except SystemExit as error:
        raise ValueError(str(error)) from error
    return {"stage": stage, "complete": complete, "output": output.getvalue(),
            "project": get_story(root, slug)}
