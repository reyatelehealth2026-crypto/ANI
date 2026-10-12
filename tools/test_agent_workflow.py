"""Standing budget, duplicate protection, verified status and result collection."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import ani
import agent_workflow as workflow


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'demo'
        self.directory.mkdir()
        project = ani.apply_defaults({'slug': 'demo', 'title': 'Test', 'scenes': [
            {'id': '01', 'seconds': 8, 'image_prompt': 'cat', 'motion_prompt': 'blink'},
            {'id': '02', 'seconds': 8, 'image_prompt': 'cat', 'motion_prompt': 'blink'}]})
        ani.save_project(self.directory, project)
        workflow.policy(self.root, True, 10)
        workflow.report_session(self.root, 'https://flow.google.com/', True)

    def test_status_requires_fresh_verified_login(self):
        workflow.report_session(self.root, 'https://flow.google.com/', False)
        self.assertFalse(workflow.status(self.root)['ready'])
        with self.assertRaises(ValueError):
            workflow.report_session(self.root, 'https://evil.test/', True)
        self.assertTrue(workflow.report_session(self.root, 'https://flow.google.com/', True)['ready'])
        with patch('agent_workflow.time.time', return_value=time.time() + 901):
            self.assertFalse(workflow.status(self.root)['ready'])
        self.assertFalse(workflow.report_session(self.root, 'https://flow.google.com/', False)['ready'])

    def test_budget_is_shared_across_all_jobs_and_repeats_resume(self):
        image = workflow.reserve(self.root, 'demo', '01', 'image', 0)
        clip = workflow.reserve(self.root, 'demo', '01', 'clip', 10)
        self.assertTrue(image['submit'])
        self.assertEqual(clip['remaining_credits'], 0)
        repeated = workflow.reserve(self.root, 'demo', '01', 'clip', 10)
        self.assertFalse(repeated['submit'])
        self.assertEqual(repeated['token'], clip['token'])
        with self.assertRaises(ValueError):
            workflow.reserve(self.root, 'demo', '02', 'clip', 10)
        self.assertNotIn('flow', ani.load_project(self.directory)['scenes'][1])

    def test_stale_session_prevents_new_submit_but_existing_job_can_resume(self):
        job = workflow.reserve(self.root, 'demo', '01', 'image', 0)
        with patch('agent_workflow.time.time', return_value=time.time() + 901):
            self.assertFalse(workflow.reserve(self.root, 'demo', '01', 'image', 0)['submit'])
            with self.assertRaises(ValueError):
                workflow.reserve(self.root, 'demo', '02', 'image', 0)

    def test_media_plan_uses_standing_flow_budget_only(self):
        import mcp_actions
        project = ani.load_project(self.directory)
        project['providers']['image'] = 'flow'
        ani.save_project(self.directory, project)
        plan = mcp_actions.plan_media(self.root, 'demo', 'images')
        self.assertFalse(plan['needs_approval'])
        self.assertEqual(plan['standing_budget']['credits_per_request'], 10)
        project['providers']['image'] = 'openai'
        ani.save_project(self.directory, project)
        self.assertTrue(mcp_actions.plan_media(self.root, 'demo', 'images')['needs_approval'])

    def test_disabled_or_unreadable_pricing_does_not_reserve(self):
        for credits in (-1, 0, True, 2.5):
            with self.assertRaises(ValueError):
                workflow.reserve(self.root, 'demo', '01', 'clip', credits)
        workflow.policy(self.root, False, 10)
        with self.assertRaises(ValueError):
            workflow.reserve(self.root, 'demo', '01', 'image', 0)
        self.assertFalse(workflow._read(self.root)['requests'])

    def test_collection_preserves_source_updates_dashboard_and_is_idempotent(self):
        job = workflow.reserve(self.root, 'demo', '01', 'image', 0)
        source = self.root / 'download.jpg'
        Image.new('RGB', (40, 60), 'orange').save(source)
        workflow.collect_result(self.root, 'demo', job['token'], str(source), 'cat image')
        self.assertTrue(source.exists())
        self.assertTrue((self.directory / '03-images/scene-01.jpg').exists())
        self.assertTrue((self.directory / '03-images/contact-sheet.jpg').exists())
        scene = ani.load_project(self.directory)['scenes'][0]
        self.assertEqual(scene['flow']['image']['status'], 'downloaded')
        self.assertEqual(scene['flow']['image']['media'], 'cat image')
        workflow.collect_result(self.root, 'demo', job['token'], str(source), 'cat image')
        self.assertEqual(len(list((self.directory / '03-images').glob('scene-01.*'))), 1)

    def test_invalid_result_leaves_reservation_available_for_resume(self):
        job = workflow.reserve(self.root, 'demo', '01', 'image', 0)
        source = self.root / 'fake.jpg'
        source.write_text('not an image')
        with self.assertRaises(Exception):
            workflow.collect_result(self.root, 'demo', job['token'], str(source), 'cat')
        self.assertEqual(workflow._read(self.root)['requests']['demo']['01:image']['state'], 'reserved')
        self.assertFalse((self.directory / '03-images/scene-01.jpg').exists())


if __name__ == '__main__':
    unittest.main()
