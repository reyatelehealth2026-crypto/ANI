# ANI agent guide

- Read `README.md` for setup and `CLAUDE.md` for the pipeline workflow.
- When the user asks for a new story, create a new slug with `python tools/ani.py new <slug>`, then write an original `project.json` from that request. Never reuse a previous film's story, prompts, characters, or output directory unless the user explicitly asks to continue it. Repeat this workflow for every new story; multiple films may coexist.
- Treat each film's `project.json` as the source of truth. Regenerate `01-story/storyboard.md`, `04-prompts/prompts.md`, and `status.md` with `tools/ani.py`; do not edit generated files as source material.
- Use `python tools/ani.py <stage> --project <slug>` for deterministic media work. Extend the code and tests if a stage lacks an option; do not build one-off ffmpeg/TTS scripts for a film.
- Review scene images in `03-images/contact-sheet.jpg` and clips in `06-draft/frames-grid.jpg`. Record QC with `mark <scene-id> image=pass|redo clip=pass|redo`.
- For agent automation, read get_agent_status and honor the user's saved standing budget. Read the current Flow price and reserve_agent_generation before each submit. Within the saved budget, proceed without repeated credit questions; stop if the total exceeds it or pricing cannot be read. A repeated reservation must resume the existing job, never generate again. Without a standing budget, show scenes/provider/cost and obtain approval before `--yes`.
- The dashboard is a status/results surface. Users describe work to the agent; the agent designs fresh scenes, controls its supported Flow browser, downloads originals, calls collect_agent_result, checks contact/frames and records QC. Report login only after observing the current account control; do not equate an open browser with login or claim CDP automation works when it does not.
- Run `python tools/test_ani.py` after code changes when Python is available. Keep changes focused on the affected stage.
- Use `python tools/ani.py ui` to show the local read-only project dashboard when the user asks for a visual summary or scene details.
- When ANI MCP tools are available, use `create_story` with original scenes for each new request, `get_story`/`list_stories` for progress, and `open_dashboard` for a visual summary. Use `plan_media` before any paid generation; the MCP tool intentionally does not spend credits.
- Do not commit `.env`, film `project.json` files, generated media, or account-specific Flow URLs. These are ignored by `.gitignore`.
