---
name: ani-studio
description: Create a fresh ANI short-film story, inspect its production state, and open the local dashboard through the ANI MCP tools.
---

# ANI Studio

For a new story request, invent a new slug and original title, style, characters, and scene-by-scene image/motion prompts. Call `create_story` once with the full story; it creates a separate project and never replaces an existing one. Do not borrow any existing story's plot, characters, or prompts unless the user asks to continue it.

Use `list_stories` and `get_story` for status and detail. Use `open_dashboard` when the user wants the visual summary. Use `mark_scene` for image/clip QC and `run_local_stage` for deterministic, non-credit stages.

Call `plan_media` before image or clip generation. Show the exact scene IDs and provider, check current pricing, and wait for explicit user approval before running the CLI's paid generation stages. The MCP server does not spend credits. Treat `project.json` as the source of truth; the dashboard is read-only.
