"""Google Flow automation over CDP (Playwright) — generate images/clips and download them straight to the scene path.

Setup, selectors and recovery: .claude/skills/ani-pipeline/flow-playbook.md. One browser controller at a time.
State per scene lives in project.json → scene["flow"][kind] = {status, at, media, credits, file}:
  unknown    written right before the Generate click (credits may be spent, result unknown)
  submitted  Flow accepted the job; `media` identifies it → a rerun finishes it instead of paying again
  downloaded file saved to the scene path
"""
from __future__ import annotations

import atexit
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PENDING = ("unknown", "submitted")
FLOW_HOME = "https://flow.google.com/"
CHROMES = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
           os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"))
_SESSION = None
_SESSION_ERROR = None


def mark_state(scene: dict, kind: str, status: str, **info) -> dict:
    rec = {"status": status, "at": datetime.now().isoformat(timespec="seconds"),
           **{k: v for k, v in info.items() if v is not None}}
    scene.setdefault("flow", {})[kind] = rec
    return rec


def check_pending(scene: dict, kind: str, force: bool = False) -> dict | None:
    """None = free to submit. A pending job with a media id = finish it (no new credits). Pending without id = stop."""
    rec = (scene.get("flow") or {}).get(kind)
    if force or not rec or rec.get("status") not in PENDING:
        return None
    if not rec.get("media"):
        sid = scene.get("id", "reference")
        fix = ("ลบ `reference.flow` ใน project.json แล้วรันซ้ำ" if sid == "reference"
               else f"รันซ้ำด้วย `--force --scene {sid}` (ห้าม --force ทั้งเรื่อง: ฉากอื่นจะถูกสร้างใหม่และเสียเครดิต)")
        raise SystemExit(f"ani: ฉาก {sid} ({kind}) ค้างสถานะ '{rec['status']}' ตั้งแต่ {rec['at']} — "
                         f"อาจกด Generate ไปแล้ว: เปิด Flow ดูกริดก่อน ถ้าไม่มีงานนี้จริง {fix}")
    return rec


def parse_credits(text: str) -> int | None:
    m = re.search(r"(\d[\d,]*)\s*(?:credits?|เครดิต)", text or "", re.I)
    return int(m.group(1).replace(",", "")) if m else None


def new_tile(keys: list, before: set) -> str | None:
    """The one tile key that was not in the grid before submit; >1 unknown tiles → refuse to guess."""
    new = [k for k in keys if k and k not in before]
    if len(new) > 1:
        raise RuntimeError(f"กริดมี tile ใหม่ {len(new)} อัน — ไม่รู้ว่าอันไหนเป็นของงานนี้ (เปิดกริดดูแล้วตั้งชื่อเอง)")
    return new[0] if new else None


def asset_name(sid: str, kind: str) -> str:
    """Unique title for a finished Flow tile — survives reloads and is what the asset pickers search for."""
    who = "reference" if sid == "reference" else f"scene-{sid}"
    return f"{who} {kind} {datetime.now():%m%d-%H%M%S}"


def make(kind: str, prompt: str, out: Path, cfg: dict, page=None, attach=()) -> Path | None:
    """Generate one image/clip in Flow and download it to `out`; returns None when credits need --yes first.
    `attach` = titles of Flow assets to use (reference ingredient for images, Start frame for clips)."""
    scene, save = cfg["scene"], cfg["save"]
    sid = scene.get("id", "reference")
    rec = check_pending(scene, kind, cfg.get("force", False))
    page = page or session(cfg)
    if rec:
        media, cost = rec["media"], rec.get("credits")
        print(f"[flow] {sid}: ทำต่องานที่ส่งไปแล้ว ({media}) — ไม่กด Generate ซ้ำ")
    else:
        cost = page.setup(kind)
        if not (cost == 0 and kind == "image") and not cfg.get("yes"):   # a clip showing 0 = misread price
            print(f"[flow] {sid}: Flow แจ้ง {cost if cost is not None else '?'} เครดิต/{kind} — ยังไม่กด; "
                  "แสดงรายการให้ user ok แล้วรันซ้ำด้วย --yes")
            return None
        page.prepare(kind, prompt, list(attach))
        mark_state(scene, kind, "unknown", credits=cost)
        save()
        media = page.submit()
        mark_state(scene, kind, "submitted", media=media, credits=cost)
        save()
    done = page.wait_done(media, cfg.get("max_wait", 600), asset_name(sid, kind))
    if done != media:                       # finished tile got its title → a failed download can resume
        media = done
        mark_state(scene, kind, "submitted", media=media, credits=cost)
        save()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.part{out.suffix}")    # hidden: never matched as a scene asset
    got = Path(page.download(media, kind, tmp) or tmp)      # Flow may change the extension (.jpg)
    saved = out.with_name(out.stem + got.suffix)
    _keep_old(out)
    got.replace(saved)
    mark_state(scene, kind, "downloaded", media=media, credits=cost, file=saved.name)
    save()
    return saved


def _keep_old(out: Path) -> None:
    """Move the previous take (scene-XX.* any extension) to _old/ — paid takes are never overwritten."""
    for f in out.parent.glob(f"{out.stem}.*"):
        if f.is_file():
            old = f.parent / "_old"
            old.mkdir(exist_ok=True)
            f.replace(old / f"{f.stem}.{int(time.time() * 1000)}{f.suffix}")


# ---------------------------------------------------------------- Flow UI
# Thai labels verified live 2026-09-27. Flow changed its UI → fix here, then flow-playbook.md.
UI = {
    "settings": "ทริกเกอร์การตั้งค่า",            # composer settings popover
    "model": "เลือกกลุ่มผลิตภัณฑ์โมเดล",         # model dropdown inside it
    "mode": {"image": "รูปภาพ", "clip": "วิดีโอ"},
    "frames": "เฟรม",                             # video sub-mode with Start/End frame slots
    "cost": "การสร้างจะใช้",                      # "การสร้างจะใช้ 10 เครดิต" (only while the popover is open)
    "submit": "เริ่มสร้าง",
    "no_credit": "คำเตือนเครดิตไม่เพียงพอ",       # replaces submit when credits are short
    "clear": "ล้างพรอมต์",
    "ingredient": "เพิ่มองค์ประกอบลงในช่องพรอมต์",
    "start": "เริ่ม",
    "search": "ค้นหาเนื้อหา",                     # asset picker search box
    "title": "ข้อความที่แก้ไขได้",                 # tile title field in the detail view
    "back": "ปุ่มย้อนกลับเพื่อไปยังหน้าก่อนหน้า",
    "download": "ดาวน์โหลดสื่อ",
    "original": "ขนาดดั้งเดิม",                   # 1K / 720p original; the other items are paid upscales
}
# tile identity: image tiles carry img[data-media-id]; video tiles only a cover src; pending tiles nothing
TILE_KEYS_JS = """() => [...document.querySelectorAll('flow-tile-container')].map(t => {
  const i = t.querySelector('img'); return i ? (i.dataset.mediaId || i.src.split('?')[0]) : null; })"""
COMPOSER_IMGS_JS = """() => { let n = document.querySelector('[contenteditable=true]');
  while (n && !n.querySelector('button[aria-label="ทริกเกอร์การตั้งค่า"]')) n = n.parentElement;
  return n ? [...n.querySelectorAll('img')].map(i => i.src) : []; }"""
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class FlowPage:
    """One Flow project tab. Real (trusted) CDP clicks only; no global key except Escape."""

    def __init__(self, page, cfg: dict):
        self.p, self.cfg, self.before = page, cfg, set()

    def _button(self, name: str):
        return self.p.get_by_role("button", name=name, exact=True)

    def _radio(self, label: str):
        return self.p.get_by_role("radio", name=re.compile(re.escape(label) + "$"))

    def _tile(self, title: str):
        return self.p.locator("flow-tile-container").filter(
            has=self.p.locator(".footer-title", has_text=re.compile(f"^{re.escape(title)}$")))

    @staticmethod
    def _img_sel(key: str) -> str:
        return f'img[data-media-id="{key}"]' if UUID.match(key) else f'img[src^="{key}"]'

    def _to_grid(self) -> None:
        self.p.keyboard.press("Escape")                     # stray popover/picker of an aborted step
        if self._button(UI["back"]).is_visible():
            self._button(UI["back"]).click()                # detail view: its composer would EDIT that asset
        self._button(UI["settings"]).wait_for()

    def _cost_line(self) -> str:
        """Price text read until two reads 0.5 s apart agree — a value still re-rendering never passes."""
        def read():
            return next((x for x in self.p.locator("body").inner_text().splitlines() if UI["cost"] in x), "")
        last = read()
        for _ in range(10):
            self.p.wait_for_timeout(500)
            now = read()
            if now == last:
                return now
            last = now
        return ""                                           # unreadable → treated as paid

    def setup(self, kind: str) -> int | None:
        """Grid view + mode/frames/aspect/x1/model, every job (Flow may reset them); returns the price shown."""
        p = self.p
        self._to_grid()
        agent = p.locator("button.agent-mode-chip")
        if agent.count() and agent.get_attribute("aria-pressed") == "true":
            agent.click()                                   # Agent mode hides the frame slots
        self._button(UI["settings"]).click()
        self._radio(UI["mode"][kind]).click()
        if kind == "clip":
            self._radio(UI["frames"]).click()
        self._radio(self.cfg["video"]["aspect"]).click()
        p.get_by_role("radio", name="x1", exact=True).click()
        model = self.cfg.get("model" if kind == "clip" else "image_model")
        pick = self._button(UI["model"])
        if model and re.sub(r"arrow_drop_down|volume_up|🍌", "", pick.inner_text()).strip() != model:
            pick.click()
            p.get_by_role("menuitem", name=re.compile(re.escape(model) + "$")).click()
        if not self._radio(UI["mode"][kind]).is_visible():
            self._button(UI["settings"]).click()            # the menu choice closed the popover
        line = self._cost_line()
        p.keyboard.press("Escape")
        self._radio(UI["mode"][kind]).wait_for(state="hidden")
        return parse_credits(line)

    def _pick(self, title: str) -> str | None:
        """Attach the asset titled `title` from the open picker; returns its media id when the grid shows it."""
        box = self.p.locator(".cdk-overlay-container")
        box.get_by_role("textbox", name=UI["search"]).fill(title)
        opt = box.get_by_role("option", name=re.compile(rf"^{re.escape(title)}(\s|$)"))
        for _ in range(20):                                 # search results arrive asynchronously
            if opt.count():
                break
            self.p.wait_for_timeout(500)
        self.p.wait_for_timeout(500)
        if opt.count() != 1:
            raise SystemExit(f"ani: หา asset ชื่อ '{title}' ใน Flow ได้ {opt.count()} รายการ (ต้อง 1) — "
                             "ตั้งชื่อ tile ให้ตรงแล้วรันซ้ำ")
        opt.click()
        tile = self._tile(title).locator("img[data-media-id]")
        return tile.first.get_attribute("data-media-id") if tile.count() else None

    def prepare(self, kind: str, prompt: str, attach: list) -> None:
        if self._button(UI["clear"]).count():
            self._button(UI["clear"]).click()               # leftovers of an aborted run
        ids = []
        for title in attach:
            self._button(UI["start"] if kind == "clip" else UI["ingredient"]).click()
            ids.append(self._pick(title))
        editor = self.p.locator("[contenteditable=true]:visible").first
        editor.fill(prompt)
        if len(editor.inner_text().strip()) < len(prompt.strip()) * 0.95:
            raise RuntimeError("ช่อง prompt ของ Flow รับข้อความไม่ครบ")
        self._check_ready(ids)

    def _check_ready(self, ids: list) -> None:
        """Last look before any state is written: grid composer, our attachments, nothing pending, credits."""
        if self._button(UI["back"]).is_visible():
            raise RuntimeError("อยู่ในหน้า detail ของ asset — ไม่กดสร้าง")
        imgs = self.p.evaluate(COMPOSER_IMGS_JS)
        if any(not any(mid in src for src in imgs) for mid in ids if mid):
            raise RuntimeError("Flow ไม่ได้แนบ asset ที่เลือกไว้ในช่อง prompt")
        if self.p.locator("flow-pending-tile").count():
            raise RuntimeError("มีงานกำลังสร้างค้างในกริด — รอให้เสร็จก่อน ไม่งั้นจับคู่ผลลัพธ์ผิดฉาก")
        if self._button(UI["no_credit"]).count() or not self._button(UI["submit"]).is_visible():
            raise SystemExit("ani: เครดิต Google Flow ไม่พอสำหรับงานนี้ — รอรีเฟรช/อัปเกรด หรือเปลี่ยนบัญชี")

    def submit(self) -> None:
        """Click Generate exactly once (never retried); None — pending tiles carry no id."""
        self.before = set(filter(None, self.p.evaluate(TILE_KEYS_JS)))
        self._button(UI["submit"]).click()
        self.p.locator("flow-pending-tile").first.wait_for(timeout=20000)   # Flow accepted the job
        return None

    def wait_done(self, media: str | None, timeout: float, name: str) -> str:
        """Our job = the one tile that appeared after submit; once finished it is renamed to `name`."""
        if media:
            self._tile(media).first.wait_for(timeout=30000)
            return media
        end, quiet = time.time() + timeout, None
        while time.time() < end:
            key = new_tile(self.p.evaluate(TILE_KEYS_JS), self.before)
            pending = self.p.locator("flow-pending-tile").count()
            if key and not pending:
                self._rename(key, name)
                return name
            if key or pending:
                quiet = None
            elif quiet is None:
                quiet = time.time()
            elif time.time() - quiet > 60:
                raise RuntimeError("Flow ไม่มีผลลัพธ์ 60 s หลังงานหายจากกริด (อาจถูกปฏิเสธ) — เปิดกริดดู error ก่อนรันซ้ำ")
            self.p.wait_for_timeout(3000)
        raise RuntimeError(f"Flow ยังไม่เสร็จใน {timeout:.0f}s — ห้ามกดซ้ำ: รอแล้วเปิดกริดดู")

    def _rename(self, key: str, name: str) -> None:
        self.p.locator(f"flow-tile-container {self._img_sel(key)}").first.click()
        box = self.p.get_by_role("textbox", name=UI["title"])
        box.fill(name)
        box.press("Enter")
        self._button(UI["back"]).click()
        self._tile(name).locator(self._img_sel(key)).first.wait_for(timeout=15000)   # the name sits on OUR tile

    def download(self, media: str, kind: str, out: Path) -> Path:
        p = self.p
        self._tile(media).first.locator("img").first.click()
        self._button(UI["download"]).click()
        with p.expect_download(timeout=120000) as d:
            p.get_by_role("menuitem", name=re.compile(UI["original"])).click()
        dl = d.value
        real = Path(out).with_suffix(Path(dl.suggested_filename).suffix or Path(out).suffix)
        dl.save_as(real)
        self._button(UI["back"]).click()
        return real


# ---------------------------------------------------------------- browser
def _alive(cdp: str) -> bool:
    try:
        with urllib.request.urlopen(cdp.rstrip("/") + "/json/version", timeout=2):
            return True
    except OSError:
        return False


def launch(cfg: dict) -> str:
    """Dedicated Flow Chrome: own profile dir + local debug port → no Allow prompt, never the everyday profiles."""
    cdp = cfg["cdp"]
    if _alive(cdp):
        return cdp
    exe = next((c for c in (cfg.get("chrome"), *CHROMES) if c and Path(c).exists()), None)
    if not exe:
        raise SystemExit("ani: หา chrome.exe ไม่เจอ — ตั้ง provider_config.flow.chrome")
    subprocess.Popen([exe, f"--user-data-dir={Path(cfg['profile_dir']).expanduser()}",
                      f"--remote-debugging-port={urllib.parse.urlparse(cdp).port}", "--no-first-run",
                      "--no-default-browser-check", cfg.get("project_url") or FLOW_HOME],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    for _ in range(60):
        if _alive(cdp):
            return cdp
        time.sleep(0.5)
    raise SystemExit(f"ani: Chrome สำหรับ Flow ไม่ตอบที่ {cdp}")


def _project_page(browser, cfg: dict):
    url = cfg.get("project_url")
    if not url:
        raise SystemExit("ani: ยังไม่ได้ตั้ง provider_config.flow.project_url — เปิดโปรเจคใน Flow แล้วคัดลอก URL มาใส่")
    pages = [pg for c in browser.contexts for pg in c.pages]
    page = next((pg for pg in pages if pg.url.startswith(url)), None)
    if page is None:
        page = next((pg for pg in pages if pg.url.startswith(FLOW_HOME)), None) or browser.contexts[0].new_page()
        page.goto(url, wait_until="domcontentloaded")
    try:
        page.get_by_role("button", name=UI["settings"], exact=True).wait_for(timeout=20000)
    except Exception:
        raise SystemExit("ani: เปิดหน้าโปรเจค Flow ไม่ขึ้น (ยังไม่ login?) — ให้ user sign in ในหน้าต่าง Chrome ของ Flow "
                         f"(profile {cfg['profile_dir']}) แล้วรันซ้ำ") from None
    return page


def session(cfg: dict):
    """One CDP connection per process; exit only disconnects (the Flow window stays open)."""
    global _SESSION, _SESSION_ERROR
    if _SESSION_ERROR:
        raise SystemExit(_SESSION_ERROR)                    # same failure for every remaining scene, no new driver
    if _SESSION is None:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            _SESSION = FlowPage(_project_page(pw.chromium.connect_over_cdp(launch(cfg)), cfg), cfg)
        except BaseException as e:
            pw.stop()
            _SESSION_ERROR = str(e) or type(e).__name__
            raise
        atexit.register(pw.stop)
    return _SESSION
