"""ffmpeg / Pillow stages: contact sheet, frame grid, assemble (xfade), mix (2-pass loudness), subtitles.

All ffmpeg calls: subprocess list-args, cwd = project dir, relative paths (no drive-letter escaping in filters).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import ani


# ---------------------------------------------------------------- helpers
def _bin(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise SystemExit(f"ani: ไม่พบ {name} บน PATH — ติดตั้งด้วย `winget install Gyan.FFmpeg` แล้วเปิด shell ใหม่")
    return p


def rel(path: Path, base: Path) -> str:
    return os.path.relpath(path, base).replace("\\", "/")


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = "\n".join(r.stderr.splitlines()[-40:])
        raise SystemExit(f"ani: ffmpeg ล้มเหลว (exit {r.returncode})\ncmd: {' '.join(cmd)}\n{tail}")
    return r


def probe(path: Path) -> dict:
    r = subprocess.run([_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"ani: ffprobe อ่าน {path} ไม่ได้ — {r.stderr.strip()[:200]}")
    return json.loads(r.stdout or "{}")


def probe_duration(path: Path) -> float:
    return float(probe(path).get("format", {}).get("duration") or 0.0)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


def _finish(tmp: Path, out: Path) -> Path:
    tmp.replace(out)
    return out


# ---------------------------------------------------------------- QC images
def _label(im, text: str, size: int = 28):
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=size)
    d.rectangle([0, 0, 18 + size * len(text) * 0.6, size + 12], fill=(16, 16, 24))
    d.text((8, 4), text, fill=(255, 255, 255), font=font)


def contact_sheet(project_dir: Path, project: dict, height: int = 800, gap: int = 12) -> Path:
    from PIL import Image
    tiles = []
    for s in project["scenes"]:
        p = ani.find_asset(project_dir, "image", s["id"])
        if not p:
            print(f"[contact] ข้าม {s['id']}: ยังไม่มีภาพ")
            continue
        im = Image.open(p).convert("RGB")
        im = im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
        _label(im, s["id"])
        tiles.append(im)
    if not tiles:
        raise SystemExit("ani: ไม่มีภาพฉากเลย — รัน `images` ก่อน")
    sheet = Image.new("RGB", (sum(t.width for t in tiles) + gap * (len(tiles) + 1), height + 2 * gap), (16, 16, 24))
    x = gap
    for t in tiles:
        sheet.paste(t, (x, gap))
        x += t.width + gap
    out = project_dir / "03-images" / "contact-sheet.jpg"
    sheet.save(out, quality=85)
    print(f"[contact] {rel(out, project_dir)} ({len(tiles)} ฉาก) — ดูภาพนี้ภาพเดียวเพื่อ QC")
    return out


def frames(project_dir: Path, project: dict, scenes: list[str] | None = None, width: int = 360) -> Path:
    from PIL import Image
    ffmpeg = _bin("ffmpeg")
    fdir = project_dir / "06-draft" / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in project["scenes"]:
        if scenes and s["id"] not in scenes:
            continue
        clip = ani.find_asset(project_dir, "clip", s["id"])
        if not clip:
            print(f"[frames] ข้าม {s['id']}: ยังไม่มีคลิป")
            continue
        dur = probe_duration(clip)
        row = []
        for k, t in enumerate((min(1.0, dur / 4), dur / 2, max(0.0, dur - 1.0)), 1):
            out = fdir / f"s{s['id']}_t{k}.jpg"
            run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", rel(clip, project_dir), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", "-q:v", "3", rel(out, project_dir)], project_dir)
            row.append(out)
        rows.append((s["id"], row))
    if not rows:
        raise SystemExit("ani: ไม่มีคลิปเลย — รัน `clips` / `collect clips` ก่อน")
    first = Image.open(rows[0][1][0])
    tw, th, gap = first.width, first.height, 8
    grid = Image.new("RGB", (3 * tw + 4 * gap, len(rows) * (th + gap) + gap), (16, 16, 24))
    for r, (sid, row) in enumerate(rows):
        for c, p in enumerate(row):
            im = Image.open(p).convert("RGB")
            if c == 0:
                _label(im, sid, 24)
            grid.paste(im, (gap + c * (tw + gap), gap + r * (th + gap)))
    out = project_dir / "06-draft" / "frames-grid.jpg"
    grid.save(out, quality=85)
    print(f"[frames] {rel(out, project_dir)} ({len(rows)} คลิป × 3 เฟรม) — ดูภาพนี้ภาพเดียวเพื่อ QC คลิป")
    return out


# ---------------------------------------------------------------- assemble
def build_xfade_graph(clips: list[dict], w: int, h: int, fps: int, xfade: float, fade_out: float) -> tuple[str, str, str, float]:
    """clips: [{seconds, v_in, a_in}] → (filter_complex, video_label, audio_label, total_seconds). Pure."""
    parts = []
    for i, c in enumerate(clips):
        S = c["seconds"]
        parts.append(f"[{c['v_in']}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},"
                     f"setsar=1,trim=0:{S},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[{c['a_in']}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"atrim=0:{S},asetpts=PTS-STARTPTS[a{i}]")
    if len(clips) == 1:
        v, a, total = "v0", "a0", float(clips[0]["seconds"])
    elif xfade <= 0:
        parts.append("".join(f"[v{i}][a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=1[vc][ac]")
        v, a, total = "vc", "ac", float(sum(c["seconds"] for c in clips))
    else:
        v, a, elapsed = "v0", "a0", float(clips[0]["seconds"])
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


def assemble(project_dir: Path, project: dict) -> Path:
    ffmpeg = _bin("ffmpeg")
    vid, edit = project["video"], project["edit"]
    inputs, clips, n_in = [], [], 0
    for s in project["scenes"]:
        clip = ani.find_asset(project_dir, "clip", s["id"])
        if not clip:
            raise SystemExit(f"ani: ไม่มีคลิปฉาก {s['id']} — รัน `clips` หรือ `collect clips --yes` ก่อน")
        S, dur = float(s["seconds"]), probe_duration(clip)
        if dur + 0.05 < S:
            print(f"[assemble] warning: {clip.name} ยาว {dur:.2f}s < seconds {S} → ใช้ {dur:.2f}s (แก้ seconds ใน project.json ให้ตรง)")
            S = round(dur, 3)
        inputs += ["-i", rel(clip, project_dir)]
        v_in, n_in = n_in, n_in + 1
        a_in = v_in
        if not has_audio(clip):
            inputs += ["-f", "lavfi", "-t", f"{S}", "-i", "anullsrc=r=48000:cl=stereo"]
            a_in, n_in = n_in, n_in + 1
        clips.append({"seconds": S, "v_in": v_in, "a_in": a_in})
    graph, vmap, amap, total = build_xfade_graph(clips, vid["width"], vid["height"], vid["fps"],
                                                float(edit["xfade"]), float(edit["fade_out"]))
    out = project_dir / "06-draft" / "draft.mp4"
    tmp = out.with_name(".draft.tmp.mp4")
    run([ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", vmap, "-map", amap,
         "-c:v", "libx264", "-crf", str(edit["crf"]), "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{total:.3f}",
         rel(tmp, project_dir)], project_dir)
    print(f"[assemble] {rel(out, project_dir)} {total:.1f}s ({len(clips)} คลิป, xfade {edit['xfade']}s)")
    return _finish(tmp, out)


# ---------------------------------------------------------------- mix
def parse_loudnorm(stderr: str) -> dict:
    """Pull the JSON block loudnorm prints to stderr (ffmpeg appends progress lines after it)."""
    a, b = stderr.rfind("{"), stderr.rfind("}")
    try:
        d = json.loads(stderr[a:b + 1])
        return {"i": float(d["input_i"]), "tp": float(d["input_tp"]), "lra": float(d["input_lra"])}
    except (ValueError, KeyError):
        raise SystemExit(f"ani: วัด loudness ไม่ได้\n{stderr[-400:]}")


def measure_loudness(path: Path, cwd: Path, lufs: float, tp: float) -> dict:
    r = subprocess.run([_bin("ffmpeg"), "-hide_banner", "-nostats", "-i", rel(path, cwd), "-af",
                        f"loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
                       cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return parse_loudnorm(r.stderr)


def _mix_graph(project: dict, n_amb: int | None, n_mus: int | None, vo_inputs: list[tuple[int, float]], total: float) -> str:
    """Build the pass-1 filter graph. vo_inputs: [(input_index, at_seconds)]."""
    e = project["edit"]
    parts = [f"[{n_amb}:a]volume={e['clip_audio']}[amb]"]
    if n_mus is not None:
        parts.append(f"[{n_mus}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={project['music']['gain']}[mus]")
    labels = []
    for idx, at in vo_inputs:
        ms = int(round(at * 1000))
        parts.append(f"[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay={ms}|{ms}[d{idx}]")
        labels.append(f"[d{idx}]")
    bus = ["[amb]"]
    if labels:
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,volume={e['vo_gain']},apad=whole_dur={total}[vo]")
        if n_mus is not None:
            parts.append("[vo]asplit=2[vo_sc][vo_out]")
            parts.append(f"[mus][vo_sc]sidechaincompress=threshold={e['duck_threshold']}:ratio={e['duck_ratio']}"
                         f":attack=20:release=400[musd]")
            bus += ["[musd]", "[vo_out]"]
        else:
            bus.append("[vo]")
    elif n_mus is not None:
        bus.append("[mus]")
    if len(bus) == 1:
        parts.append(f"{bus[0]}anull[out]")
    else:
        parts.append(f"{''.join(bus)}amix=inputs={len(bus)}:normalize=0:dropout_transition=0[out]")
    return ";".join(parts)


def mix(project_dir: Path, project: dict) -> Path:
    ffmpeg = _bin("ffmpeg")
    e = project["edit"]
    draft = project_dir / "06-draft" / "draft.mp4"
    if not draft.exists():
        raise SystemExit("ani: ไม่มี 06-draft/draft.mp4 — รัน `assemble` ก่อน")
    total = probe_duration(draft)
    inputs, n = ["-i", rel(draft, project_dir)], 1
    if has_audio(draft):
        n_amb = 0
    else:
        inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        n_amb, n = n, n + 1
    music = project_dir / "07-audio" / "music.wav"
    n_mus = None
    if music.exists():
        inputs += ["-i", rel(music, project_dir)]
        n_mus, n = n, n + 1
    else:
        print("[mix] ไม่มี 07-audio/music.wav → mix โดยไม่มีดนตรี (รัน `music` ถ้าต้องการ)")
    vo_inputs = []
    for ev in ani.vo_events(project):
        f = project_dir / ev["file"]
        if not f.exists():
            print(f"[mix] warning: ไม่มี {ev['file']} → ข้าม (รัน `vo`)")
            continue
        inputs += ["-i", rel(f, project_dir)]
        vo_inputs.append((n, ev["at"]))
        n += 1
    final_dir = project_dir / "08-final"
    final_dir.mkdir(exist_ok=True)
    tmpwav = final_dir / "_mix.wav"
    run([ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", _mix_graph(project, n_amb, n_mus, vo_inputs, total),
         "-map", "[out]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", "-ar", "48000", rel(tmpwav, project_dir)], project_dir)
    m = measure_loudness(tmpwav, project_dir, e["lufs"], e["true_peak"])
    gain = 0.0 if not math.isfinite(m["i"]) else float(e["lufs"]) - m["i"]
    if math.isfinite(m["tp"]) and m["tp"] + gain > float(e["true_peak"]) + 6:
        print(f"[mix] warning: limiter ทำงานหนัก (peak หลัง gain ≈ {m['tp'] + gain:.1f} dBTP) — ลด music.gain/clip_audio หรือ vo_gain")
    limit = 10 ** (float(e["true_peak"]) / 20)
    out = final_dir / "final.mp4"
    tmp = final_dir / ".final.tmp.mp4"
    run([ffmpeg, "-y", "-v", "error", "-i", rel(draft, project_dir), "-i", rel(tmpwav, project_dir),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", f"volume={gain:.2f}dB,alimiter=limit={limit:.3f}:attack=5:release=50:level=false",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
         rel(tmp, project_dir)], project_dir)
    tmpwav.unlink(missing_ok=True)
    _finish(tmp, out)
    final = measure_loudness(out, project_dir, e["lufs"], e["true_peak"])
    print(f"[mix] {rel(out, project_dir)} {total:.1f}s | pre {m['i']:.1f} LUFS → gain {gain:+.1f} dB → "
          f"final {final['i']:.1f} LUFS, TP {final['tp']:.1f} dBTP ({len(vo_inputs)} VO, music={'yes' if n_mus is not None else 'no'})")
    return out


# ---------------------------------------------------------------- subtitles
def fmt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def srt_text(items: list[dict]) -> str:
    out = []
    for i, it in enumerate(items, 1):
        out += [str(i), f"{fmt_ts(it['at'])} --> {fmt_ts(it['end'])}", it["text"], ""]
    return "\n".join(out)


def dedupe_overlaps(items: list[dict], gap: float = 0.1) -> list[dict]:
    items = [dict(it) for it in items]
    for a, b in zip(items, items[1:]):
        if a["end"] > b["at"] - gap:
            a["end"] = round(max(a["at"] + 0.5, b["at"] - gap), 3)
    return items


def write_srt(project_dir: Path, project: dict) -> Path:
    total = ani.total_seconds(project)
    items = []
    for ev in ani.vo_events(project):
        f = project_dir / ev["file"]
        dur = probe_duration(f) if f.exists() else max(2.0, len(ev["text"]) / 12)
        items.append({"at": ev["at"], "end": round(min(total, ev["at"] + dur), 3), "text": ev["text"]})
    out = project_dir / "07-audio" / "subs.srt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(srt_text(dedupe_overlaps(items)), encoding="utf-8-sig")
    print(f"[subs] {rel(out, project_dir)} ({len(items)} บรรทัด)")
    return out


def sub_style(subs: dict, height: int) -> str:
    """force_style for the subtitles filter. libass lays SRT out in a 384x288 script space, so
    `size`/`margin_v` given in output pixels are scaled by 288/height."""
    k = 288 / height
    return (f"FontName={subs['font']},FontSize={subs['size'] * k:.1f},Outline=2,Shadow=0,"
            f"MarginV={subs['margin_v'] * k:.1f},Alignment=2,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000")


def burn_subs(project_dir: Path, project: dict) -> Path:
    ffmpeg = _bin("ffmpeg")
    sub, final = project_dir / "07-audio" / "subs.srt", project_dir / "08-final" / "final.mp4"
    if not sub.exists():
        write_srt(project_dir, project)
    if not final.exists():
        raise SystemExit("ani: ไม่มี 08-final/final.mp4 — รัน `mix` ก่อน")
    c = project["subs"]
    style = sub_style(c, int(project["video"]["height"]))
    out = project_dir / "08-final" / "final-subs.mp4"
    tmp = out.with_name(".final-subs.tmp.mp4")
    run([ffmpeg, "-y", "-v", "error", "-i", "08-final/final.mp4", "-vf", f"subtitles=07-audio/subs.srt:force_style='{style}'",
         "-c:v", "libx264", "-crf", str(project["edit"]["crf"]), "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", rel(tmp, project_dir)], project_dir)
    print(f"[subs] {rel(out, project_dir)} (burn-in, font {c['font']})")
    return _finish(tmp, out)
