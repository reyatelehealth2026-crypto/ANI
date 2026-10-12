"""Dashboard Flow controller: serialize browser work, preview credits, run existing CLI."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import ani
import agent_workflow
import flow
import flow_auth
import gen
import mcp_actions


class FlowStudio:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.lock = threading.Lock()
        self.connection = {'ready': False, 'message': 'เลือกล็อกอินผ่าน Chrome หรือนำเข้า cookies'}
        self.process = None
        self.job = None
        self.plans = {}

    def status(self):
        cfg = flow_auth.settings(self.root)
        alive = flow.browser_available(cfg)
        return {**self.connection, 'ready': bool(self.connection.get('ready') and alive),
                'browser_open': alive, 'project_url': flow_auth.settings(self.root)['project_url'],
                'job': self.job_status(), 'browser_mode': cfg['browser_mode'],
                'existing_cdp': cfg['cdp'] if cfg['browser_mode'] == 'existing' else 'auto',
                'agent': agent_workflow.status(self.root)}

    def job_status(self):
        if self.job is None:
            return None
        code = self.process.poll()
        log = self.root / '.local' / 'flow-job.log'
        output = log.read_text(encoding='utf-8', errors='replace')[-16000:] if log.exists() else ''
        return {**self.job, 'state': 'running' if code is None else 'complete' if code == 0 else 'error',
                'exit_code': code, 'output': output}

    def busy(self):
        return self.process is not None and self.process.poll() is None

    def action(self, action: str, data: dict):
        if not self.lock.acquire(blocking=False):
            raise ValueError('Flow กำลังทำงาน กรุณารอสักครู่')
        try:
            if self.busy():
                raise ValueError('กำลังสร้างสื่อ รอให้งานเสร็จก่อนเปลี่ยนเซสชัน')
            if action == 'policy':
                agent_workflow.policy(self.root, data.get('enabled'), data.get('credits_per_request'))
                return self.status()
            if action in ('login', 'import', 'check', 'configure', 'existing'):
                if action == 'import':
                    flow_auth.normalize_cookies(data.get('cookies'))
                directory = None
                if action == 'configure':
                    directory = mcp_actions._directory(self.root, data.get('slug', ''))
                    if not flow_auth.project_url(data.get('project_url', '')):
                        raise ValueError('ใส่ URL โปรเจกต์ Flow ก่อน')
                if 'project_url' in data or action in ('existing', 'login', 'import'):
                    mode = 'existing' if action == 'existing' else 'dedicated' if action in ('login', 'import') else None
                    cfg = flow_auth.save_settings(self.root, data.get('project_url', ''), mode, data.get('existing_cdp', 'auto'))
                    self.connection['ready'] = False
                    self.plans.clear()
                else:
                    cfg = flow_auth.settings(self.root)
                # Explicit Chrome login supersedes an imported-cookie backup.
                if action == 'login':
                    Path(cfg['_cookie_store']).unlink(missing_ok=True)
                self.connection = flow_auth.connect(cfg, action, data.get('cookies'))
                if action == 'configure':
                    project = ani.load_project(directory)
                    project['providers'].update(image='flow', video='flow')
                    project['provider_config']['flow'].update(cfg)
                    ani.save_project(directory, project)
                return self.status()
            if action == 'plan':
                return self.plan(data)
            if action == 'run':
                return self.run(data)
            raise ValueError('ไม่พบคำสั่ง Flow')
        finally:
            self.lock.release()

    def snapshot(self, directory, plan):
        connection = self.root / '.local' / 'flow.json'
        return hashlib.sha256((directory / 'project.json').read_bytes() +
                              (connection.read_bytes() if connection.exists() else b'') +
                              json.dumps(plan, sort_keys=True).encode()).hexdigest()

    def media_plan(self, slug, kind):
        directory = mcp_actions._directory(self.root, slug)
        project = ani.load_project(directory)
        plan = mcp_actions.plan_media(self.root, slug, kind)
        if plan['provider'] != 'flow':
            raise ValueError('กดใช้ Flow สำหรับเรื่องที่เลือกก่อน')
        prompt_key = 'image_prompt' if kind == 'images' else 'motion_prompt'
        planned_ids = {job['scene_id'] for job in plan['jobs']}
        if any(not str(scene.get(prompt_key) or '').strip() for scene in project['scenes'] if scene['id'] in planned_ids):
            raise ValueError('กรอก prompt ของทุกฉากที่จะสร้างให้ครบก่อน')
        if kind == 'images' and project.get('reference', {}).get('prompt') and not ani.reference_path(directory, project):
            plan['jobs'].insert(0, {'scene_id': 'reference', 'prompt': project['reference']['prompt']})
        if kind == 'clips' and any(not job['source_image'] for job in plan['jobs']):
            raise ValueError('สร้างภาพของทุกฉากที่จะทำคลิปให้ครบก่อน')
        return directory, project, plan

    def plan(self, data):
        from playwright.sync_api import sync_playwright
        directory, project, plan = self.media_plan(data.get('slug'), data.get('kind'))
        if not plan['jobs']:
            raise ValueError('มีไฟล์ครบแล้ว ไม่มีฉากที่ต้องสร้าง')
        cfg = gen._cfg(project, 'flow')
        was_alive = flow.browser_available(cfg)
        endpoint = flow.launch(cfg)
        with sync_playwright() as pw:
            browser = flow.attach(pw, cfg, endpoint)
            if not was_alive and cfg.get('browser_mode') != 'existing':
                flow_auth.restore_cookies(browser.contexts[0], cfg)
            page = flow.FlowPage(flow._project_page(browser, cfg), cfg)
            cost = page.setup('image' if plan['kind'] == 'images' else 'clip')
        if cost is None or (cost == 0 and plan['kind'] == 'clips'):
            raise ValueError('อ่านเครดิตจาก Flow ไม่ได้ กรุณาตรวจหน้า Chrome และลองอีกครั้ง')
        token = secrets.token_urlsafe(24)
        self.plans = {token: {'created': time.monotonic(), 'snapshot': self.snapshot(directory, plan),
                              'slug': plan['slug'], 'kind': plan['kind'], 'cost': cost}}
        return {**plan, 'token': token, 'credits_per_job': cost,
                'estimated_credits': cost * len(plan['jobs'])}

    def run(self, data):
        rec = self.plans.get(data.get('token'))
        if not rec or time.monotonic() - rec['created'] > 300:
            raise ValueError('แผนหมดอายุ กรุณาดูค่าเครดิตใหม่')
        if data.get('approved') is not True:
            raise ValueError('ยืนยันฉากและเครดิตในแผนก่อนเริ่ม')
        directory, project, plan = self.media_plan(rec['slug'], rec['kind'])
        if self.snapshot(directory, plan) != rec['snapshot']:
            raise ValueError('โปรเจกต์หรือรายการงานเปลี่ยน กรุณาดูค่าเครดิตใหม่')
        env = os.environ.copy()
        env['ANI_FLOW_MAX_CREDITS'] = str(rec['cost'])
        env['PYTHONUNBUFFERED'] = '1'
        logs = self.root / '.local' / 'flow-job.log'
        logs.parent.mkdir(parents=True, exist_ok=True)
        with logs.open('w', encoding='utf-8') as out:
            self.process = subprocess.Popen([sys.executable, str(self.root / 'tools' / 'ani.py'),
                                             rec['kind'], '--project', str(directory), '--yes'],
                                            cwd=self.root, env=env, stdout=out, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.plans.clear()
        self.job = {'slug': rec['slug'], 'kind': rec['kind']}
        return self.job_status()
