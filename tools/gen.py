"""Image / video generation providers + collect (ingest files from Downloads).

Provider signatures:
  image: fn(prompt, reference_images: list[Path], out: Path, cfg) -> Path | None
  video: fn(prompt, source_image: Path, out: Path, cfg) -> Path | None
manual / flow providers print the prompt block and return None (files arrive via `collect`).
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import shutil
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ani

GEMINI = "https://generativelanguage.googleapis.com/v1beta"
FAL_QUEUE = "https://queue.fal.run"
OPENAI = "https://api.openai.com/v1"


# ---------------------------------------------------------------- http helpers
def need_key(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"ani: ต้องตั้ง {name} — ใส่ใน env หรือไฟล์ ANI/.env บรรทัด `{name}=...`")
    return v


def http_bytes(url: str, method: str = "POST", headers: dict | None = None, body: dict | None = None,
               raw: bytes | None = None, content_type: str = "application/json", timeout: int = 120) -> bytes:
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    hdrs = dict(headers or {})
    if data is not None:
        hdrs.setdefault("Content-Type", content_type)
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ani: HTTP {e.code} {url}\n{e.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"ani: เชื่อมต่อ {url} ไม่ได้ — {e.reason}")


def http_json(url: str, method: str = "POST", headers: dict | None = None, body: dict | None = None,
              raw: bytes | None = None, content_type: str = "application/json", timeout: int = 120) -> dict:
    return json.loads(http_bytes(url, method, headers, body, raw, content_type, timeout) or b"{}")


def write_atomic(out: Path, data: bytes) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


def download(url: str, out: Path, headers: dict | None = None) -> Path:
    return write_atomic(out, http_bytes(url, "GET", headers, timeout=600))


def b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def mime(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "image/png"


def data_uri(path: Path) -> str:
    return f"data:{mime(path)};base64,{b64(path)}"


def multipart(fields: dict, files: list[tuple[str, Path]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    buf = bytearray()
    for k, v in fields.items():
        buf += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    for k, p in files:
        buf += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{p.name}\"\r\n"
                f"Content-Type: {mime(p)}\r\n\r\n").encode("utf-8") + p.read_bytes() + b"\r\n"
    buf += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


def veo_duration(seconds: float) -> int:
    """Veo accepts 4/6/8 s — round UP so the clip is never shorter than the scene (assemble trims)."""
    return next((d for d in (4, 6, 8) if d >= seconds), 8)


# ---------------------------------------------------------------- image providers
def img_manual(prompt, refs, out, cfg):
    print(f"\n=== {cfg['label']} (image) → วางไฟล์ที่ {cfg['rel_out']} ===\n{prompt}\n")
    return None


def img_gemini(prompt, refs, out, cfg):
    key = need_key("GEMINI_API_KEY")
    model = cfg.get("image_model", "gemini-2.5-flash-image")
    parts = [{"text": prompt}] + [{"inline_data": {"mime_type": mime(r), "data": b64(r)}} for r in refs]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": cfg["video"]["aspect"]}}}
    res = http_json(f"{GEMINI}/models/{model}:generateContent", headers={"x-goog-api-key": key}, body=body, timeout=180)
    for cand in res.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            d = part.get("inlineData") or part.get("inline_data")
            if d and d.get("data"):
                return write_atomic(out, base64.b64decode(d["data"]))
    raise SystemExit(f"ani: gemini ไม่คืนภาพ ({cfg['label']}): {json.dumps(res, ensure_ascii=False)[:300]}")


def _openai_size(aspect: str) -> str:
    return {"9:16": "1024x1536", "16:9": "1536x1024"}.get(aspect, "1024x1024")


def img_openai(prompt, refs, out, cfg):
    key = need_key("OPENAI_API_KEY")
    fields = {"model": cfg.get("image_model", "gpt-image-1"), "prompt": prompt,
              "size": cfg.get("size") or _openai_size(cfg["video"]["aspect"]), "quality": cfg.get("quality", "high")}
    hdr = {"Authorization": f"Bearer {key}"}
    if refs:
        raw, ctype = multipart(fields, [("image[]", r) for r in refs])
        res = http_json(f"{OPENAI}/images/edits", headers=hdr, raw=raw, content_type=ctype, timeout=300)
    else:
        res = http_json(f"{OPENAI}/images/generations", headers=hdr, body={**fields, "n": 1}, timeout=300)
    b = (res.get("data") or [{}])[0].get("b64_json")
    if not b:
        raise SystemExit(f"ani: openai ไม่คืนภาพ ({cfg['label']}): {json.dumps(res)[:300]}")
    return write_atomic(out, base64.b64decode(b))


def fal_run(model: str, body: dict, key: str, timeout: int) -> dict:
    hdr = {"Authorization": f"Key {key}"}
    res = http_json(f"{FAL_QUEUE}/{model}", headers=hdr, body=body, timeout=60)
    t0 = time.time()
    while True:
        st = http_json(res["status_url"], "GET", hdr, timeout=60)
        if st.get("status") == "COMPLETED":
            return http_json(res["response_url"], "GET", hdr, timeout=60)
        if st.get("status") in ("FAILED", "ERROR", "CANCELLED"):
            raise SystemExit(f"ani: fal {model} ล้มเหลว: {json.dumps(st)[:300]}")
        if time.time() - t0 > timeout:
            raise SystemExit(f"ani: fal {model} เกิน {timeout}s — ลองใหม่หรือเช็ค https://fal.ai/dashboard")
        time.sleep(3)


def img_fal(prompt, refs, out, cfg):
    key = need_key("FAL_KEY")
    model = cfg.get("image_edit_model" if refs else "image_model") or "fal-ai/nano-banana-pro"
    body = {"prompt": prompt, "aspect_ratio": cfg["video"]["aspect"], "num_images": 1, **cfg.get("image_params", {})}
    if refs:
        body["image_urls"] = [data_uri(r) for r in refs]  # ponytail: param names are model-specific; override via image_params
    res = fal_run(model, body, key, 300)
    url = (res.get("images") or [{}])[0].get("url") or (res.get("image") or {}).get("url")
    if not url:
        raise SystemExit(f"ani: fal ไม่คืนภาพ ({cfg['label']}): {json.dumps(res)[:300]}")
    return download(url, out)


def img_flow(prompt, refs, out, cfg):
    """Nano Banana in Google Flow (0 credits when checked 2026-09-26) — reference image attached as ingredient."""
    import flow
    ref = [cfg["ref_media"]] if cfg.get("ref_media") else ["reference"] if refs else []   # local ref → Flow tile "reference"
    return flow.make("image", prompt, out, cfg, attach=ref)


IMAGE_PROVIDERS = {"manual": img_manual, "flow": img_flow, "gemini": img_gemini, "openai": img_openai, "fal": img_fal}


# ---------------------------------------------------------------- video providers
def vid_manual(prompt, image, out, cfg):
    print(f"\n=== {cfg['label']} (video) ใช้ภาพ {cfg['rel_image']} → วางไฟล์ที่ {cfg['rel_out']} ===\n{prompt}\n")
    return None


def vid_flow(prompt, image, out, cfg):
    """Google Flow in the user's Chrome over CDP — steps + setup in .claude/skills/ani-pipeline/flow-playbook.md."""
    import flow
    shot = (cfg["scene"].get("flow") or {}).get("image") or {}
    media = shot.get("media") if shot.get("file") == Path(image).name else None   # image replaced since → search
    return flow.make("clip", prompt, out, cfg, attach=[media or f"scene-{cfg['scene']['id']}"])


def vid_gemini(prompt, image, out, cfg):
    key = need_key("GEMINI_API_KEY")
    model = cfg.get("video_model", "veo-3.1-fast-generate-preview")
    v, hdr = cfg["video"], {"x-goog-api-key": key}
    body = {"instances": [{"prompt": prompt, "image": {"bytesBase64Encoded": b64(image), "mimeType": mime(image)}}],
            "parameters": {"aspectRatio": v["aspect"], "resolution": v["resolution"],
                           "durationSeconds": veo_duration(cfg["seconds"]), "personGeneration": "allow_adult"}}
    op = http_json(f"{GEMINI}/models/{model}:predictLongRunning", headers=hdr, body=body, timeout=120)
    name = op.get("name")
    if not name:
        raise SystemExit(f"ani: veo ไม่เริ่มงาน ({cfg['label']}): {json.dumps(op)[:300]}")
    t0 = time.time()
    while not op.get("done"):
        if time.time() - t0 > 600:
            raise SystemExit(f"ani: veo {name} เกิน 10 นาที — ลองใหม่ภายหลัง")
        time.sleep(10)
        op = http_json(f"{GEMINI}/{name}", "GET", hdr, timeout=60)
    if op.get("error"):
        raise SystemExit(f"ani: veo ล้มเหลว ({cfg['label']}): {json.dumps(op['error'])[:300]}")
    try:
        uri = op["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit(f"ani: veo ไม่คืนวิดีโอ ({cfg['label']}): {json.dumps(op)[:300]}")
    return download(uri, out, headers=hdr)


def vid_fal(prompt, image, out, cfg):
    key = need_key("FAL_KEY")
    model = cfg.get("video_model", "fal-ai/veo3.1/fast/image-to-video")
    v = cfg["video"]
    body = {"prompt": prompt, "image_url": data_uri(image), "aspect_ratio": v["aspect"],
            "duration": f"{veo_duration(cfg['seconds'])}s", "resolution": v["resolution"], **cfg.get("video_params", {})}
    res = fal_run(model, body, key, 900)
    url = (res.get("video") or {}).get("url")
    if not url:
        raise SystemExit(f"ani: fal ไม่คืนวิดีโอ ({cfg['label']}): {json.dumps(res)[:300]}")
    return download(url, out)


VIDEO_PROVIDERS = {"manual": vid_manual, "flow": vid_flow, "gemini": vid_gemini, "fal": vid_fal}


# ---------------------------------------------------------------- stage runners
def _cfg(project: dict, name: str, **extra) -> dict:
    cfg = dict(project["provider_config"].get(name, {}))
    if name == 'flow' and (ani.ROOT / '.local' / 'flow.json').exists():
        import flow_auth
        local = flow_auth.settings(ani.ROOT)
        for key in ('cdp', 'profile_dir', 'project_url'):
            if not cfg.get(key) or cfg.get(key) == ani.DEFAULTS['provider_config']['flow'].get(key):
                cfg[key] = local[key]
        if cfg.get('profile_dir') == local['profile_dir']:
            cfg['_cookie_store'] = local['_cookie_store']
            cfg['browser_mode'] = local['browser_mode']
            cfg['cdp'] = local['cdp']
    return {**cfg, "video": project["video"], **extra}


def _run_jobs(fn, jobs: list, parallel: bool) -> list[tuple]:
    """Run fn over jobs → [(job, result, error)]. A failing job never discards its finished siblings."""
    def guarded(j):
        try:
            return j, fn(j), None
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # SystemExit from http helpers included
            return j, None, str(e) or type(e).__name__

    if not parallel or len(jobs) <= 1:
        return [guarded(j) for j in jobs]
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(guarded, jobs))


def _fail_if_errors(stage: str, results: list[tuple]) -> None:
    errors = [(j, e) for j, _, e in results if e is not None]
    if errors:
        lines = "\n".join(f"  - {getattr(j, 'get', lambda k: None)('id') or j}: {e}" for j, e in errors)
        raise SystemExit(f"ani: {stage} ล้มเหลว {len(errors)} งาน (ที่สำเร็จแล้วบันทึกไว้แล้ว — รันซ้ำเพื่อทำเฉพาะที่ขาด)\n{lines}")


def _select(project: dict, scenes: list[str] | None) -> list[dict]:
    return [s for s in project["scenes"] if not scenes or s["id"] in scenes]


def generate_images(project_dir: Path, project: dict, scenes: list[str] | None = None, force: bool = False,
                    yes: bool = False):
    name = project["providers"]["image"]
    fn = IMAGE_PROVIDERS.get(name)
    if not fn:
        raise SystemExit(f"ani: providers.image '{name}' ไม่รู้จัก — เลือกจาก {', '.join(IMAGE_PROVIDERS)}")
    done, missing = [], []
    run = {"save": lambda: ani.save_project(project_dir, project), "yes": yes, "force": force}  # flow: state + credit gate
    ref = ani.reference_path(project_dir, project)
    rprompt = (project.get("reference") or {}).get("prompt")
    if rprompt and (ref is None or force):
        out = project_dir / "02-reference" / "reference.png"
        full = "\n".join(x for x in (rprompt, project["style"], project["characters"]) if x)
        r = fn(full, [], out, _cfg(project, name, label="reference", rel_out="02-reference/reference.png",
                                   scene=project.setdefault("reference", {}), **run))
        if r:
            ref = r
            done.append(r)
            print(f"[images] reference → {r.name}")
        else:
            missing.append("reference")
    refs = [ref] if ref else []
    jobs = [s for s in _select(project, scenes) if ani.scene_needs(project_dir, s, "image", force, project)]

    def one(s):
        out = project_dir / "03-images" / f"scene-{s['id']}.png"
        return fn(ani.image_prompt(project, s), refs, out,
                  _cfg(project, name, label=f"scene {s['id']}", rel_out=f"03-images/scene-{s['id']}.png", scene=s,
                       ref_media=((project.get("reference") or {}).get("flow") or {}).get("image", {}).get("media"), **run))

    results = _run_jobs(one, jobs, parallel=name not in ("manual", "flow"))
    for s, r, err in results:
        if r:
            ani.retire_asset(project_dir, "image", s["id"], keep=r)
            s["qc"]["image"] = ""
            if name != "flow":
                (s.get("flow") or {}).pop("image", None)            # Flow tile no longer = this image
            done.append(r)
            print(f"[images] {s['id']} → {r.name}")
        elif err is None:
            missing.append(s["id"])
    if done:
        ani.save_project(project_dir, project)
    _fail_if_errors("images", results)
    if not jobs and not missing:
        print("[images] ครบทุกฉากแล้ว (ใช้ --force หรือ `mark <id> image=redo` เพื่อทำใหม่)")
    if missing and name == "flow":
        print(f"[images] ยังขาด {len(missing)}: {', '.join(missing)} — ดูบรรทัด [flow] ด้านบน (ติดเครดิต → user ok แล้ว --yes)")
    elif missing:
        print(f"[images] ยังขาด {len(missing)}: {', '.join(missing)} — สร้างภาพตาม prompt ข้างบน แล้วรัน "
              f"`python tools/ani.py collect images --yes` (จาก Downloads) หรือวางไฟล์แล้ว `mark <id> image=pass`")
    return done, missing


def generate_clips(project_dir: Path, project: dict, scenes: list[str] | None = None, force: bool = False,
                   yes: bool = False):
    name = project["providers"]["video"]
    fn = VIDEO_PROVIDERS.get(name)
    if not fn:
        raise SystemExit(f"ani: providers.video '{name}' ไม่รู้จัก — เลือกจาก {', '.join(VIDEO_PROVIDERS)}")
    jobs = []
    for s in _select(project, scenes):
        if not ani.scene_needs(project_dir, s, "clip", force, project):
            continue
        img = ani.find_asset(project_dir, "image", s["id"])
        if not img:
            raise SystemExit(f"ani: ฉาก {s['id']} ยังไม่มีภาพ — รัน `images` ก่อน")
        jobs.append((s, img))

    def one(job):
        s, img = job
        out = project_dir / "05-clips" / f"scene-{s['id']}.mp4"
        return fn(ani.motion_prompt(project, s), img, out,
                  _cfg(project, name, label=f"scene {s['id']}", rel_out=f"05-clips/scene-{s['id']}.mp4",
                       rel_image=f"03-images/{img.name}", seconds=float(s["seconds"]), scene=s,
                       save=lambda: ani.save_project(project_dir, project), yes=yes, force=force))

    done, missing = [], []
    results = _run_jobs(one, jobs, parallel=name not in ("manual", "flow"))
    for (s, _img), r, err in results:
        if r:
            ani.retire_asset(project_dir, "clip", s["id"], keep=r)
            s["qc"]["clip"] = ""
            done.append(r)
            print(f"[clips] {s['id']} → {r.name}")
        elif err is None:
            missing.append(s["id"])
    if done:
        ani.save_project(project_dir, project)
    _fail_if_errors("clips", [(s, r, e) for (s, _i), r, e in results])
    if not jobs and not missing:
        print("[clips] ครบทุกฉากแล้ว (ใช้ --force หรือ `mark <id> clip=redo` เพื่อทำใหม่)")
    if missing:
        hint = ("ดูบรรทัด [flow] ด้านบน (ติดเครดิต → user ok แล้ว --yes)" if name == "flow"
                else "สร้างคลิปตาม prompt ข้างบน แล้วรัน `python tools/ani.py collect clips --yes`")
        print(f"[clips] ยังขาด {len(missing)}: {', '.join(missing)} — {hint}")
    return done, missing


# ---------------------------------------------------------------- collect
KINDS = {"images": ("image", ani.IMAGE_EXT, "03-images"), "clips": ("clip", ani.CLIP_EXT, "05-clips")}


def plan_collect(missing_ids: list[str], candidates: list[Path]) -> dict[str, Path]:
    """Pair missing scene ids (in order) with candidate files (oldest first). Pure."""
    return dict(zip(missing_ids, candidates))


def collect(project_dir: Path, project: dict, kind: str, src_dir: Path, hours: float = 6.0,
            mapping: dict[str, str] | None = None, apply: bool = False) -> list[tuple[str, Path, Path]]:
    if kind not in KINDS:
        raise SystemExit("ani: collect ต้องระบุ images หรือ clips")
    akind, exts, folder = KINDS[kind]
    missing = [s["id"] for s in project["scenes"] if ani.scene_needs(project_dir, s, akind, project=project)]
    if not missing:
        print(f"[collect] {kind} ครบทุกฉากแล้ว — ใช้ `mark <id> {akind}=redo` ถ้าต้องการแทนที่")
        return []
    if mapping:
        known = {s["id"] for s in project["scenes"]}
        bad = sorted(set(mapping) - known)
        if bad:
            raise SystemExit(f"ani: --map มีฉากที่ไม่รู้จัก: {', '.join(bad)} (มี: {', '.join(sorted(known))})")
        plan = {k: Path(v).expanduser() for k, v in mapping.items()}
    else:
        src_dir = Path(src_dir).expanduser()
        if not src_dir.is_dir():
            raise SystemExit(f"ani: ไม่พบโฟลเดอร์ {src_dir} — ใช้ --src DIR")
        cutoff = time.time() - hours * 3600
        cands = sorted((p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in exts
                        and not p.name.startswith(".") and p.stat().st_mtime >= cutoff), key=lambda p: p.stat().st_mtime)
        plan = plan_collect(missing, cands)
        if not plan:
            print(f"[collect] ไม่พบไฟล์ {'/'.join(exts)} ใน {src_dir} ที่ใหม่กว่า {hours:g} ชม. — ใช้ --hours 48 หรือ --map {missing[0]}=path")
            return []
    rows = []
    for sid, src in plan.items():
        if not src.exists():
            raise SystemExit(f"ani: ไม่พบไฟล์ {src}")
        st = src.stat()
        print(f"  scene {sid} ← {src}  ({st.st_size / 1e6:.1f} MB, {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))})")
        rows.append((sid, src, project_dir / folder / f"scene-{sid}{src.suffix.lower()}"))
    left = [m for m in missing if m not in plan]
    if left:
        print(f"  ยังไม่มีไฟล์ให้ฉาก: {', '.join(left)}")
    if not apply:
        print("[collect] dry-run — ถ้า mapping ถูกต้อง รันซ้ำพร้อม --yes เพื่อย้ายไฟล์ (ผิดคู่ → ใช้ --map 03=path)")
        return rows
    (project_dir / folder).mkdir(exist_ok=True)
    log = project_dir / ".collect.log"
    for sid, src, dst in rows:
        ani.retire_asset(project_dir, akind, sid)
        shutil.move(str(src), str(dst))
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{kind}\t{sid}\t{src}\t{dst}\n")
        scene = next(s for s in project["scenes"] if s["id"] == sid)
        scene["qc"][akind] = ""
        (scene.get("flow") or {}).pop(akind, None)                  # collected file supersedes any Flow job
        print(f"[collect] {sid} → {folder}/{dst.name}")
    ani.save_project(project_dir, project)
    return rows
