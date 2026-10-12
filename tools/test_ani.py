"""ANI pipeline tests — run: python tools/test_ani.py  (no ffmpeg/network needed)."""
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
        self.assertEqual(
            ani.music_sections(ani.apply_defaults(moonpetal())),
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
        with self.assertRaises(SystemExit):
            ani.apply_defaults(p)

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

    def test_asset_match_does_not_cross_prefix_ids(self):
        # review HIGH: scene "1" must not see scene-10 / scene-12 files
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / "03-images").mkdir()
            for n in ("scene-1.png", "scene-10.png", "scene-12-image.png"):
                (d / "03-images" / n).write_bytes(b"x")
            os.utime(d / "03-images" / "scene-12-image.png", (time.time() + 9, time.time() + 9))
            self.assertEqual(ani.find_asset(d, "image", "1").name, "scene-1.png")
            self.assertEqual(ani.find_asset(d, "image", "12").name, "scene-12-image.png")
            ani.retire_asset(d, "image", "1")
            self.assertEqual(sorted(p.name for p in (d / "03-images").glob("scene-*")), ["scene-10.png", "scene-12-image.png"])

    def test_parse_map_rejects_bad_entries(self):
        self.assertEqual(ani.parse_map(["03=C:/x.mp4", "04=y.mp4"]), {"03": "C:/x.mp4", "04": "y.mp4"})
        with self.assertRaises(SystemExit):
            ani.parse_map(["bogus"])

import media


class MediaTests(unittest.TestCase):
    def test_xfade_graph_offsets(self):
        clips = [{"seconds": 8.0, "v_in": 0, "a_in": 0}, {"seconds": 8.0, "v_in": 1, "a_in": 3},
                 {"seconds": 8.0, "v_in": 2, "a_in": 2}]
        g, vmap, amap, total = media.build_xfade_graph(clips, 720, 1280, 24, 0.5, 1.0)
        self.assertIn("xfade=transition=fade:duration=0.5:offset=7.5", g)
        self.assertIn("offset=15.0", g)
        self.assertIn("[3:a]aresample", g)
        self.assertIn("fade=t=out:st=22.0:d=1.0", g)
        self.assertEqual((vmap, amap, total), ("[vout]", "[aout]", 23.0))

    def test_xfade_zero_uses_concat(self):
        g, *_ = media.build_xfade_graph(
            [{"seconds": 8, "v_in": 0, "a_in": 0}, {"seconds": 8, "v_in": 1, "a_in": 1}], 720, 1280, 24, 0, 1.0)
        self.assertIn("concat=n=2:v=1:a=1", g)

    def test_srt(self):
        items = [{"at": 0.6, "end": 6.672, "text": "หนึ่ง"}, {"at": 8.0, "end": 12.4, "text": "สอง"}]
        s = media.srt_text(items)
        self.assertTrue(s.startswith("1\n00:00:00,600 --> 00:00:06,672\nหนึ่ง\n\n2\n00:00:08,000"))

    def test_parse_loudnorm_ignores_trailing_ffmpeg_lines(self):
        stderr = ('[Parsed_loudnorm_0 @ 0x1] \n{\n\t"input_i" : "-24.27",\n\t"input_tp" : "-3.10",\n'
                  '\t"input_lra" : "7.60",\n\t"output_i" : "-15.01"\n}\n'
                  '[out#0/null @ 0x2] video:0KiB audio:28500KiB\nsize=N/A time=00:00:38.00 bitrate=N/A speed=33.9x\n')
        m = media.parse_loudnorm(stderr)
        self.assertEqual((m["i"], m["tp"], m["lra"]), (-24.27, -3.10, 7.60))

    def test_sub_style_converts_pixels_to_libass_units(self):
        # libass renders SRT in a 384x288 script space → px must be scaled by 288/height
        style = media.sub_style({"font": "Leelawadee UI", "size": 56, "margin_v": 220}, 1280)
        self.assertIn("FontName=Leelawadee UI", style)
        self.assertIn("FontSize=12.6", style)
        self.assertIn("MarginV=49.5", style)
        self.assertIn("Alignment=2", style)

    def test_srt_no_overlap(self):
        items = media.dedupe_overlaps([{"at": 0.0, "end": 9.0, "text": "a"}, {"at": 8.0, "end": 12.0, "text": "b"}])
        self.assertAlmostEqual(items[0]["end"], 7.9)


import audio


class AudioTests(unittest.TestCase):
    def test_synth_moonpetal(self):
        import wave
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.wav"
            audio.synth_music([("calm", 0, 7.5), ("threat", 7.5, 15), ("resolve", 15, 22.5),
                               ("climax", 22.5, 30), ("resolution", 30, 38)], 38.0, out)
            with wave.open(str(out)) as w:
                self.assertEqual(w.getnchannels(), 2)
                self.assertEqual(w.getframerate(), 44100)
                self.assertAlmostEqual(w.getnframes() / 44100, 38.0, places=2)
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32767
            self.assertAlmostEqual(float(abs(pcm).max()), 0.89, places=1)
            self.assertFalse(np.isnan(pcm).any())

    def test_synth_short_two_sections(self):
        import wave
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m.wav"
            audio.synth_music([("climax", 0, 3), ("calm", 3, 6)], 6.0, out)
            with wave.open(str(out)) as w:
                self.assertAlmostEqual(w.getnframes() / 44100, 6.0, places=2)

    def test_tts_provider_table(self):
        self.assertEqual(set(audio.TTS_PROVIDERS), {"edge", "elevenlabs", "file"})

    def test_retry_recovers_from_transient_failures(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("NoAudioReceived")
            return "ok"

        self.assertEqual(audio._retry(flaky, attempts=4, delay=0), "ok")
        self.assertEqual(len(calls), 3)

    def test_retry_gives_up_after_attempts(self):
        def always():
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            audio._retry(always, attempts=2, delay=0)

    def test_music_file_uses_absolute_input_path(self):
        # review MEDIUM: os.path.relpath explodes across drives → -i must take the absolute path
        cmd = audio.music_file_cmd(Path("D:/suno/track.mp3"), Path("C:/p/07-audio/.music.tmp.wav"), 38.0, Path("C:/p"))
        self.assertIn("D:/suno/track.mp3", [c.replace("\\", "/") for c in cmd])
        self.assertIn("apad,atrim=0:38.0,afade=t=out:st=35.500:d=2.5", cmd)

    def test_elevenlabs_http_error_is_retryable_not_fatal(self):
        # review MEDIUM: an HTTP error on one line must not abort the whole vo stage
        import gen
        os.environ["ELEVENLABS_API_KEY"] = "x"
        orig, audio.RETRY_DELAY = gen.http_bytes, 0
        gen.http_bytes = lambda *a, **k: (_ for _ in ()).throw(SystemExit("ani: HTTP 429"))
        try:
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(RuntimeError):
                    audio.tts_elevenlabs("สวัสดี", "voice", Path(d) / "x.mp3", {})
        finally:
            gen.http_bytes, audio.RETRY_DELAY = orig, 2.0
            os.environ.pop("ELEVENLABS_API_KEY", None)


import gen


class GenTests(unittest.TestCase):
    def test_plan_collect_by_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "b.mp4", Path(d) / "a.mp4"
            a.write_bytes(b"1"); time.sleep(0.05); b.write_bytes(b"2")
            os.utime(b, (time.time() + 5, time.time() + 5))
            plan = gen.plan_collect(["02", "03"], sorted([b, a], key=lambda p: p.stat().st_mtime))
            self.assertEqual(plan, {"02": a, "03": b})

    def test_plan_collect_fewer_candidates(self):
        self.assertEqual(gen.plan_collect(["01", "02"], [Path("x.mp4")]), {"01": Path("x.mp4")})

    def test_provider_tables(self):
        self.assertEqual(set(gen.IMAGE_PROVIDERS), {"manual", "flow", "gemini", "openai", "fal"})
        self.assertEqual(set(gen.VIDEO_PROVIDERS), {"manual", "flow", "gemini", "fal"})

    def test_need_key_message(self):
        os.environ.pop("ZZ_TEST_KEY", None)
        with self.assertRaises(SystemExit) as cm:
            gen.need_key("ZZ_TEST_KEY")
        self.assertIn("ZZ_TEST_KEY", str(cm.exception))

    def test_run_jobs_keeps_successes_when_one_fails(self):
        # review MEDIUM: parallel provider jobs — one failure must not discard finished siblings
        def work(j):
            if j == 2:
                raise SystemExit("ani: HTTP 500")
            return j * 10

        res = gen._run_jobs(work, [1, 2, 3], parallel=True)
        self.assertEqual([(j, r) for j, r, e in res if e is None], [(1, 10), (3, 30)])
        self.assertEqual([j for j, r, e in res if e is not None], [2])

    def test_collect_map_unknown_scene_refuses_before_moving(self):
        # review MEDIUM: --map 99=file must not relocate the file
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for f in ani.FOLDERS:
                (d / f).mkdir()
            src = d / "dl.mp4"; src.write_bytes(b"v")
            p = ani.apply_defaults(moonpetal())
            with self.assertRaises(SystemExit):
                gen.collect(d, p, "clips", d, 6, {"99": str(src)}, apply=True)
            self.assertTrue(src.exists())
            self.assertEqual(list((d / "05-clips").iterdir()), [])

    def test_vid_flow_uses_the_flow_title_only_for_the_current_image(self):
        page, orig = FakeFlowPage(cost=0), flow.session
        flow.session = lambda cfg: page
        rec = {"status": "downloaded", "media": "scene-03 image 0927-0452", "file": "scene-03.jpg"}
        try:
            with tempfile.TemporaryDirectory() as d:
                for scene, image, want in (({"id": "03", "flow": {"image": dict(rec)}}, "scene-03.jpg", "scene-03 image 0927-0452"),
                                           ({"id": "03", "flow": {"image": dict(rec)}}, "scene-03.png", "scene-03"),  # replaced elsewhere
                                           ({"id": "04"}, "scene-04.png", "scene-04")):
                    cfg = {"scene": scene, "save": lambda: None, "yes": True}
                    gen.vid_flow("motion", Path("03-images") / image, Path(d) / "c.mp4", cfg)
                    self.assertEqual(page.calls[-4][:4], ("prepare", "clip", "motion", (want,)))
        finally:
            flow.session = orig

    def test_img_flow_falls_back_to_the_reference_title(self):
        page, orig = FakeFlowPage(cost=0), flow.session
        flow.session = lambda cfg: page
        try:
            with tempfile.TemporaryDirectory() as d:
                cfg = {"scene": {"id": "01"}, "save": lambda: None}
                gen.img_flow("p", [Path("02-reference/reference.png")], Path(d) / "scene-01.png", cfg)
        finally:
            flow.session = orig
        self.assertEqual(page.calls[1][3], ("reference",))

    def test_other_image_sources_drop_the_stale_flow_record(self):
        stale = {"image": {"status": "downloaded", "media": "scene-01 image old", "file": "scene-01.jpg"}}
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for f in ani.FOLDERS:
                (d / f).mkdir(exist_ok=True)
            p = ani.apply_defaults(moonpetal())
            p["scenes"][0]["flow"] = {k: dict(v) for k, v in stale.items()}
            src = d / "pic.jpg"
            src.write_bytes(b"i")
            gen.collect(d, p, "images", d, 6, {"01": str(src)}, apply=True)
            self.assertNotIn("image", p["scenes"][0]["flow"])

            def fake(prompt, refs, out, cfg):
                out.write_bytes(b"i")
                return out
            gen.IMAGE_PROVIDERS["fake"] = fake
            try:
                p["providers"]["image"] = "fake"
                p["scenes"][0]["flow"] = {k: dict(v) for k, v in stale.items()}
                gen.generate_images(d, p, ["01"], force=True)
            finally:
                del gen.IMAGE_PROVIDERS["fake"]
            self.assertNotIn("image", p["scenes"][0]["flow"])

    def test_veo_duration_snaps_to_allowed(self):
        self.assertEqual(gen.veo_duration(7), 8)
        self.assertEqual(gen.veo_duration(5), 6)   # round up: clip never shorter than the scene
        self.assertEqual(gen.veo_duration(4), 4)
        self.assertEqual(gen.veo_duration(20), 8)


class CliTests(unittest.TestCase):
    def test_new_then_story_mark_status(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(ani.main(["new", "demo", "--root", str(root)]), 0)
            proj = root / "demo"
            self.assertTrue((proj / "project.json").exists())
            template = json.loads((proj / "project.json").read_text(encoding="utf-8"))
            self.assertEqual((template["providers"]["image"], template["providers"]["video"]),
                             ("manual", "manual"))
            self.assertEqual((template["style"], template["characters"], template["reference"]["prompt"]),
                             ("", "", ""))
            self.assertEqual((template["scenes"][0]["image_prompt"], template["scenes"][0]["motion_prompt"]),
                             ("", ""))
            self.assertNotIn("anime", template["motion_suffix"].lower())
            for f in ani.FOLDERS:
                self.assertTrue((proj / f).is_dir(), f)
            self.assertEqual(ani.main(["story", "--project", str(proj)]), 0)
            self.assertIn("Storyboard", (proj / "01-story" / "storyboard.md").read_text("utf-8"))
            self.assertIn("STYLE", (proj / "04-prompts" / "prompts.md").read_text("utf-8"))
            self.assertEqual(ani.main(["mark", "01", "image=redo", "note=หมอก", "--project", str(proj)]), 0)
            p = json.loads((proj / "project.json").read_text("utf-8"))
            self.assertEqual(p["scenes"][0]["qc"]["image"], "redo")
            self.assertEqual(p["scenes"][0]["qc"]["note"], "หมอก")
            self.assertIn("redo", (proj / "status.md").read_text("utf-8"))

    def test_new_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ani.main(["new", "demo", "--root", d]), 0)
            with self.assertRaises(SystemExit):
                ani.main(["new", "demo", "--root", d])

    def test_new_projects_are_independent_and_require_prompts(self):
        with tempfile.TemporaryDirectory() as d:
            for slug in ("first-film", "second-film"):
                self.assertEqual(ani.main(["new", slug, "--root", d]), 0)
                project_dir = Path(d) / slug
                project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
                self.assertEqual(project["slug"], slug)
                with self.assertRaises(SystemExit):
                    ani.main(["validate", "--project", str(project_dir)])
                project["scenes"][0]["image_prompt"] = "A new scene"
                project["scenes"][0]["motion_prompt"] = "A new movement"
                (project_dir / "project.json").write_text(json.dumps(project), encoding="utf-8")
                self.assertEqual(ani.main(["validate", "--project", str(project_dir)]), 0)

    def test_new_rejects_invalid_slug_and_existing_directory(self):
        with tempfile.TemporaryDirectory() as d:
            for slug in ("../other", "a/b", "Bad Name", "."):
                with self.assertRaises(SystemExit):
                    ani.main(["new", slug, "--root", d])
            (Path(d) / "existing").mkdir()
            with self.assertRaises(SystemExit):
                ani.main(["new", "existing", "--root", d])

    def test_unknown_cmd(self):
        with self.assertRaises(SystemExit):
            ani.main(["bogus"])


import flow


class FakeFlowPage:
    """Stands in for the Playwright page: records calls, never touches a browser."""
    def __init__(self, cost=0, fail_submit=False):
        self.cost, self.fail_submit, self.calls = cost, fail_submit, []

    def setup(self, kind):
        self.calls.append(("setup", kind))
        return self.cost

    def prepare(self, kind, prompt, attach):
        self.calls.append(("prepare", kind, prompt, tuple(attach)))

    def submit(self):
        self.calls.append(("submit",))
        if self.fail_submit:
            raise RuntimeError("click lost")
        return None                      # Flow: pending tiles carry no id

    def wait_done(self, media, timeout, name):
        self.calls.append(("wait", media))
        return media or name

    def download(self, media, kind, out):
        self.calls.append(("download", media, kind))
        Path(out).write_bytes(b"x")
        return out


def flow_cfg(scene, kind="clip", **kw):
    """cfg as gen.py builds it; `seen` = status on disk at every save()."""
    seen = []
    return {"scene": scene, "save": lambda: seen.append(scene["flow"][kind]["status"]), **kw}, seen


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "scene-01.mp4"

    def test_state_is_saved_before_every_risky_step(self):
        s = {"id": "01"}
        cfg, seen = flow_cfg(s, yes=True)
        page = FakeFlowPage(cost=10)
        self.assertEqual(flow.make("clip", "p", self.out, cfg, page=page, attach=["scene-01 image x"]), self.out)
        self.assertEqual(seen, ["unknown", "submitted", "submitted", "downloaded"])   # 2nd: finished tile named
        self.assertEqual([c[0] for c in page.calls], ["setup", "prepare", "submit", "wait", "download"])
        self.assertRegex(s["flow"]["clip"]["media"], r"^scene-01 clip \d{4}-\d{6}$")
        self.assertEqual(s["flow"]["clip"]["credits"], 10)

    def test_paid_or_unpriced_generation_waits_for_yes(self):
        for cost in (10, None, 0):           # 0 on a clip = stale/misread price, never trusted
            with self.subTest(cost=cost):
                s = {"id": "01"}
                cfg, seen = flow_cfg(s)
                page = FakeFlowPage(cost=cost)
                self.assertIsNone(flow.make("clip", "p", self.out, cfg, page=page))
                self.assertEqual([c[0] for c in page.calls], ["setup"])
                self.assertEqual((seen, "flow" in s), ([], False))

    def test_free_generation_needs_no_yes(self):
        s = {"id": "01"}
        cfg, seen = flow_cfg(s, kind="image")
        out = self.tmp / "scene-01.png"
        self.assertEqual(flow.make("image", "p", out, cfg, page=FakeFlowPage(cost=0)), out)
        self.assertEqual(seen[-1], "downloaded")

    def test_submitted_job_resumes_without_new_submit(self):
        s = {"id": "01", "flow": {"clip": {"status": "submitted", "at": "t", "media": "m7", "credits": 10}}}
        cfg, _ = flow_cfg(s)          # no --yes: nothing new is spent
        page = FakeFlowPage(cost=10)
        self.assertEqual(flow.make("clip", "p", self.out, cfg, page=page), self.out)
        self.assertEqual(page.calls, [("wait", "m7"), ("download", "m7", "clip")])   # no re-submit
        self.assertEqual((s["flow"]["clip"]["status"], s["flow"]["clip"]["credits"]), ("downloaded", 10))

    def test_unknown_job_blocks_until_force(self):
        s = {"id": "03", "flow": {"clip": {"status": "unknown", "at": "t"}}}
        cfg, _ = flow_cfg(s, yes=True)
        page = FakeFlowPage(cost=10)
        with self.assertRaises(SystemExit) as e:
            flow.make("clip", "p", self.out, cfg, page=page)
        self.assertIn("--force --scene 03", str(e.exception))
        self.assertEqual(page.calls, [])
        cfg["force"] = True
        self.assertEqual(flow.make("clip", "p", self.out, cfg, page=page), self.out)

    def test_submit_error_leaves_unknown_on_disk(self):
        s = {"id": "01"}
        cfg, seen = flow_cfg(s, yes=True)
        with self.assertRaises(RuntimeError):
            flow.make("clip", "p", self.out, cfg, page=FakeFlowPage(cost=10, fail_submit=True))
        self.assertEqual(seen, ["unknown"])

    def _with_page(self, page, fn, *a, **kw):
        orig, flow.session = flow.session, (lambda cfg: page)
        try:
            return fn(*a, **kw)
        finally:
            flow.session = orig

    def _flow_project(self, d, **over):
        providers = {"image": "flow", "video": "flow", "tts": "edge", "music": "synth"}
        proj = ani.apply_defaults({**moonpetal(), "providers": providers, **over})
        (Path(d) / "03-images").mkdir()
        for sc in proj["scenes"]:
            (Path(d) / "03-images" / f"scene-{sc['id']}.png").write_bytes(b"i")
        return proj

    def test_generate_clips_saves_flow_state_and_needs_yes(self):
        with tempfile.TemporaryDirectory() as d:
            proj = self._flow_project(d)
            page = FakeFlowPage(cost=10)
            done, missing = self._with_page(page, gen.generate_clips, Path(d), proj, ["02"])
            self.assertEqual((done, missing, [c[0] for c in page.calls]), ([], ["02"], ["setup"]))
            done, missing = self._with_page(page, gen.generate_clips, Path(d), proj, ["02"], yes=True)
            self.assertEqual(([x.name for x in done], missing), (["scene-02.mp4"], []))
            saved = json.loads((Path(d) / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["scenes"][1]["flow"]["clip"]["status"], "downloaded")

    def test_generate_images_makes_reference_first_and_attaches_it(self):
        with tempfile.TemporaryDirectory() as d:
            proj = self._flow_project(d, reference={"prompt": "sheet", "file": None})
            for f in (Path(d) / "03-images").iterdir():
                f.unlink()
            page = FakeFlowPage(cost=0)
            done, missing = self._with_page(page, gen.generate_images, Path(d), proj, ["01"])
            preps = [c[3] for c in page.calls if c[0] == "prepare"]
            self.assertEqual(preps, [(), (proj["reference"]["flow"]["image"]["media"],)])
            self.assertRegex(preps[1][0], r"^reference image ")
            self.assertEqual((proj["reference"]["flow"]["image"]["status"], missing), ("downloaded", []))

    def test_make_returns_the_file_actually_saved(self):
        # Flow serves images as .jpg even when the scene path says .png — keep the real extension
        class JpgPage(FakeFlowPage):
            def download(self, media, kind, out):
                real = Path(out).with_suffix(".jpg")
                real.write_bytes(b"x")
                return real
        s = {"id": "01"}
        cfg, _ = flow_cfg(s, kind="image")
        got = flow.make("image", "p", self.tmp / "scene-01.png", cfg, page=JpgPage(cost=0))
        self.assertEqual((got.name, s["flow"]["image"]["file"]), ("scene-01.jpg", "scene-01.jpg"))

    def test_new_tile_needs_exactly_one_new_key(self):
        self.assertEqual(flow.new_tile(["a", "n", None, "b"], {"a", "b"}), "n")
        self.assertIsNone(flow.new_tile(["a", None], {"a"}))
        with self.assertRaises(RuntimeError):          # two unknown tiles: never guess which one is ours
            flow.new_tile(["x", "y", "a"], {"a"})

    def test_make_keeps_the_previous_take_in_old(self):
        s = {"id": "01"}
        cfg, _ = flow_cfg(s, yes=True)
        self.out.write_bytes(b"old take")
        self.assertEqual(flow.make("clip", "p", self.out, cfg, page=FakeFlowPage(cost=10)), self.out)
        self.assertEqual(self.out.read_bytes(), b"x")
        self.assertEqual([o.read_bytes() for o in (self.tmp / "_old").iterdir()], [b"old take"])
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()), ["_old", "scene-01.mp4"])   # no temp left

    def test_parse_credits(self):
        self.assertEqual(flow.parse_credits("Generating will use 10 credits"), 10)
        self.assertEqual(flow.parse_credits("การสร้างจะใช้ 0 เครดิต"), 0)
        self.assertEqual(flow.parse_credits("การสร้างจะใช้ 1,000 เครดิต"), 1000)
        self.assertIsNone(flow.parse_credits("Veo 3.1 - Lite"))



import dashboard


class DashboardTests(unittest.TestCase):
    def test_lists_new_and_existing_projects_without_provider_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            film = root / "first-film"
            film.mkdir()
            project = ani.apply_defaults(moonpetal())
            project["provider_config"]["flow"]["project_url"] = "private-flow-url"
            (film / "project.json").write_text(json.dumps(project), encoding="utf-8")
            for folder in ("03-images", "05-clips", "08-final"):
                (film / folder).mkdir()
            (film / "03-images" / "scene-01.png").write_bytes(b"image")
            (film / "05-clips" / "scene-01.mp4").write_bytes(b"clip")
            (film / "08-final" / "final.mp4").write_bytes(b"0123456789")
            ani.cmd_new("second-film", root)

            summaries = dashboard.list_projects(root)
            self.assertEqual({item["slug"] for item in summaries}, {"first-film", "second-film"})
            first = next(item for item in summaries if item["slug"] == "first-film")
            self.assertEqual((first["scene_count"], first["image_count"], first["clip_count"], first["state"]),
                             (5, 1, 1, "review"))
            self.assertEqual((first["voice_count"], first["voice_total"], first["music"]), (0, 5, False))
            detail = dashboard.project_detail(root, "first-film")
            self.assertEqual((detail["scenes"][0]["image"], detail["scenes"][0]["clip"]),
                             ("scene-01.png", "scene-01.mp4"))
            self.assertIn("02", detail["next_step"])
            self.assertNotIn("provider_config", detail)
            self.assertNotIn("private-flow-url", json.dumps(detail))
            self.assertIsNone(dashboard.media_file(root, "..", "final"))
            self.assertIsNone(dashboard.media_file(root, "first-film", "scene", "99"))

    def test_api_and_video_range(self):
        from http.client import HTTPConnection
        from http.server import ThreadingHTTPServer
        from threading import Thread

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            film = root / "demo"
            (film / "08-final").mkdir(parents=True)
            project = ani.apply_defaults({**moonpetal(), "scenes": moonpetal()["scenes"][:1]})
            (film / "project.json").write_text(json.dumps(project), encoding="utf-8")
            (film / "08-final" / "final.mp4").write_bytes(b"0123456789")
            server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.make_handler(root))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request("GET", "/api/projects")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())[0]["slug"], "demo")
                connection.request("GET", "/media/demo/final", headers={"Range": "bytes=2-5"})
                response = connection.getresponse()
                self.assertEqual((response.status, response.getheader("Content-Range"), response.read()),
                                 (206, "bytes 2-5/10", b"2345"))
                connection.request("GET", "/media/%2E%2E/final")
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                connection.request("GET", "/api/projects", headers={"Host": "untrusted.example"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


import mcp_actions


class McpActionTests(unittest.TestCase):
    def _story(self, root, slug, title):
        return mcp_actions.create_story(
            root, slug, title, "original style", "original characters",
            [{"id": "01", "title": "Opening", "seconds": 8, "mood": "calm",
              "image_prompt": f"{title} still", "motion_prompt": f"{title} camera move",
              "vo": [{"speaker": "narrator", "text": title, "offset": 0.5}]}])

    def test_create_multiple_independent_stories_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._story(root, "first-film", "First")
            second = self._story(root, "second-film", "Second")
            self.assertEqual({item["slug"] for item in mcp_actions.list_stories(root)},
                             {"first-film", "second-film"})
            self.assertEqual(first["scenes"][0]["image_prompt"], "First still")
            self.assertEqual(second["scenes"][0]["image_prompt"], "Second still")
            self.assertEqual(json.loads((root / "first-film" / "project.json").read_text(encoding="utf-8"))
                             ["providers"]["video"], "manual")
            with self.assertRaises(ValueError):
                self._story(root, "first-film", "Replacement")
            self.assertEqual(mcp_actions.get_story(root, "first-film")["title"], "First")

    def test_invalid_story_does_not_create_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                mcp_actions.create_story(root, "bad-film", "Bad", "S", "C",
                    [{"id": "../../bad", "seconds": 8, "image_prompt": "a", "motion_prompt": "b"}])
            with self.assertRaises(ValueError):
                mcp_actions.create_story(root, "bad-film", "Bad", "S", "C",
                    [{"id": "01", "seconds": 8, "image_prompt": "", "motion_prompt": "b"}])
            self.assertFalse((root / "bad-film").exists())

    def test_plan_qc_and_safe_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._story(root, "demo", "Demo")
            plan = mcp_actions.plan_media(root, "demo", "images")
            self.assertEqual(([job["scene_id"] for job in plan["jobs"]], plan["provider"]),
                             (["01"], "manual"))
            result = mcp_actions.run_local_stage(root, "demo", "validate")
            self.assertTrue(result["complete"])
            self.assertIn("[validate] ok", result["output"])
            with self.assertRaises(ValueError):
                mcp_actions.run_local_stage(root, "demo", "images")
            detail = mcp_actions.mark_scene(root, "demo", "01", image="redo", note="regenerate")
            self.assertEqual(detail["scenes"][0]["qc"]["image"], "redo")
            with self.assertRaises(ValueError):
                mcp_actions.mark_scene(root, "demo", "01", clip="approved")


if __name__ == "__main__":
    unittest.main(verbosity=1)
