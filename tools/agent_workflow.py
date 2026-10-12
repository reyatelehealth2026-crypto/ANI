"""Agent session evidence, standing credit budget and idempotent media collection.

The agent operates its supported browser tool; ANI stores verified status and results.
No text-to-image service or language model is hidden behind the dashboard.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import ani
import flow
import flow_auth


def _path(root):
    return Path(root) / '.local' / 'agent-workflow.json'


def _read(root):
    path = _path(root)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
        'policy': {'enabled': False, 'credits_per_request': 10}, 'session': {}, 'requests': {}}


@contextlib.contextmanager
def _edit(root):
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix('.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('เอเจนท์กำลังอัปเดตงาน กรุณาลองอีกครั้ง') from None
    os.close(fd)
    try:
        data = _read(root)
        yield data
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
    finally:
        lock.unlink(missing_ok=True)


def policy(root, enabled: bool, credits_per_request: int):
    if not isinstance(enabled, bool) or isinstance(credits_per_request, bool) or not isinstance(credits_per_request, int) or not 0 <= credits_per_request <= 10000:
        raise ValueError('วงเงินต้องเป็นจำนวนเต็ม 0–10000 เครดิต')
    with _edit(root) as data:
        data['policy'] = {'enabled': enabled, 'credits_per_request': credits_per_request}
    return status(root)


def report_session(root, page_url: str, logged_in: bool):
    """Call only after the agent inspected the current Flow page/account control."""
    from urllib.parse import urlsplit
    url = urlsplit(page_url)
    if url.scheme != 'https' or url.hostname not in ('flow.google.com', 'labs.google') or url.username or url.password or url.port:
        raise ValueError('ต้องเป็นหน้า Google Flow ที่ตรวจจากเบราว์เซอร์แล้ว')
    if not isinstance(logged_in, bool):
        raise ValueError('ต้องระบุผลตรวจล็อกอิน')
    with _edit(root) as data:
        data['session'] = {'logged_in': logged_in, 'checked_at': time.time(),
                           'page_url': f'https://{url.hostname}{url.path}'}
    return status(root)


def status(root):
    data = _read(root)
    session = data['session']
    fresh = 0 <= time.time() - session.get('checked_at', 0) < 900
    ready = bool(fresh and session.get('logged_in'))
    return {'ready': ready, 'policy': data['policy'], 'checked_at': session.get('checked_at'),
            'message': 'ล็อกอิน Flow แล้ว พร้อมให้เอเจนท์ทำงาน' if ready else
                       'เอเจนท์จะตรวจล็อกอิน Flow เมื่อเริ่มคำสั่งของคุณ'}


def reserve(root, slug: str, scene_id: str, kind: str, credits: int):
    """Reserve BEFORE a browser submit; repeated requests must resume, never submit twice."""
    import mcp_actions
    directory = mcp_actions._directory(Path(root), slug)
    project = ani.load_project(directory)
    scene = next((s for s in project['scenes'] if s['id'] == scene_id), None)
    if scene is None or kind not in ('image', 'clip'):
        raise ValueError('ไม่พบฉากหรือประเภทสื่อ')
    if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0 or (kind == 'clip' and credits == 0):
        raise ValueError('อ่านราคา Flow ปัจจุบันให้ได้ก่อนส่งงาน')
    key = f'{scene_id}:{kind}'
    with _edit(root) as data:
        if not data['policy']['enabled']:
            raise ValueError('ยังไม่ได้เปิดโหมดเอเจนท์อัตโนมัติ')
        jobs = data['requests'].setdefault(slug, {})
        if key in jobs:
            return {**jobs[key], 'submit': False, 'message': 'ทำต่องานเดิม ห้ามกดสร้างซ้ำ'}
        session = data['session']
        if not session.get('logged_in') or not 0 <= time.time() - session.get('checked_at', 0) < 900:
            raise ValueError('ตรวจบัญชี Flow ในเบราว์เซอร์แล้วรายงานสถานะล่าสุดก่อนส่งงานใหม่')
        if ani.find_asset(directory, kind, scene_id):
            raise ValueError('ฉากนี้มีไฟล์แล้ว ไม่ส่งงานซ้ำ')
        flow.check_pending(scene, kind)
        used = sum(job['credits'] for job in jobs.values())
        if used + credits > data['policy']['credits_per_request']:
            raise ValueError('เกินวงเงินต่อคำสั่ง หยุดก่อนส่งงานและแจ้งผู้ใช้')
        job = {'token': secrets.token_urlsafe(20), 'credits': credits, 'state': 'reserved',
               'scene_id': scene_id, 'kind': kind, 'at': time.time()}
        project['providers']['image' if kind == 'image' else 'video'] = 'flow'
        observed_url = data['session'].get('page_url', '')
        if '/project/' in observed_url:
            project['provider_config']['flow']['project_url'] = flow_auth.project_url(observed_url)
        flow.mark_state(scene, kind, 'unknown', credits=credits)
        ani.save_project(directory, project)
        jobs[key] = job
    return {**job, 'submit': True, 'remaining_credits': data['policy']['credits_per_request'] - used - credits}


def collect_result(root, slug: str, token: str, file_path: str, media_title: str):
    """Collect a downloaded result for a reserved job; no repeat generation or uploads."""
    import mcp_actions
    directory = mcp_actions._directory(Path(root), slug)
    source = Path(file_path).resolve()
    with _edit(root) as data:
        job = next((j for j in data['requests'].get(slug, {}).values() if j['token'] == token), None)
        if not job:
            raise ValueError('ไม่พบงานที่จองไว้')
        if job['state'] == 'downloaded':
            return mcp_actions.get_story(Path(root), slug)
        kind = job['kind']
        allowed = ani.IMAGE_EXT if kind == 'image' else ani.CLIP_EXT
        if not source.is_file() or source.suffix.lower() not in allowed or not source.stat().st_size:
            raise ValueError('ไฟล์ผลลัพธ์ไม่ถูกต้อง')
        if kind == 'image':
            from PIL import Image
            with Image.open(source) as image:
                image.verify()
        else:
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(source)], capture_output=True, text=True, check=True)
            duration = float(json.loads(result.stdout)['format']['duration'])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError('คลิปไม่มีความยาวที่อ่านได้')
        project = ani.load_project(directory)
        scene = next(s for s in project['scenes'] if s['id'] == job['scene_id'])
        if ani.find_asset(directory, kind, scene['id']):
            raise ValueError('ฉากนี้มีไฟล์แล้ว ไม่เขียนทับผลลัพธ์')
        target = directory / ani.ASSET_DIR[kind] / f"scene-{scene['id']}{source.suffix.lower()}"
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
        flow.mark_state(scene, kind, 'downloaded', credits=job['credits'], media=media_title, file=target.name)
        ani.save_project(directory, project)
        job['state'] = 'downloaded'
        job['media_title'] = media_title
        job['file'] = str(target)
    mcp_actions.run_local_stage(Path(root), slug, 'contact' if kind == 'image' else 'frames')
    return mcp_actions.get_story(Path(root), slug)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='ANI agent workflow; browser work is performed by the calling agent')
    parser.add_argument('action', choices=('status', 'session', 'reserve', 'collect', 'policy'))
    parser.add_argument('--data-file', type=Path, help='JSON arguments, excluding root')
    args = parser.parse_args()
    payload = json.loads(args.data_file.read_text(encoding='utf-8')) if args.data_file else {}
    functions = {'status': status, 'session': report_session, 'reserve': reserve,
                 'collect': collect_result, 'policy': policy}
    try:
        print(json.dumps(functions[args.action](ani.ROOT, **payload), ensure_ascii=False, indent=2))
    except (ValueError, SystemExit) as error:
        parser.exit(1, f'ani: {error}\n')
