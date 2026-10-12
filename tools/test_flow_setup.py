"""Flow setup and credit approval tests; no real login or media generation."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import ani
import dashboard
import flow
import flow_auth
import flow_studio


class CookieTests(unittest.TestCase):
    def test_blank_import_url_preserves_saved_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            url = 'https://flow.google.com/project/demo'
            flow_auth.save_settings(root, url)
            self.assertEqual(flow_auth.save_settings(root, '')['project_url'], url)

    def test_detail_url_normalized_to_project_grid(self):
        self.assertEqual(flow_auth.project_url('https://flow.google.com/project/demo/edit/asset?x=1'),
                         'https://flow.google.com/project/demo')

    def test_netscape_session_httponly_and_host_scope(self):
        text = '\ufeff# Netscape HTTP Cookie File\n# comment\n' + '\n'.join([
            '.google.com\tTRUE\t/\tTRUE\t0\tSESSION_TEST\ttest-value',
            '#HttpOnly_flow.google.com\tFALSE\t/\tTRUE\t4102444800\tFLOW_TEST\ta=b',
            'google.com\tTRUE\t/\tFALSE\t4102444800\tDOMAIN_TEST\tx',
            'example.com\tFALSE\t/\tFALSE\t4102444800\tUNRELATED\tskip',
        ])
        cookies = flow_auth.normalize_cookies(text)
        self.assertEqual(len(cookies), 3)
        self.assertNotIn('expires', cookies[0])
        self.assertTrue(cookies[1]['httpOnly'])
        self.assertEqual(cookies[1]['domain'], 'flow.google.com')
        self.assertEqual(cookies[1]['value'], 'a=b')
        self.assertEqual(cookies[2]['domain'], '.google.com')

    def test_netscape_errors_do_not_reveal_values(self):
        secret = 'test-only-sensitive-value'
        for text in [secret, '.google.com\tTRUE\t/\tTRUE\tbad\tS\t' + secret,
                     '.google.com\tTRUE\t/\tMAYBE\t0\tS\t' + secret]:
            with self.assertRaises(ValueError) as error:
                flow_auth.normalize_cookies(text)
            self.assertNotIn(secret, str(error.exception))

    def test_json_text_detected_automatically(self):
        cookies = flow_auth.normalize_cookies('[{"name":"S","value":"test-only","domain":".google.com"}]')
        self.assertEqual(cookies[0]['name'], 'S')

    def test_netscape_empty_value_preserved(self):
        cookies = flow_auth.normalize_cookies('.google.com\tTRUE\t/\tTRUE\t0\tEMPTY\t')
        self.assertEqual(cookies[0]['value'], '')

    def test_extension_and_storage_state(self):
        result = flow_auth.normalize_cookies({'cookies': [
            {'name': 'session', 'value': 'test-only', 'domain': '.google.com',
             'expirationDate': time.time() + 100, 'sameSite': 'no_restriction'},
            {'name': 'unrelated', 'value': 'skip', 'domain': 'example.com'},
        ]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sameSite'], 'None')
        self.assertTrue(result[0]['secure'])
        self.assertNotIn('expirationDate', result[0])

    def test_invalid_expired_and_lookalike_domains(self):
        for value in [[], {}, [{'name': 's', 'value': 'x', 'domain': 'google.com.evil.test'}],
                      [{'name': 's', 'value': 'x', 'domain': '.google.com', 'expires': time.time() - 1}],
                      [{'name': 's', 'value': 'x', 'domain': '.google.com', 'expires': float('nan')}]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                flow_auth.normalize_cookies(value)

    @unittest.skipUnless(os.name == 'nt', 'Windows encryption')
    def test_dpapi_roundtrip_and_tamper(self):
        payload = b'test-only-cookie-value'
        encrypted = flow_auth._dpapi(payload)
        self.assertNotIn(payload, encrypted)
        self.assertEqual(flow_auth._dpapi(encrypted, decrypt=True), payload)
        with self.assertRaises(ValueError):
            flow_auth._dpapi(encrypted[:-10], decrypt=True)

    def test_cookie_restore_to_context(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp) / 'cookies.dpapi'
            store.write_bytes(b'encrypted')
            context = Mock()
            context.cookies.return_value = []
            with patch('flow_auth._dpapi', return_value=b'[{"name":"s","value":"x","domain":".google.com"}]'):
                flow_auth.restore_cookies(context, {'_cookie_store': str(store)})
            self.assertEqual(context.add_cookies.call_args.args[0][0]['name'], 's')

    def test_urls_and_local_settings(self):
        for url in ['http://flow.google.com/project/a', 'https://evil.test/project/a',
                    'https://flow.google.com@evil.test/project/a', 'https://flow.google.com/']:
            with self.assertRaises(ValueError):
                flow_auth.project_url(url)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            flow_auth.save_settings(root, 'https://flow.google.com/project/demo')
            cfg = flow_auth.settings(root)
            self.assertEqual(cfg['project_url'], 'https://flow.google.com/project/demo')
            self.assertTrue(Path(cfg['profile_dir']).is_relative_to(root.resolve()))


class ComposerTests(unittest.TestCase):
    def test_existing_button_opens_home_before_project(self):
        page = Mock()
        page.url = flow.FLOW_HOME
        page.title.return_value = 'Google Flow'
        page.get_by_role.return_value.count.return_value = 1
        context = Mock(pages=[page])
        browser = Mock(contexts=[context])
        cfg = {'browser_mode': 'existing', 'project_url': 'https://flow.google.com/project/demo'}
        with patch('flow.browser_available', return_value=True), patch('flow.launch', return_value='endpoint'), \
                patch('flow.attach', return_value=browser), patch('flow.wait_for_composer') as composer, \
                patch('playwright.sync_api.sync_playwright'):
            result = flow_auth.connect(cfg, 'existing')
        self.assertTrue(result['session_ready'])
        self.assertFalse(result['ready'])
        self.assertEqual(result['reason'], 'home_ready')
        page.goto.assert_not_called()
        composer.assert_not_called()
        context.new_page.assert_not_called()

    def test_existing_login_finds_project_in_second_context(self):
        from playwright.sync_api import sync_playwright
        page = Mock()
        page.url = 'https://flow.google.com/project/demo'
        page.title.return_value = 'Flow project'
        first, second = Mock(), Mock()
        first.pages, second.pages = [], [page]
        browser = Mock(contexts=[first, second])
        cfg = {'browser_mode': 'existing', 'project_url': page.url}
        with patch('flow.browser_available', return_value=True), patch('flow.launch', return_value='endpoint'), \
                patch('flow.attach', return_value=browser), patch('flow.wait_for_composer'), \
                patch('playwright.sync_api.sync_playwright'):
            result = flow_auth.connect(cfg, 'check')
        self.assertTrue(result['ready'])
        first.new_page.assert_not_called()
        second.new_page.assert_not_called()
        page.goto.assert_not_called()

    def test_existing_mode_never_launches_another_chrome(self):
        cfg = {'browser_mode': 'existing', 'cdp': 'http://127.0.0.1:9222'}
        with patch('flow._alive', return_value=False), patch('flow.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                flow.launch(cfg)
            launch.assert_not_called()

    def test_existing_mode_discovers_native_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            port = Path(temp) / 'Google' / 'Chrome' / 'User Data' / 'DevToolsActivePort'
            port.parent.mkdir(parents=True)
            port.write_text('9222\n/devtools/browser/test-id\n')
            with patch.dict(os.environ, {'LOCALAPPDATA': temp}):
                self.assertEqual(flow.existing_endpoint({'cdp': 'auto'}), 'ws://127.0.0.1:9222/devtools/browser/test-id')
        for endpoint in ('http://remote.test:9222', 'ws://127.0.0.1:9222/devtools/browser/x?token=1'):
            with self.assertRaises(ValueError):
                flow.validate_local_endpoint(endpoint)

    def test_existing_mode_rejects_missing_project_without_new_tab(self):
        browser = Mock()
        context = Mock()
        context.pages = []
        browser.contexts = [context]
        with self.assertRaises(SystemExit):
            flow._project_page(browser, {'browser_mode': 'existing', 'project_url': 'https://flow.google.com/project/demo'})
        context.new_page.assert_not_called()

    def test_existing_mode_saved_across_restarts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            flow_auth.save_settings(root, 'https://flow.google.com/project/demo', 'existing')
            cfg = flow_auth.settings(root)
            self.assertEqual(cfg['browser_mode'], 'existing')
            self.assertEqual(cfg['cdp'], 'auto')
            flow_auth.save_settings(root, '')
            self.assertEqual(flow_auth.settings(root)['browser_mode'], 'existing')

    def test_about_redirect_requires_onboarding(self):
        self.assertEqual(flow_auth.location_reason('https://flow.google.com/about'), 'onboarding_required')
        self.assertEqual(flow_auth.location_reason('https://accounts.google.com/signin'), 'login_required')
        self.assertIsNone(flow_auth.location_reason('https://flow.google.com/project/demo'))
    def test_thai_and_english_composer_in_real_chrome(self):
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        chrome = next((exe for exe in flow.CHROMES if Path(exe).is_file()), None)
        if not chrome:
            self.skipTest('Chrome unavailable')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chrome, headless=True)
            page = browser.new_page()
            try:
                for name, mode in [(flow.UI['settings'], flow.UI['mode']['image']), ('Settings trigger', 'Image')]:
                    page.set_content(f'<button aria-label="{name}">Settings</button><button role="radio">{mode}</button>')
                    flow.wait_for_composer(page, timeout=1000)
                    controller = flow.FlowPage(page, {})
                    self.assertEqual(controller._button(flow.UI['settings']).count(), 1)
                    self.assertEqual(controller._radio(flow.UI['mode']['image']).count(), 1)
                    cost_label = controller.ui['cost']
                    page.set_content(f'<button aria-label="{name}">Settings</button><div>{cost_label}</div><a>10 credits</a>')
                    self.assertEqual(flow.parse_credits(controller._cost_line()), 10)
                page.set_content('<button>Sign in</button>')
                with self.assertRaises(PlaywrightTimeout):
                    flow.wait_for_composer(page, timeout=100)
            finally:
                browser.close()


class CreditTests(unittest.TestCase):
    def test_connection_change_invalidates_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'project.json').write_text('{}')
            studio = flow_studio.FlowStudio(root)
            before = studio.snapshot(root, {})
            flow_auth.save_settings(root, 'https://flow.google.com/project/demo', 'existing')
            self.assertNotEqual(before, studio.snapshot(root, {}))

    def test_changed_credit_stops_before_submit(self):
        page = Mock()
        page.setup.return_value = 20
        scene = {'id': '01'}
        with patch.dict(os.environ, {'ANI_FLOW_MAX_CREDITS': '10'}), self.assertRaises(SystemExit):
            flow.make('clip', 'prompt', Path('unused.mp4'), {'scene': scene, 'save': Mock(), 'yes': True}, page=page)
        page.submit.assert_not_called()
        self.assertNotIn('flow', scene)

    def test_unknown_price_stops_before_submit(self):
        page = Mock()
        page.setup.return_value = None
        with patch.dict(os.environ, {'ANI_FLOW_MAX_CREDITS': '10'}), self.assertRaises(SystemExit):
            flow.make('clip', 'prompt', Path('unused.mp4'), {'scene': {'id': '01'}, 'save': Mock(), 'yes': True}, page=page)
        page.submit.assert_not_called()

    def test_run_requires_approval_and_fresh_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / 'demo'
            directory.mkdir()
            (directory / 'project.json').write_text('{}')
            studio = flow_studio.FlowStudio(root)
            plan = {'slug': 'demo', 'kind': 'images', 'jobs': [{'scene_id': '01'}]}
            studio.plans['token'] = {'created': time.monotonic(), 'snapshot': studio.snapshot(directory, plan),
                                      'slug': 'demo', 'kind': 'images', 'cost': 10}
            with self.assertRaises(ValueError):
                studio.run({'token': 'token'})
            (directory / 'project.json').write_text('{"changed":true}')
            with patch.object(studio, 'media_plan', return_value=(directory, {}, plan)), patch('flow_studio.subprocess.Popen') as process:
                with self.assertRaises(ValueError):
                    studio.run({'token': 'token', 'approved': True})
                process.assert_not_called()

    def test_run_consumes_token_and_passes_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / 'demo'
            directory.mkdir()
            (directory / 'project.json').write_text('{}')
            studio = flow_studio.FlowStudio(root)
            plan = {'slug': 'demo', 'kind': 'images', 'jobs': [{'scene_id': '01'}]}
            studio.plans['token'] = {'created': time.monotonic(), 'snapshot': studio.snapshot(directory, plan),
                                      'slug': 'demo', 'kind': 'images', 'cost': 10}
            with patch.object(studio, 'media_plan', return_value=(directory, {}, plan)), patch('flow_studio.subprocess.Popen') as process:
                process.return_value.poll.return_value = None
                result = studio.action('run', {'token': 'token', 'approved': True})
                self.assertEqual(result['state'], 'running')
                self.assertEqual(process.call_args.kwargs['env']['ANI_FLOW_MAX_CREDITS'], '10')
                self.assertIn('--yes', process.call_args.args[0])
                self.assertFalse(studio.plans)
                with self.assertRaises(ValueError):
                    studio.action('login', {})


class EndpointTests(unittest.TestCase):
    def test_origin_restrictions_and_size_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.make_handler(Path(temp)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base + '/api/flow/status') as response:
                    self.assertFalse(json.load(response)['ready'])
                for origin in ['', 'https://evil.test']:
                    req = Request(base + '/api/flow/login', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': origin})
                    with self.assertRaises(HTTPError) as error:
                        urlopen(req)
                    self.assertEqual(error.exception.code, 403)
                req = Request(base + '/api/flow/login', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': base})
                with patch('flow_studio.FlowStudio.action', return_value={'ready': False}) as action:
                    with urlopen(req) as response:
                        self.assertEqual(response.status, 200)
                    action.assert_called_once_with('login', {})
                req = Request(base + '/api/flow/import', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': base, 'Content-Length': '3000000'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(req)
                self.assertEqual(error.exception.code, 413)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
