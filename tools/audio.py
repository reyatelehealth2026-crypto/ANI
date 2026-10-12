"""Audio stages: TTS (edge / elevenlabs / file) and music (synth / file).

synth = port of moonpetal-guardian/07-audio/make_music.py with mood sections parametrized by (t0, dur).
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

import ani
import media


# ---------------------------------------------------------------- TTS providers
RETRY_DELAY = 2.0


def _retry(fn, attempts: int = 4, delay: float | None = None):
    """edge-tts returns NoAudioReceived at random for fresh text; a short backoff fixes it."""
    import time
    delay = RETRY_DELAY if delay is None else delay
    for i in range(attempts):
        try:
            return fn()
        except SystemExit:
            raise
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(delay * (i + 1))


def tts_edge(text: str, voice: str, out: Path, cfg: dict) -> Path:
    import asyncio
    import edge_tts
    tmp = out.with_name(f".{out.name}.tmp")

    async def go():
        await edge_tts.Communicate(text, voice, rate=cfg.get("rate", "+0%"), pitch=cfg.get("pitch", "+0Hz")).save(str(tmp))

    _retry(lambda: asyncio.run(go()))
    tmp.replace(out)
    return out


def tts_elevenlabs(text: str, voice: str, out: Path, cfg: dict) -> Path:
    import gen
    key = gen.need_key("ELEVENLABS_API_KEY")

    def call():
        try:
            return gen.http_bytes(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                headers={"xi-api-key": key}, body={"text": text, "model_id": cfg.get("model", "eleven_multilingual_v2")}, timeout=120)
        except SystemExit as e:  # HTTP error on one line → retryable, and tts() keeps going with the other lines
            raise RuntimeError(str(e))

    data = _retry(call)
    tmp = out.with_name(f".{out.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


def tts_file(text: str, voice: str, out: Path, cfg: dict) -> Path:
    if out.exists():
        return out
    raise SystemExit(f"ani: providers.tts=file แต่ไม่พบ {out} — วางไฟล์เสียงชื่อนี้ก่อน")


TTS_PROVIDERS = {"edge": tts_edge, "elevenlabs": tts_elevenlabs, "file": tts_file}


def tts(project_dir: Path, project: dict, force: bool = False) -> list[Path]:
    name = project["providers"]["tts"]
    fn = TTS_PROVIDERS.get(name)
    if not fn:
        raise SystemExit(f"ani: providers.tts '{name}' ไม่รู้จัก — เลือกจาก {', '.join(TTS_PROVIDERS)}")
    cfg = {**project["tts"], **project["provider_config"].get(name, {})}
    (project_dir / "07-audio" / "vo").mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for ev in ani.vo_events(project):
        out = project_dir / ev["file"]
        voice = project["voices"].get(ev["speaker"]) or project["voices"].get("narrator")
        if not voice and name != "file":
            raise SystemExit("ani: ไม่มี voices.narrator ใน project.json")
        # provider "file" = user-supplied audio, nothing to regenerate from the text
        if out.exists() and not force and (name == "file" or not ani.is_stale(
                project_dir, f"vo:{ev['file']}", out, [name, ev["text"], voice, project["tts"]])):
            done.append(out)
            continue
        try:
            fn(ev["text"], voice, out, cfg)
            done.append(out)
            print(f"[vo] {ev['file']} ({ev['speaker']} @ {ev['at']}s) {ev['text'][:40]}")
        except SystemExit:
            raise
        except Exception as ex:  # network hiccup on one line must not kill the rest
            failed.append((ev["file"], f"{type(ex).__name__}: {ex}"))
            print(f"[vo] ล้มเหลว {ev['file']}: {type(ex).__name__}: {ex}")
    if failed:
        print(f"[vo] ล้มเหลว {len(failed)} บรรทัด — รัน `vo` ซ้ำ (ไฟล์ที่สำเร็จแล้วจะถูกข้าม)")
    else:
        print(f"[vo] ครบ {len(done)} บรรทัด ({name})")
    return done


# ---------------------------------------------------------------- music synth
class _Synth:
    """Stereo additive/subtractive synth. Times in seconds; sections add into L/R buffers."""

    def __init__(self, total: float, seed: int = 7, sr: int = 44100):
        self.sr, self.n = sr, int(sr * total)
        self.rng = np.random.default_rng(seed)
        self.L, self.R = np.zeros(self.n), np.zeros(self.n)

    @staticmethod
    def hz(m: float) -> float:
        return 440.0 * 2 ** ((m - 69) / 12)

    def env(self, n: int, a: float, r: float, sus: float = 1.0) -> np.ndarray:
        e = np.ones(n) * sus
        na, nr = min(int(a * self.sr), n), 0
        nr = min(int(r * self.sr), n - na)
        if na:
            e[:na] = np.linspace(0, sus, na)
        if nr:
            e[n - nr:] = np.linspace(sus, 0, nr)
        return e

    def lp(self, x: np.ndarray, fc: float, order: int = 2) -> np.ndarray:
        fc = min(fc, 0.45 * self.sr)
        return sosfilt(butter(order, fc / (self.sr / 2), "low", output="sos"), x)

    def add(self, sig: np.ndarray, t0: float, gain: float = 1.0, pan: float = 0.0) -> None:
        i = int(t0 * self.sr)
        if i >= self.n or i < 0:
            return
        j = min(self.n, i + len(sig))
        s = sig[: j - i] * gain
        self.L[i:j] += s * math.sqrt(0.5 * (1 - pan))
        self.R[i:j] += s * math.sqrt(0.5 * (1 + pan))

    def saw_pad(self, midis, dur, cutoff=1200, a=1.5, r=1.5, detune=0.12) -> np.ndarray:
        n = int(dur * self.sr)
        t = np.arange(n) / self.sr
        out = np.zeros(n)
        for m in midis:
            for d in (-detune, 0, detune):
                f = self.hz(m + d)
                for k in range(1, 12):  # band-limited saw
                    if f * k > 8000:
                        break
                    out += np.sin(2 * np.pi * f * k * t + self.rng.uniform(0, 6.28)) / k
        return self.lp(out, cutoff) * self.env(n, a, r) / (len(midis) * 3 * 2.2)

    def bell(self, m, dur=2.5) -> np.ndarray:
        n = int(dur * self.sr)
        t = np.arange(n) / self.sr
        f = self.hz(m)
        s = sum(a * np.sin(2 * np.pi * f * p * t) * np.exp(-t * d)
                for p, a, d in [(1, 1, 2.2), (2.76, .35, 3.5), (5.4, .18, 6), (8.93, .08, 9)])
        return s * self.env(n, 0.003, 0.2)

    def boom(self, dur=2.5) -> np.ndarray:
        n = int(dur * self.sr)
        t = np.arange(n) / self.sr
        f = 38 + 60 * np.exp(-t * 7)
        s = np.sin(2 * np.pi * np.cumsum(f) / self.sr) * np.exp(-t * 2.2)
        click = self.lp(self.rng.standard_normal(n), 2500) * np.exp(-t * 40) * 0.5
        return s + click

    def noise_swell(self, dur, f0, f1, curve=2.0) -> np.ndarray:
        n = int(dur * self.sr)
        out, x, seg = np.zeros(n), self.rng.standard_normal(n), self.sr // 10
        for i in range(0, n, seg):
            p = i / n
            out[i:i + seg] = self.lp(x[i:i + seg], f0 + (f1 - f0) * p ** curve)
        return out * np.linspace(0, 1, n) ** curve

    # -- moods: (t0 = section start, dur = section length); inner times are relative to t0
    def calm(self, t0: float, dur: float) -> None:
        self.add(self.saw_pad([50, 57, 62, 64, 65], dur + 1.0, cutoff=900, a=2.0, r=1.5), t0, 0.55)  # Dm(add9)
        notes, i = [74, 77, 81, 76, 74, 79, 81, 76], 0
        while 0.8 + i * 0.8 < dur - 0.5:
            self.add(self.bell(notes[i % 8]), t0 + 0.8 + i * 0.8, 0.16, pan=-0.4 + 0.1 * (i % 8))
            i += 1

    def threat(self, t0: float, dur: float) -> None:
        self.add(self.saw_pad([38, 45], dur + 0.8, cutoff=300, a=1.5, r=1.2), max(0.0, t0 - 0.3), 0.38)  # low D drone
        self.add(self.saw_pad([58, 62, 65], dur + 0.3, cutoff=600, a=1.0, r=1.0), t0, 0.35)  # Bb
        if dur > 3:
            self.add(self.saw_pad([69, 70], dur - 2.3, cutoff=1800, a=2.5, r=1.5, detune=0.3), t0 + 2.5, 0.12, pan=0.5)
        k = 0
        while 0.9 + k * 1.1 + 0.25 < dur:  # heartbeat
            b = self.lp(self.boom(1.0), 150)
            self.add(b, t0 + 0.9 + k * 1.1, 0.22)
            self.add(b, t0 + 1.15 + k * 1.1, 0.14)
            k += 1

    def resolve(self, t0: float, dur: float) -> None:
        chords = [[50, 57, 62, 65], [46, 53, 58, 62], [48, 55, 60, 64], [50, 57, 62, 65, 69]]
        j = 0
        while j * 1.9 < dur - 0.5:
            rt = j * 1.9
            self.add(self.saw_pad(chords[j % 4], 2.2, cutoff=900 + rt * 250, a=0.4, r=0.5), t0 + rt, 0.5 + rt * 0.06)
            j += 1
        for i in range(int(dur / 0.25)):  # 8th-note pulse (growth capped at 30 pulses = original 7.5 s)
            ii = min(i, 30)
            p = self.saw_pad([[62, 69, 62, 67][i % 4]], 0.22, cutoff=1500 + ii * 80, a=0.005, r=0.12, detune=0.05)
            self.add(p, t0 + i * 0.25, 0.16 + 0.016 * ii, pan=(-0.3 if i % 2 else 0.3))
        rl = min(4.0, dur)
        self.add(self.noise_swell(rl, 400, 9000), t0 + dur - rl, 0.10)  # riser into next section

    def climax(self, t0: float, dur: float) -> None:
        self.add(self.boom(3.0), t0, 0.9)
        self.add(self.noise_swell(1.2, 9000, 9000, curve=0.3)[::-1], t0, 0.10)  # crash tail
        chords = [[46, 58, 62, 65, 70], [48, 60, 64, 67, 72], [50, 62, 65, 69, 74], [50, 62, 66, 69, 74]]
        j = 0
        while j * 1.9 < dur - 0.5:
            self.add(self.saw_pad(chords[j % 4], 2.1, cutoff=3200, a=0.08, r=0.6), t0 + j * 1.9, 0.55)
            if j:
                self.add(self.lp(self.boom(1.5), 200), t0 + j * 1.9, 0.45)
            j += 1
        arp = [74, 77, 81, 86, 81, 77]
        for i in range(int(max(0.0, dur - 0.1) / 0.125)):  # fast shimmer arp
            rt = i * 0.125
            m = arp[i % 6] + (0 if rt < dur - 1.8 else [0, 1, 0, 0, 0, 1][i % 6])
            self.add(self.bell(m, 0.8), t0 + rt, 0.07, pan=math.sin(i * 0.7) * 0.6)

    def resolution(self, t0: float, dur: float) -> None:
        self.add(self.saw_pad([50, 57, 62, 66, 69, 76], dur, cutoff=1400, a=1.2, r=min(3.5, dur / 2)), t0, 0.55)  # Dmaj9
        notes, i = [78, 81, 86, 85, 81, 78, 76, 74], 0
        while 0.4 + i * 0.85 < dur - 0.3:
            self.add(self.bell(notes[i % 8], 3.0), t0 + 0.4 + i * 0.85, 0.14, pan=0.4 - 0.1 * (i % 8))
            i += 1

    def master(self, fade: float = 2.5) -> np.ndarray:
        sr, N = self.sr, self.n
        ir_n = int(2.6 * sr)
        t = np.arange(ir_n) / sr
        ir = [self.lp(self.rng.standard_normal(ir_n) * np.exp(-t * 2.4), 5000) for _ in range(2)]
        ir = [x / (np.abs(x).sum() ** 0.5 * 20) for x in ir]
        L2 = self.L * 0.75 + fftconvolve(self.L, ir[0])[:N] * 0.9
        R2 = self.R * 0.75 + fftconvolve(self.R, ir[1])[:N] * 0.9
        fo = int(min(fade, N / sr / 4) * sr)
        if fo > 0:
            f = np.ones(N)
            f[-fo:] = np.linspace(1, 0, fo) ** 1.5
            L2, R2 = L2 * f, R2 * f
        peak = max(np.abs(L2).max(), np.abs(R2).max()) or 1.0
        L2, R2 = L2 / peak * 0.89, R2 / peak * 0.89
        return (np.stack([L2, R2], 1) * 32767).astype(np.int16)


def synth_music(sections: list[tuple[str, float, float]], total: float, out: Path, seed: int = 7, sr: int = 44100) -> Path:
    s = _Synth(total, seed, sr)
    for mood, t0, t1 in sections:
        if t1 - t0 >= 0.5:
            (getattr(s, mood, None) or s.calm)(float(t0), float(t1 - t0))
    pcm = s.master()
    tmp = out.with_name(f".{out.name}.tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    tmp.replace(out)
    return out


def music_file_cmd(src: Path, tmp: Path, total: float, project_dir: Path) -> list[str]:
    """ffmpeg args for music=file. `-i` takes the absolute source path (relpath breaks across drives)."""
    return ["ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-af", f"apad,atrim=0:{total},afade=t=out:st={max(0.0, total - 2.5):.3f}:d=2.5",
            "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", media.rel(tmp, project_dir)]


def music(project_dir: Path, project: dict, force: bool = False) -> Path:
    out = project_dir / "07-audio" / "music.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    inputs = [project["providers"]["music"], project["music"], ani.music_sections(project)]
    if out.exists() and not force and not ani.is_stale(project_dir, "music", out, inputs):
        print(f"[music] มี {media.rel(out, project_dir)} แล้ว (ใช้ --force เพื่อสร้างใหม่)")
        return out
    total = ani.total_seconds(project)
    m, src = project["music"], project["music"].get("file")
    if project["providers"]["music"] == "file" or src:
        if not src:
            raise SystemExit("ani: providers.music=file ต้องตั้ง music.file เป็น path ไฟล์เพลง (wav/mp3)")
        p = Path(src) if Path(src).is_absolute() else project_dir / src
        if not p.exists():
            raise SystemExit(f"ani: ไม่พบไฟล์เพลง {p}")
        tmp = out.with_name(".music.tmp.wav")
        cmd = music_file_cmd(p, tmp, total, project_dir)
        cmd[0] = media._bin("ffmpeg")
        media.run(cmd, project_dir)
        tmp.replace(out)
        print(f"[music] {media.rel(out, project_dir)} จากไฟล์ {src} ({total:.1f}s)")
        return out
    sections = ani.music_sections(project)
    synth_music(sections, total, out, seed=int(m.get("seed", 7)))
    print(f"[music] {media.rel(out, project_dir)} synth {total:.1f}s: " + " → ".join(f"{mo} {t0:g}-{t1:g}" for mo, t0, t1 in sections))
    return out
