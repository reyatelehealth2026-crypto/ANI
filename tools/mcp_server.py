"""ANI MCP server, launched over stdio from a cloned repository."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import Thread
from http.server import ThreadingHTTPServer

import ani

try:
    from fastmcp import FastMCP
except ModuleNotFoundError:
    # .mcp.json / plugin launch bare `python`; hand off to a venv where requirements.txt is installed.
    _bin = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    _venv = next((d / ".venv" / _bin for d in (ani.TOOLS_DIR.parent, ani.ROOT) if (d / ".venv" / _bin).exists()), None)
    if _venv is None or Path(sys.executable).resolve() == _venv.resolve():
        raise SystemExit("ani-studio: ไม่พบ fastmcp — รัน `python -m pip install -r requirements.txt` "
                         f"หรือสร้าง .venv ใน {ani.ROOT}")
    sys.exit(subprocess.call([str(_venv), __file__, *sys.argv[1:]]))

import agent_workflow
import dashboard
import mcp_actions


ROOT = ani.ROOT
server = FastMCP(name="ani-studio", instructions=(
    "Create an independent story for each new user request with create_story; never reuse an old story's "
    "characters or prompts unless asked. Inspect with get_story/list_stories and open_dashboard. "
    "Inspect Flow with your browser tool and report_flow_session. Design fresh scenes from the user's prompt. "
    "Read get_agent_status for the saved standing budget; within it do not ask repeatedly for credits. "
    "Read current Flow price and reserve_agent_generation BEFORE each submit. Submit only when submit=true; "
    "otherwise resume the existing job. Stop on budget excess or unreadable prices. "
    "Download original media, collect_agent_result, inspect contact/frames, mark_scene, and run local stages."
))
_dashboard = None


@server.tool(annotations={"readOnlyHint": True})
def get_agent_status() -> dict:
    """Read verified Flow session and saved automatic credit limit per fresh story/request."""
    return agent_workflow.status(ROOT)


@server.tool()
def report_flow_session(page_url: str, logged_in: bool) -> dict:
    """Report after inspecting current Flow account control in the agent's browser. Never infer login from cookies or old media."""
    return agent_workflow.report_session(ROOT, page_url, logged_in)


@server.tool()
def reserve_agent_generation(slug: str, scene_id: str, kind: str, credits: int) -> dict:
    """Reserve current displayed credits within saved budget before one browser submit. submit=false means resume, never resubmit."""
    return agent_workflow.reserve(ROOT, slug, scene_id, kind, credits)


@server.tool()
def collect_agent_result(slug: str, token: str, file_path: str, media_title: str) -> dict:
    """Import a downloaded result, preserve originals, record Flow job, build contact/frames and update dashboard."""
    return agent_workflow.collect_result(ROOT, slug, token, file_path, media_title)


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
