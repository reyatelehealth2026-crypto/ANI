"""ANI MCP server, launched over stdio from a cloned repository."""
from __future__ import annotations

from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer

from fastmcp import FastMCP

import ani
import dashboard
import mcp_actions


ROOT = Path(__file__).resolve().parent.parent
server = FastMCP(name="ani-studio", instructions=(
    "Create an independent story for each new user request with create_story; never reuse an old story's "
    "characters or prompts unless asked. Inspect with get_story/list_stories and open_dashboard. "
    "Use plan_media before paid image/video generation. MCP never spends credits; after showing current "
    "cost and receiving user approval, use the ANI CLI for images/clips."
))
_dashboard = None


@server.tool(annotations={"readOnlyHint": True})
def list_stories() -> list[dict]:
    """List story projects in this clone with scene, asset, and final-video status."""
    return mcp_actions.list_stories(ROOT)


@server.tool(annotations={"readOnlyHint": True})
def get_story(slug: str) -> dict:
    """Show one story's summary, scenes, prompts, narration, QC, and next step."""
    return mcp_actions.get_story(ROOT, slug)


@server.tool()
def create_story(slug: str, title: str, style: str, characters: str,
                 scenes: list[dict], voices: dict[str, str] | None = None) -> dict:
    """Create a NEW independent story; requires fresh scenes with image/motion prompts and never overwrites an old project."""
    return mcp_actions.create_story(ROOT, slug, title, style, characters, scenes, voices)


@server.tool()
def mark_scene(slug: str, scene_id: str, image: str | None = None,
               clip: str | None = None, note: str | None = None) -> dict:
    """Record image/clip QC as pass or redo and optionally add a note for one scene."""
    return mcp_actions.mark_scene(ROOT, slug, scene_id, image, clip, note)


@server.tool(annotations={"readOnlyHint": True})
def plan_media(slug: str, kind: str, force: bool = False) -> dict:
    """Preview pending images or clips, provider, prompts, and approval requirement without calling a paid service."""
    return mcp_actions.plan_media(ROOT, slug, kind, force)


@server.tool()
def run_local_stage(slug: str, stage: str, scene_ids: list[str] | None = None,
                    force: bool = False, burn: bool = False) -> dict:
    """Run validate/story/contact/frames/assemble/vo/music/mix/subs/status; refuses image/video and paid voice/music providers."""
    return mcp_actions.run_local_stage(ROOT, slug, stage, scene_ids, force, burn)


@server.tool(annotations={"readOnlyHint": True})
def open_dashboard() -> dict:
    """Start the existing local read-only visual dashboard and return its localhost URL."""
    global _dashboard
    if _dashboard is None:
        _dashboard = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.make_handler(ROOT))
        _dashboard.daemon_threads = True
        Thread(target=_dashboard.serve_forever, daemon=True).start()
    return {"url": f"http://127.0.0.1:{_dashboard.server_port}/",
            "note": "เปิด URL นี้ใน browser บนเครื่องเดียวกัน; UI อยู่ได้ตราบเท่าที่ MCP server ทำงาน"}


if __name__ == "__main__":
    ani.load_env(ROOT)
    server.run(transport="stdio")
