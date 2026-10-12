"""Local project dashboard with explicit Flow session and generation actions."""
from __future__ import annotations

import json
import math
import mimetypes
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import ani


WEB_DIR = Path(__file__).resolve().parent / "ui"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STATIC = {"/": "index.html", "/styles.css": "styles.css", "/app.js": "app.js"}


def _number(value, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def project_dir(root: Path, slug: str) -> Path | None:
    if not SLUG.fullmatch(slug):
        return None
    root = Path(root).resolve()
    candidate = (root / slug).resolve()
    return candidate if candidate.parent == root and (candidate / "project.json").is_file() else None


def _read_project(directory: Path) -> dict:
    data = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise ValueError("project.json ต้องเป็น object ที่มี scenes เป็น list")
    if any(not isinstance(scene, dict) for scene in data["scenes"]):
        raise ValueError("scenes ต้องเป็น object ทุกฉาก")
    return data


def _asset(directory: Path, kind: str, scene_id: str) -> Path | None:
    found = ani.find_asset(directory, kind, scene_id)
    return found if found and found.resolve().is_relative_to(directory) else None


def _summary(directory: Path, data: dict) -> dict:
    scenes = data["scenes"]
    image_count = sum(_asset(directory, "image", str(scene.get("id", ""))) is not None for scene in scenes)
    clip_count = sum(_asset(directory, "clip", str(scene.get("id", ""))) is not None for scene in scenes)
    review_count = sum(any(_object(scene.get("qc")).get(kind) == "redo" for kind in ("image", "clip"))
                       for scene in scenes)
    final = (directory / "08-final" / "final.mp4").is_file()
    subs = (directory / "08-final" / "final-subs.mp4").is_file()
    draft = (directory / "06-draft" / "draft.mp4").is_file()
    music = (directory / "07-audio" / "music.wav").is_file()
    subtitle_file = (directory / "07-audio" / "subs.srt").is_file()
    voice_files = [directory / "07-audio" / "vo" / f"{scene.get('id', '')}-{index}.mp3"
                   for scene in scenes for index, line in enumerate(scene.get("vo") if isinstance(scene.get("vo"), list) else [], 1)
                   if isinstance(line, dict)]
    voice_count = sum(path.is_file() for path in voice_files)
    cover = (directory / "03-images" / "contact-sheet.jpg").is_file() or image_count > 0
    if final:
        state = "review" if image_count < len(scenes) or clip_count < len(scenes) or review_count else "complete"
    elif clip_count:
        state = "production"
    else:
        state = "planning"
    xfade = max(0.0, _number(_object(data.get("edit")).get("xfade"), 0.5))
    duration = max(0.0, sum(max(0.0, _number(scene.get("seconds"))) for scene in scenes)
                   - max(0, len(scenes) - 1) * xfade)
    return {
        "slug": directory.name,
        "title": str(data.get("title") or directory.name),
        "scene_count": len(scenes),
        "image_count": image_count,
        "clip_count": clip_count,
        "review_count": review_count,
        "duration": round(duration, 1),
        "final": final, "subs": subs, "draft": draft, "music": music,
        "subtitle_file": subtitle_file, "voice_count": voice_count, "voice_total": len(voice_files),
        "cover": cover,
        "state": state,
        "updated_at": int((directory / "project.json").stat().st_mtime),
    }


def list_projects(root: Path) -> list[dict]:
    projects = []
    for manifest in Path(root).glob("*/project.json"):
        directory = project_dir(root, manifest.parent.name)
        if directory is None:
            continue
        try:
            projects.append(_summary(directory, _read_project(directory)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            projects.append({"slug": directory.name, "title": directory.name, "scene_count": 0,
                             "image_count": 0, "clip_count": 0, "review_count": 0, "duration": 0,
                             "final": False, "subs": False, "draft": False, "music": False,
                             "subtitle_file": False, "voice_count": 0, "voice_total": 0,
                             "cover": False, "state": "error",
                             "error": str(error), "updated_at": int(manifest.stat().st_mtime)})
    return sorted(projects, key=lambda project: project["updated_at"], reverse=True)


def project_detail(root: Path, slug: str) -> dict | None:
    directory = project_dir(root, slug)
    if directory is None:
        return None
    data = _read_project(directory)
    detail = _summary(directory, data)
    xfade = max(0.0, _number(_object(data.get("edit")).get("xfade"), 0.5))
    start, scenes = 0.0, []
    for index, scene in enumerate(data["scenes"]):
        if index:
            start = max(0.0, scenes[-1]["end"] - xfade)
        scene_id = str(scene.get("id", ""))
        seconds = max(0.0, _number(scene.get("seconds")))
        image = _asset(directory, "image", scene_id)
        clip = _asset(directory, "clip", scene_id)
        qc = _object(scene.get("qc"))
        vo = scene.get("vo") if isinstance(scene.get("vo"), list) else []
        scenes.append({
            "id": scene_id, "title": str(scene.get("title") or f"ฉาก {scene_id}"),
            "start": round(start, 2), "end": round(start + seconds, 2), "seconds": seconds,
            "mood": str(scene.get("mood") or ""),
            "image_prompt": str(scene.get("image_prompt") or ""),
            "motion_prompt": str(scene.get("motion_prompt") or ""),
            "image": image.name if image else None, "clip": clip.name if clip else None,
            "qc": {"image": str(qc.get("image") or ""), "clip": str(qc.get("clip") or ""),
                   "note": str(qc.get("note") or "")},
            "vo": [{"speaker": str(item.get("speaker") or ""), "text": str(item.get("text") or ""),
                    "offset": _number(item.get("offset"))} for item in vo if isinstance(item, dict)],
        })
    providers = _object(data.get("providers"))
    video = _object(data.get("video"))
    detail.update({
        "style": str(data.get("style") or ""), "characters": str(data.get("characters") or ""),
        "providers": {kind: str(providers.get(kind) or "—") for kind in ("image", "video", "tts", "music")},
        "video": {kind: video.get(kind) for kind in ("width", "height", "fps", "aspect")},
        "scenes": scenes,
    })
    pending_images = [scene["id"] for scene in scenes if not scene["image"] or scene["qc"]["image"] == "redo"]
    pending_clips = [scene["id"] for scene in scenes if not scene["clip"] or scene["qc"]["clip"] == "redo"]
    if not scenes:
        detail["next_step"] = "เพิ่มฉากใน project.json"
    elif pending_images:
        detail["next_step"] = "สร้างหรือตรวจภาพฉาก " + ", ".join(pending_images)
    elif pending_clips:
        detail["next_step"] = "สร้างหรือตรวจคลิปฉาก " + ", ".join(pending_clips)
    elif detail["final"]:
        detail["next_step"] = "Final พร้อมใช้งาน"
    elif not detail["draft"]:
        detail["next_step"] = "ตัดต่อคลิปเพื่อสร้าง draft"
    elif detail["voice_count"] < detail["voice_total"]:
        detail["next_step"] = "สร้างเสียงพากย์ที่ยังขาด"
    elif not detail["music"]:
        detail["next_step"] = "สร้างหรือเพิ่มเพลงประกอบ"
    else:
        detail["next_step"] = "ผสมเสียงเพื่อสร้าง final"
    return detail


def media_file(root: Path, slug: str, kind: str, scene_id: str | None = None) -> Path | None:
    directory = project_dir(root, slug)
    if directory is None:
        return None
    if kind == "final":
        candidate = directory / "08-final" / "final.mp4"
    elif kind == "subs":
        candidate = directory / "08-final" / "final-subs.mp4"
    elif kind == "cover":
        candidate = directory / "03-images" / "contact-sheet.jpg"
        if not candidate.is_file():
            data = _read_project(directory)
            candidate = next((image for scene in data["scenes"]
                              if (image := _asset(directory, "image", str(scene.get("id", ""))))), None)
    elif kind in ("scene", "clip") and scene_id is not None:
        data = _read_project(directory)
        if scene_id not in {str(scene.get("id", "")) for scene in data["scenes"]}:
            return None
        candidate = _asset(directory, "image" if kind == "scene" else "clip", scene_id)
    else:
        return None
    return candidate if candidate and candidate.is_file() and candidate.resolve().is_relative_to(directory) else None


def make_handler(root: Path):
    from flow_studio import FlowStudio
    studio = FlowStudio(root)
    class DashboardHandler(BaseHTTPRequestHandler):
        def _json(self, value, status: int = 200, head_only: bool = False) -> None:
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def _file(self, path: Path, head_only: bool = False) -> None:
            size = path.stat().st_size
            start, end, partial = 0, size - 1, False
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or not any(match.groups()):
                    return self._range_error(size)
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
                if start >= size or end < start:
                    return self._range_error(size)
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head_only:
                return
            try:
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _range_error(self, size: int) -> None:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _route(self, head_only: bool = False) -> None:
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host", "").lower() not in allowed_hosts:
                return self._json({"error": "Host ไม่ถูกต้อง"}, 403, head_only)
            path = urlsplit(self.path).path
            if path in STATIC:
                return self._file(WEB_DIR / STATIC[path], head_only)
            parts = [unquote(part) for part in path.strip("/").split("/")]
            if parts == ["api", "projects"]:
                return self._json(list_projects(root), head_only=head_only)
            if parts == ['api', 'flow', 'status']:
                return self._json(studio.status(), head_only=head_only)
            if len(parts) == 3 and parts[:2] == ["api", "projects"]:
                try:
                    detail = project_detail(root, parts[2])
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self._json({"error": str(error)}, 422, head_only)
                return self._json(detail, head_only=head_only) if detail else self._json({"error": "ไม่พบโปรเจกต์"}, 404, head_only)
            if parts[0] == "media" and ((len(parts) == 3 and parts[2] in ("cover", "final", "subs"))
                                         or (len(parts) == 4 and parts[2] in ("scene", "clip"))):
                try:
                    candidate = media_file(root, parts[1], parts[2], parts[3] if len(parts) == 4 else None)
                except (OSError, ValueError, json.JSONDecodeError):
                    candidate = None
                if candidate:
                    return self._file(candidate, head_only)
            self._json({"error": "ไม่พบข้อมูล"}, 404, head_only)

        def do_GET(self) -> None:
            self._route()

        def do_HEAD(self) -> None:
            self._route(head_only=True)

        def do_POST(self) -> None:
            host = self.headers.get('Host', '').lower()
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if host not in hosts or self.headers.get('Origin') != f'http://{host}':
                return self._json({'error': 'Origin ไม่ถูกต้อง'}, 403)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self._json({'error': 'ต้องเป็น application/json'}, 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2 * 1024 * 1024:
                    return self._json({'error': 'ไฟล์ต้องไม่เกิน 2 MB'}, 413)
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('ข้อมูลต้องเป็น JSON object')
                parts = urlsplit(self.path).path.strip('/').split('/')
                if len(parts) != 3 or parts[:2] != ['api', 'flow']:
                    return self._json({'error': 'ไม่พบคำสั่ง'}, 404)
                result = studio.action(parts[2], data)
                return self._json(result)
            except (ValueError, SystemExit) as error:
                return self._json({'error': str(error)}, 422)
            except Exception:
                # Playwright exceptions can include supplied cookie values.
                return self._json({'error': 'เชื่อมต่อ Flow ไม่สำเร็จ ตรวจหน้าต่าง Chrome แล้วลองใหม่'}, 500)

    return DashboardHandler


def serve(root: Path, port: int = 8765, open_browser: bool = True) -> None:
    if not 1 <= port <= 65535:
        raise SystemExit("ani: --port ต้องอยู่ระหว่าง 1 ถึง 65535")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Path(root)))
    except OSError as error:
        raise SystemExit(f"ani: เปิด UI ที่พอร์ต {port} ไม่ได้ — {error}") from error
    server.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"[ui] เปิด {url} (Ctrl+C เพื่อหยุด)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
