"""Local Flow setup. Cookie backups are encrypted for the current Windows user."""
from __future__ import annotations

import ctypes
import json
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import flow


def project_url(value: str) -> str:
    value = str(value or '').strip()
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in ('flow.google.com', 'labs.google')
            or parsed.username or parsed.password or parsed.port
            or '/project/' not in parsed.path or not parsed.path.split('/project/', 1)[1]):
        raise ValueError('ใช้ URL โปรเจกต์ Flow แบบ https://flow.google.com/.../project/...')
    # A copied detail/tools URL must return to the project grid, never the asset editor.
    prefix, suffix = parsed.path.split('/project/', 1)
    return f'https://{parsed.hostname}{prefix}/project/{suffix.split("/", 1)[0]}'


def settings(root: Path) -> dict:
    path = Path(root) / '.local' / 'flow.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {
        'browser_mode': data.get('browser_mode', 'dedicated'),
        'cdp': data.get('existing_cdp', 'auto') if data.get('browser_mode') == 'existing' else 'http://127.0.0.1:9443',
        'profile_dir': str(Path(root).resolve() / '.local' / 'chrome-flow'),
        'project_url': project_url(data.get('project_url', '')),
        '_cookie_store': str(Path(root).resolve() / '.local' / 'flow-cookies.dpapi'),
    }


def save_settings(root: Path, url: str, browser_mode: str | None = None, existing_cdp: str = 'auto') -> dict:
    cfg = settings(root)
    cfg['project_url'] = project_url(url) or cfg['project_url']
    if browser_mode is not None:
        if browser_mode not in ('existing', 'dedicated'):
            raise ValueError('โหมด Chrome ไม่ถูกต้อง')
        if browser_mode == 'existing':
            flow.validate_local_endpoint(existing_cdp)
        cfg['browser_mode'] = browser_mode
        cfg['cdp'] = existing_cdp if browser_mode == 'existing' else 'http://127.0.0.1:9443'
    path = Path(root) / '.local' / 'flow.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'project_url': cfg['project_url'], 'browser_mode': cfg['browser_mode'],
                               'existing_cdp': cfg['cdp'] if cfg['browser_mode'] == 'existing' else 'auto'}, indent=2), encoding='utf-8')
    tmp.replace(path)
    return cfg


def normalize_cookies(payload) -> list[dict]:
    """Accept storageState, extension JSON or Netscape text, filtering unrelated domains."""
    if isinstance(payload, str):
        text = payload.lstrip('\ufeff')
        if text.lstrip().startswith(('[', '{')):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError('ไฟล์ cookies JSON ไม่ถูกต้อง') from None
        else:
            payload = netscape_cookies(text)
    raw = payload.get('cookies') if isinstance(payload, dict) else payload
    if not isinstance(raw, list) or not raw or len(raw) > 1000:
        raise ValueError('ไฟล์ต้องเป็น Netscape cookies.txt หรือ JSON cookies/storageState')
    cookies = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('รายการ cookies ไม่ถูกต้อง')
        domain = str(item.get('domain', '')).lower()
        host = domain.lstrip('.')
        if not (host == 'google.com' or host.endswith('.google.com') or host == 'labs.google'):
            continue
        name, value = item.get('name'), item.get('value')
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise ValueError('cookie ต้องมี name และ value เป็นข้อความ')
        cookie = {'name': name, 'value': value, 'domain': domain,
                  'path': item.get('path') or '/', 'secure': bool(item.get('secure', True)),
                  'httpOnly': bool(item.get('httpOnly', False))}
        if not isinstance(cookie['path'], str) or not cookie['path'].startswith('/'):
            raise ValueError('cookie path ไม่ถูกต้อง')
        expiry = item.get('expires', item.get('expirationDate', -1))
        if expiry is not None:
            try:
                expiry = float(expiry)
            except (TypeError, ValueError):
                raise ValueError('วันหมดอายุ cookie ไม่ถูกต้อง') from None
            if not math.isfinite(expiry):
                raise ValueError('วันหมดอายุ cookie ไม่ถูกต้อง')
            if expiry > 0:
                if expiry <= time.time():
                    continue
                cookie['expires'] = expiry
        same_site = {'strict': 'Strict', 'lax': 'Lax', 'none': 'None',
                     'no_restriction': 'None'}.get(str(item.get('sameSite', '')).lower())
        if same_site:
            cookie['sameSite'] = same_site
            if same_site == 'None':
                cookie['secure'] = True
        cookies.append(cookie)
    if not cookies:
        raise ValueError('ไม่พบ Google/Flow cookies ที่ยังไม่หมดอายุในไฟล์นี้')
    return cookies


def netscape_cookies(text: str) -> list[dict]:
    """Seven tab-separated fields; #HttpOnly_ lines are cookies, expiry 0 is session."""
    cookies = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip('\r')
        if not line.strip():
            continue
        http_only = line.startswith('#HttpOnly_')
        if http_only:
            line = line[len('#HttpOnly_'):]
        elif line.lstrip().startswith('#'):
            continue
        fields = line.split('\t', 6)
        if len(fields) != 7:
            raise ValueError(f'cookies.txt บรรทัด {number} ต้องมี 7 ช่องคั่นด้วย Tab')
        domain, subdomains, path, secure, expires, name, value = fields
        if subdomains.upper() not in ('TRUE', 'FALSE') or secure.upper() not in ('TRUE', 'FALSE'):
            raise ValueError(f'cookies.txt บรรทัด {number} มีค่า TRUE/FALSE ไม่ถูกต้อง')
        try:
            expiry = int(expires)
        except ValueError:
            raise ValueError(f'cookies.txt บรรทัด {number} มีวันหมดอายุไม่ถูกต้อง') from None
        if expiry < 0:
            raise ValueError(f'cookies.txt บรรทัด {number} มีวันหมดอายุไม่ถูกต้อง')
        domain = domain.strip()
        domain = '.' + domain.lstrip('.') if subdomains.upper() == 'TRUE' else domain.lstrip('.')
        cookies.append({'domain': domain, 'path': path, 'secure': secure.upper() == 'TRUE',
                        'expires': expiry if expiry else -1, 'name': name, 'value': value,
                        'httpOnly': http_only})
    return cookies


def _dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != 'nt':
        raise ValueError('การเก็บ cookies แบบเข้ารหัสรองรับ Windows; ใช้ล็อกอินผ่าน Chrome แทน')
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.restype = wintypes.BOOL
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                  ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('เข้ารหัส/ถอดรหัส cookies ของผู้ใช้ Windows นี้ไม่สำเร็จ')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def restore_cookies(context, cfg: dict) -> None:
    store = Path(cfg.get('_cookie_store', ''))
    if cfg.get('_cookie_store') and store.is_file():
        try:
            cookies = normalize_cookies(json.loads(_dpapi(store.read_bytes(), decrypt=True)))
            # Keep cookies refreshed by Chrome; restore only missing entries.
            existing = {(c['name'], c['domain'], c['path']) for c in context.cookies()}
            missing = [c for c in cookies if (c['name'], c['domain'], c['path']) not in existing]
            if missing:
                context.add_cookies(missing)
        except Exception:
            raise ValueError('cookies ที่เก็บไว้ใช้ไม่ได้หรือหมดอายุ กรุณาล็อกอินหรือนำเข้าใหม่') from None


def location_reason(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.hostname == 'accounts.google.com':
        return 'login_required'
    if parsed.hostname == 'flow.google.com' and parsed.path.rstrip('/') == '/about':
        return 'onboarding_required'
    return None


def connect(cfg: dict, action: str, payload=None) -> dict:
    """One short-lived Playwright driver; the dedicated Chrome profile stays open."""
    from playwright.sync_api import sync_playwright
    was_alive = flow.browser_available(cfg)
    endpoint = flow.launch(cfg)
    with sync_playwright() as pw:
        browser = flow.attach(pw, cfg, endpoint)
        context = browser.contexts[0]
        if not was_alive and action != 'import' and cfg.get('browser_mode') != 'existing':
            restore_cookies(context, cfg)
        if action == 'import':
            if cfg.get('browser_mode') == 'existing':
                raise ValueError('โหมด Chrome เดิมใช้ล็อกอินที่มีอยู่ ไม่ต้องนำเข้า cookies')
            cookies = normalize_cookies(payload)
            encrypted = _dpapi(json.dumps(cookies).encode('utf-8'))
            try:
                context.add_cookies(cookies)
            except Exception:
                raise ValueError('Chrome รับ cookies ไม่สำเร็จ ตรวจรูปแบบไฟล์แล้วลองใหม่') from None
            store = Path(cfg['_cookie_store'])
            store.parent.mkdir(parents=True, exist_ok=True)
            tmp = store.with_suffix('.tmp')
            tmp.write_bytes(encrypted)
            tmp.replace(store)
        opening_home = action in ('existing', 'login', 'import')
        url = flow.FLOW_HOME if opening_home else cfg.get('project_url') or flow.FLOW_HOME
        pages = [p for c in browser.contexts for p in c.pages] if cfg.get('browser_mode') == 'existing' else context.pages
        page = next((p for p in pages if p.url.split('?')[0].rstrip('/') == url.rstrip('/')), None)
        if page is None and cfg.get('browser_mode') == 'existing' and not opening_home:
            raise ValueError('เปิดแท็บโปรเจกต์ Flow ตาม URL นี้ใน Chrome เดิมก่อน แล้วกดเชื่อมต่ออีกครั้ง')
        if page is None and cfg.get('browser_mode') == 'existing' and not any(urlsplit(p.url).hostname in ('flow.google.com', 'labs.google') for p in pages):
            raise ValueError('Chrome ที่อนุญาตการเชื่อมต่อยังไม่มีแท็บ Flow — เปิด https://flow.google.com/ ในโปรไฟล์นั้น หรือเปิด Remote debugging ในโปรไฟล์ที่ล็อกอิน Flow อยู่')
        page = page or next((p for p in pages if urlsplit(p.url).hostname in ('flow.google.com', 'labs.google')), None) or context.new_page()
        if action in ('login', 'import') or page.url.split('?')[0].rstrip('/') != url.rstrip('/'):
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.bring_to_front()
        ready = False
        reason = 'missing_project'
        if cfg.get('project_url') and not opening_home:
            try:
                redirected = location_reason(page.url)
                if redirected:
                    reason = redirected
                else:
                    flow.wait_for_composer(page, timeout=20000)
                    ready = True
                    reason = 'ready'
            except Exception:
                reason = 'login_required' if urlsplit(page.url).hostname == 'accounts.google.com' else 'project_unavailable'
                text = page.locator('body').inner_text(timeout=5000).lower()
                if any(term in text for term in ("don't have access", 'not available in your country', 'ไม่มีสิทธิ์เข้าถึง', 'ไม่พร้อมให้บริการในประเทศ')):
                    reason = 'access_denied'
                elif any(term in text for term in ('sign in to', 'ลงชื่อเข้าใช้', 'log in to')):
                    reason = 'login_required'
                elif any(term in text for term in ('something went wrong', 'เกิดข้อผิดพลาด', 'could not load')):
                    reason = 'flow_error'
        session_ready = ready or page.get_by_role('button', name=re.compile(r'^(Account details|รายละเอียดบัญชี)$')).count() > 0
        messages = {'ready': 'เชื่อมต่อ Flow พร้อมสร้างแล้ว',
                    'missing_project': 'นำเข้าเซสชันแล้ว แต่ยังไม่ได้ระบุ URL โปรเจกต์ Flow — ใส่ URL แล้วกดตรวจสอบ',
                    'login_required': 'Google ให้ลงชื่อเข้าใช้อีกครั้ง — ล็อกอินในหน้าต่าง Chrome ของ ANI แล้วตรวจสอบใหม่',
                    'onboarding_required': 'Flow พาไปหน้าเริ่มต้น (/about) แทนโปรเจกต์ — กด Start creating ใน Chrome ของ ANI และลงชื่อเข้าใช้ แล้วกดตรวจสอบอีกครั้ง',
                    'access_denied': 'Flow แจ้งว่าบัญชีหรือพื้นที่นี้ไม่มีสิทธิ์เข้าใช้งาน — ตรวจสิทธิ์ใน Chrome ของ ANI',
                    'flow_error': 'หน้า Google Flow แจ้งข้อผิดพลาดในการโหลด — ลองรีโหลดใน Chrome ของ ANI แล้วตรวจสอบใหม่',
                    'project_unavailable': 'เข้าโปรเจกต์ Flow ไม่ได้ — ตรวจว่าโปรเจกต์เป็นของบัญชีที่นำเข้า หรือเปิดโปรเจกต์ใน Chrome ของ ANI ก่อน'}
        if opening_home:
            reason = 'home_ready' if session_ready else 'login_required'
            messages['home_ready'] = 'เปิดหน้าแรก Flow แล้วและล็อกอินอยู่ — เลือกโปรเจกต์ใน Flow จากนั้นใส่ URL แล้วกดตรวจสอบ'
            messages['login_required'] = 'เปิดหน้าแรก Flow แล้ว — ลงชื่อเข้าใช้ใน Chrome แล้วเลือกโปรเจกต์ที่ต้องการ'
        return {'ready': ready, 'session_ready': session_ready, 'reason': reason, 'browser_open': True,
                'project_url': cfg.get('project_url', ''), 'message': messages[reason],
                'page_location': f'{urlsplit(page.url).scheme}://{urlsplit(page.url).netloc}{urlsplit(page.url).path}',
                'page_title': page.title()}
