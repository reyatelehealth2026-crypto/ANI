---
name: ani-studio
description: Create a fresh ANI short-film story, run its production (images, clips, QC, VO, mix) and open the local dashboard through the ANI MCP tools. Use when the user asks for a new story/animation/short film, its status, or the dashboard (เรื่องใหม่, หนังสั้น, อนิเมชัน, สรุปงาน, เปิดแดชบอร์ด).
---

# ANI Studio

## New story
Invent a new slug and an original title, style, characters, and scene-by-scene image/motion prompts (EN prompts, Thai VO ≤14 words per line). Call `create_story` once with the full story; it creates a separate project and never replaces an existing one. Do not borrow any existing story's plot, characters, or prompts unless the user asks to continue it.

## Inspect
`list_stories` / `get_story` for status and detail; `open_dashboard` returns a localhost URL for the visual summary. Stories live in `$ANI_ROOT` (plugin default `~/ANI`; inside a cloned repo, the repo itself).

## Paid generation (images / clips)
1. `plan_media` first — it shows scene IDs and provider and spends nothing.
2. `get_agent_status`: if the user saved a standing budget, read the current Flow price and call `reserve_agent_generation` before EVERY submit. Within the budget do not ask about credits again. If it returns `submit=false`, resume the existing job — never generate twice. Stop when the total exceeds the budget or the price cannot be read.
3. Without a standing budget: show scenes, provider and cost, and wait for explicit approval.
4. After downloading originals, call `collect_agent_result` so the files land in the project and the dashboard.
5. Report Flow login only after `report_flow_session` from the real account control — an open browser is not a login.

## QC and local stages
QC from one image only: `03-images/contact-sheet.jpg` for images, `06-draft/frames-grid.jpg` for clips — never open videos or single frames. Record results with `mark_scene` (redo per scene, not a whole-story force). Run non-credit stages (contact, frames, assemble, vo, music, mix, subs, status) with `run_local_stage`.

`project.json` is the source of truth; storyboard.md / prompts.md / status.md are generated. Do not write ad-hoc ffmpeg/TTS commands — every stage is in the ANI tools.
